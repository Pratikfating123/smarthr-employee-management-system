import csv
import io
from datetime import time
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import User
from attendance.models import Attendance
from leaves.models import LeaveRequest
from reports.exports import safe_text

from .factories import PASSWORD, make_department, make_employee, make_leave_type, make_structure
from .test_attendance import SCHEDULE


class CsvSafetyTests(TestCase):
    def test_formula_prefixes_neutralised(self):
        for bad in ("=1+1", "+cmd", "-2", "@SUM(A1)", "\tx"):
            self.assertTrue(safe_text(bad).startswith("'"), bad)
        self.assertEqual(safe_text("normal"), "normal")
        self.assertEqual(safe_text(5), 5)

    def test_export_escapes_malicious_name(self):
        hr = make_employee(role=User.Role.HR)
        victim = make_employee()
        victim.user.first_name = "=HYPERLINK(\"http://evil\")"
        victim.user.save()
        self.client.login(username=hr.user.username, password=PASSWORD)
        resp = self.client.get(reverse("reports:detail", args=["employee-directory"]), {"export": "csv"})
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        names = [r[1] for r in rows[1:]]
        self.assertTrue(any(n.startswith("'=HYPERLINK") for n in names))
        self.assertFalse(any(n.startswith("=") for n in names))

    def test_xlsx_export_opens_and_is_safe(self):
        hr = make_employee(role=User.Role.HR)
        victim = make_employee()
        victim.user.first_name = ""
        victim.user.last_name = "@bad"  # full name becomes "@bad", which starts with a formula character
        victim.user.save()
        self.client.login(username=hr.user.username, password=PASSWORD)
        resp = self.client.get(reverse("reports:detail", args=["employee-directory"]), {"export": "xlsx"})
        sheet = load_workbook(io.BytesIO(resp.content)).active
        values = [str(c.value) for row in sheet.iter_rows(min_row=2) for c in row if c.value]
        self.assertTrue(any(v == "'@bad" for v in values))
        self.assertFalse(any(v.startswith(("=", "@", "+")) for v in values))


class ReportAuthorizationTests(TestCase):
    def setUp(self):
        self.emp = make_employee()
        self.hr = make_employee(role=User.Role.HR)
        self.hr_pay = make_employee(role=User.Role.HR, can_manage_payroll=True)

    def test_employee_blocked_from_reports_and_exports(self):
        self.client.login(username=self.emp.user.username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("reports:index")).status_code, 403)
        for export in ("", "csv", "xlsx"):
            resp = self.client.get(reverse("reports:detail", args=["employee-directory"]), {"export": export})
            self.assertEqual(resp.status_code, 403, export)

    def test_payroll_report_needs_payroll_permission(self):
        url = reverse("reports:detail", args=["payroll-summary"])
        self.client.login(username=self.hr.user.username, password=PASSWORD)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 403)
        self.client.login(username=self.hr_pay.user.username, password=PASSWORD)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_unknown_report_404_and_anonymous_redirect(self):
        self.client.login(username=self.hr.user.username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("reports:detail", args=["nope"])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("reports:detail", args=["employee-directory"])).status_code, 302)

    def test_every_report_renders_for_authorized_user(self):
        from reports.views import REPORTS

        self.client.login(username=self.hr_pay.user.username, password=PASSWORD)
        for slug in REPORTS:
            self.assertEqual(self.client.get(reverse("reports:detail", args=[slug])).status_code, 200, slug)
            self.assertEqual(self.client.get(reverse("reports:detail", args=[slug]), {"export": "csv"}).status_code, 200, slug)


@override_settings(SMARTHR=SCHEDULE)
class DashboardAggregationTests(TestCase):
    def setUp(self):
        self.hr = make_employee(role=User.Role.HR)
        self.dept = make_department("Aggregation Dept")
        self.today = timezone.localdate()
        self.e1 = make_employee(department=self.dept)
        self.e2 = make_employee(department=self.dept)
        self.e3 = make_employee(department=self.dept)
        Attendance.objects.create(employee=self.e1, date=self.today, check_in=time(9, 0), check_out=time(18, 0), status="present")
        Attendance.objects.create(employee=self.e2, date=self.today, check_in=time(11, 0), status="late")
        self.client.login(username=self.hr.user.username, password=PASSWORD)

    def stats(self, **params):
        resp = self.client.get(reverse("core:dashboard"), params)
        return {s["label"]: s["value"] for s in resp.context["stats"]}, resp

    def test_counts_come_from_database(self):
        stats, resp = self.stats()
        self.assertEqual(stats["Active employees"], 4)  # hr + 3
        self.assertEqual(stats["Present"], 2)  # present + late
        self.assertEqual(stats["Late arrivals"], 1)
        self.assertEqual(stats["Pending leave requests"], 0)
        self.assertEqual(resp.context["early_count"], 1)

    def test_pending_leave_counted_and_listed(self):
        lt = make_leave_type()
        LeaveRequest.objects.create(employee=self.e1, leave_type=lt, start_date=self.today, end_date=self.today, reason="r", days=Decimal("1"))
        stats, resp = self.stats()
        self.assertEqual(stats["Pending leave requests"], 1)
        self.assertEqual(len(resp.context["pending_leaves"]), 1)

    def test_selected_date_changes_numbers(self):
        stats, _ = self.stats(date="2001-01-01")
        self.assertEqual(stats["Present"], 0)

    def test_chart_data_matches_headcount(self):
        _, resp = self.stats()
        data = dict(zip(resp.context["chart_labels"], resp.context["chart_values"]))
        self.assertEqual(data["Aggregation Dept"], 3)

    def test_empty_database_renders(self):
        Attendance.objects.all().delete()
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

    def test_employee_dashboard_has_no_org_stats(self):
        self.client.login(username=self.e1.user.username, password=PASSWORD)
        resp = self.client.get(reverse("core:dashboard"))
        self.assertNotIn("stats", resp.context)
        self.assertEqual(resp.context["employee"], self.e1)
