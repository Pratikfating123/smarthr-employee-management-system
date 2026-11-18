from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from leaves.models import LeaveRequest
from payroll.models import Payroll

from .factories import PASSWORD, make_employee, make_leave_type


class AuthenticationTests(TestCase):
    def setUp(self):
        self.emp = make_employee()

    def test_login_and_redirect(self):
        resp = self.client.post(reverse("accounts:login"), {"username": self.emp.user.username, "password": PASSWORD})
        self.assertRedirects(resp, reverse("core:dashboard"))

    def test_bad_password_rejected(self):
        resp = self.client.post(reverse("accounts:login"), {"username": self.emp.user.username, "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_inactive_user_cannot_login(self):
        self.emp.user.is_active = False
        self.emp.user.save()
        self.client.post(reverse("accounts:login"), {"username": self.emp.user.username, "password": PASSWORD})
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_anonymous_redirected_to_login(self):
        for name in ("core:dashboard", "employees:list", "attendance:list", "leaves:list", "payroll:list", "reports:index"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn(reverse("accounts:login"), resp.url)

    def test_logout_requires_post(self):
        self.client.login(username=self.emp.user.username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertFalse("_auth_user_id" in self.client.session)


class RoleAccessTests(TestCase):
    def setUp(self):
        self.admin = make_employee(role=User.Role.ADMIN)
        self.hr = make_employee(role=User.Role.HR)
        self.hr_payroll = make_employee(role=User.Role.HR, can_manage_payroll=True)
        self.emp = make_employee()
        self.other = make_employee()

    def login(self, e):
        self.client.login(username=e.user.username, password=PASSWORD)

    def test_employee_blocked_from_hr_pages(self):
        self.login(self.emp)
        for url in (reverse("employees:list"), reverse("employees:create"), reverse("departments:list"),
                    reverse("attendance:record"), reverse("reports:index"), reverse("payroll:create"),
                    reverse("payroll:structures"), reverse("core:audit_log")):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_hr_without_payroll_flag_blocked_from_payroll_admin(self):
        self.login(self.hr)
        self.assertEqual(self.client.get(reverse("payroll:create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("payroll:structures")).status_code, 403)
        self.assertEqual(self.client.get(reverse("employees:list")).status_code, 200)

    def test_hr_with_payroll_flag_allowed(self):
        self.login(self.hr_payroll)
        self.assertEqual(self.client.get(reverse("payroll:create")).status_code, 200)

    def test_audit_log_admin_only(self):
        self.login(self.hr)
        self.assertEqual(self.client.get(reverse("core:audit_log")).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("core:audit_log")).status_code, 200)

    def test_employee_cannot_open_other_employee_record(self):
        self.login(self.emp)
        self.assertEqual(self.client.get(reverse("employees:detail", args=[self.other.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("employees:detail", args=[self.emp.pk])).status_code, 200)

    def test_employee_cannot_see_other_leave(self):
        lt = make_leave_type()
        leave = LeaveRequest.objects.create(
            employee=self.other, leave_type=lt, start_date=date(2030, 1, 7), end_date=date(2030, 1, 8), reason="x", days=Decimal("2")
        )
        self.login(self.emp)
        self.assertEqual(self.client.get(reverse("leaves:detail", args=[leave.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("leaves:approve", args=[leave.pk])).status_code, 403)

    def test_employee_cannot_see_other_payslip_or_unapproved_own(self):
        mine = Payroll.objects.create(employee=self.emp, year=2026, month=1, status=Payroll.Status.GENERATED,
                                      **{k: Decimal("100.00") for k in ("basic_salary", "allowances", "other_earnings", "gross_salary", "pf_amount", "tax_amount", "other_deductions", "total_deductions", "net_salary")})
        theirs = Payroll.objects.create(employee=self.other, year=2026, month=1, status=Payroll.Status.APPROVED,
                                        **{k: Decimal("100.00") for k in ("basic_salary", "allowances", "other_earnings", "gross_salary", "pf_amount", "tax_amount", "other_deductions", "total_deductions", "net_salary")})
        self.login(self.emp)
        self.assertEqual(self.client.get(reverse("payroll:detail", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("payroll:detail", args=[mine.pk])).status_code, 404)
        mine.status = Payroll.Status.APPROVED
        mine.save()
        self.assertEqual(self.client.get(reverse("payroll:detail", args=[mine.pk])).status_code, 200)

    def test_state_changes_reject_get(self):
        self.login(self.hr_payroll)
        for name in ("leaves:approve", "leaves:reject", "leaves:cancel", "payroll:approve", "payroll:payment", "employees:status", "departments:toggle"):
            self.assertEqual(self.client.get(reverse(name, args=[1])).status_code, 405, name)
        for name in ("attendance:check_in", "attendance:check_out"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 405, name)
