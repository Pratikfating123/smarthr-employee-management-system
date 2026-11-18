from datetime import date, datetime, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from attendance import services
from attendance.models import Attendance

from .factories import PASSWORD, make_employee

SCHEDULE = {
    "WORK_START": time(9, 30), "WORK_END": time(18, 30), "GRACE_MINUTES": 15, "EARLY_ARRIVAL_MINUTES": 15,
    "HALF_DAY_MIN_HOURS": 4, "WORKING_WEEKDAYS": [0, 1, 2, 3, 4], "ENABLE_SELF_CHECKIN": True,
}


def at(day, hh, mm=0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


@override_settings(SMARTHR=SCHEDULE)
class AttendanceModelAndServiceTests(TestCase):
    def setUp(self):
        self.emp = make_employee()
        self.day = date(2026, 3, 4)

    def test_duplicate_record_blocked_by_database(self):
        Attendance.objects.create(employee=self.emp, date=self.day)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attendance.objects.create(employee=self.emp, date=self.day)

    def test_checkout_before_checkin_invalid(self):
        record = Attendance(employee=self.emp, date=self.day, check_in=time(10), check_out=time(9))
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_db_constraint_on_checkout(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attendance.objects.create(employee=self.emp, date=self.day, check_in=time(10), check_out=time(9))

    def test_worked_duration(self):
        record = Attendance(employee=self.emp, date=self.day, check_in=time(9, 30), check_out=time(18, 15))
        self.assertEqual(record.worked_hours, Decimal("8.75"))
        self.assertEqual(record.worked_display, "8h 45m")

    def test_worked_none_when_missing_punch(self):
        record = Attendance(employee=self.emp, date=self.day, check_in=time(9, 30))
        self.assertIsNone(record.worked_duration)
        self.assertEqual(record.worked_display, "—")

    def test_classification(self):
        self.assertEqual(services.classify_arrival(time(9, 15)), "early")
        self.assertEqual(services.classify_arrival(time(9, 16)), "on_time")
        self.assertEqual(services.classify_arrival(time(9, 45)), "on_time")
        self.assertEqual(services.classify_arrival(time(9, 46)), "late")

    @override_settings(SMARTHR={**SCHEDULE, "WORK_START": time(8, 0), "GRACE_MINUTES": 0})
    def test_classification_uses_configuration(self):
        self.assertEqual(services.classify_arrival(time(8, 1)), "late")
        self.assertEqual(services.classify_arrival(time(7, 45)), "early")

    def test_check_in_late_sets_status(self):
        record = services.check_in_employee(self.emp, at(self.day, 10, 5))
        self.assertEqual(record.status, Attendance.Status.LATE)

    def test_check_in_on_time_and_duplicate_rejected(self):
        record = services.check_in_employee(self.emp, at(self.day, 9, 30))
        self.assertEqual(record.status, Attendance.Status.PRESENT)
        with self.assertRaises(ValidationError):
            services.check_in_employee(self.emp, at(self.day, 9, 40))
        self.assertEqual(Attendance.objects.filter(employee=self.emp, date=self.day).count(), 1)

    def test_check_out_flow(self):
        services.check_in_employee(self.emp, at(self.day, 9, 30))
        record = services.check_out_employee(self.emp, at(self.day, 18, 30))
        self.assertEqual(record.worked_hours, Decimal("9.00"))
        with self.assertRaises(ValidationError):
            services.check_out_employee(self.emp, at(self.day, 19))

    def test_check_out_without_check_in_rejected(self):
        with self.assertRaises(ValidationError):
            services.check_out_employee(self.emp, at(self.day, 18))

    def test_short_day_becomes_half_day(self):
        services.check_in_employee(self.emp, at(self.day, 9, 30))
        record = services.check_out_employee(self.emp, at(self.day, 12, 30))
        self.assertEqual(record.status, Attendance.Status.HALF_DAY)

    def test_early_late_missing_queries(self):
        early = make_employee()
        late = make_employee()
        missing = make_employee()
        Attendance.objects.create(employee=early, date=self.day, check_in=time(9, 0), check_out=time(18, 0))
        Attendance.objects.create(employee=late, date=self.day, check_in=time(10, 30), check_out=time(18, 0), status="late")
        Attendance.objects.create(employee=missing, date=self.day, check_in=time(9, 30))
        self.assertEqual([a.employee_id for a in services.early_arrivals(self.day)], [early.pk])
        self.assertEqual([a.employee_id for a in services.late_arrivals(self.day)], [late.pk])
        self.assertEqual([a.employee_id for a in services.missing_punches(self.day, now=at(date(2026, 3, 5), 10))], [missing.pk])

    def test_todays_missing_checkout_not_flagged_before_work_end(self):
        emp = make_employee()
        Attendance.objects.create(employee=emp, date=self.day, check_in=time(9, 30))
        self.assertEqual(services.missing_punches(self.day, now=at(self.day, 12)).count(), 0)
        self.assertEqual(services.missing_punches(self.day, now=at(self.day, 19)).count(), 1)

    def test_monthly_summary_counts(self):
        for d, status in ((1, "present"), (2, "late"), (3, "absent"), (4, "present")):
            Attendance.objects.create(employee=self.emp, date=date(2026, 3, d), status=status)
        Attendance.objects.create(employee=self.emp, date=date(2026, 4, 1), status="present")  # other month
        from employees.models import Employee

        row = services.monthly_summary(Employee.objects.filter(pk=self.emp.pk), date(2026, 3, 1), date(2026, 3, 31)).get()
        self.assertEqual((row.present_days, row.late_days, row.absent_days), (2, 1, 1))


@override_settings(SMARTHR=SCHEDULE)
class AttendanceViewTests(TestCase):
    def setUp(self):
        self.hr = make_employee(role=User.Role.HR)
        self.emp = make_employee()
        self.other = make_employee()

    def test_employee_sees_only_own_records(self):
        today = timezone.localdate()
        Attendance.objects.create(employee=self.emp, date=today)
        Attendance.objects.create(employee=self.other, date=today)
        self.client.login(username=self.emp.user.username, password=PASSWORD)
        resp = self.client.get(reverse("attendance:list"))
        self.assertEqual([a.employee_id for a in resp.context["page_obj"]], [self.emp.pk])

    def test_hr_creates_then_corrects_same_record(self):
        self.client.login(username=self.hr.user.username, password=PASSWORD)
        base = {"employee": self.emp.pk, "date": "2026-03-04", "status": "present", "check_in": "09:30", "check_out": ""}
        self.client.post(reverse("attendance:record"), base)
        self.client.post(reverse("attendance:record"), {**base, "check_out": "18:00", "notes": "fixed"})
        self.assertEqual(Attendance.objects.filter(employee=self.emp).count(), 1)
        self.assertEqual(Attendance.objects.get(employee=self.emp).check_out, time(18, 0))
        self.assertTrue(self.emp.user.notifications.exists())

    def test_form_rejects_bad_times_and_future_date(self):
        self.client.login(username=self.hr.user.username, password=PASSWORD)
        resp = self.client.post(reverse("attendance:record"), {"employee": self.emp.pk, "date": "2026-03-04", "status": "present", "check_in": "10:00", "check_out": "09:00"})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse("attendance:record"), {"employee": self.emp.pk, "date": "2999-01-01", "status": "present"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_self_checkin_views(self):
        self.client.login(username=self.emp.user.username, password=PASSWORD)
        self.client.post(reverse("attendance:check_in"))
        self.assertEqual(Attendance.objects.filter(employee=self.emp, date=timezone.localdate()).count(), 1)
        self.client.post(reverse("attendance:check_in"))  # duplicate -> no second record
        self.assertEqual(Attendance.objects.filter(employee=self.emp).count(), 1)

    @override_settings(SMARTHR={**SCHEDULE, "ENABLE_SELF_CHECKIN": False})
    def test_self_checkin_can_be_disabled(self):
        self.client.login(username=self.emp.user.username, password=PASSWORD)
        self.client.post(reverse("attendance:check_in"))
        self.assertEqual(Attendance.objects.count(), 0)
