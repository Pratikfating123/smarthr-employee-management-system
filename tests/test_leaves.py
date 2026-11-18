from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import Holiday
from leaves import services
from leaves.models import LeaveBalance, LeaveRequest

from .factories import PASSWORD, make_employee, make_leave_type


def next_weekday(weekday, weeks_ahead=1):
    today = timezone.localdate()
    return today + timedelta(days=(weekday - today.weekday()) % 7 + 7 * weeks_ahead)


class WorkingDayTests(TestCase):
    def test_weekend_excluded(self):
        monday = next_weekday(0)
        self.assertEqual(services.working_days(monday, monday + timedelta(days=6)), Decimal(5))

    def test_holiday_excluded(self):
        monday = next_weekday(0)
        Holiday.objects.create(date=monday + timedelta(days=1), name="Test")
        self.assertEqual(services.working_days(monday, monday + timedelta(days=4)), Decimal(4))


class LeaveWorkflowTests(TestCase):
    def setUp(self):
        self.hr = make_employee(role=User.Role.HR)
        self.emp = make_employee()
        self.lt = make_leave_type(allowance="5")
        self.monday = next_weekday(0)
        if self.monday.year != (self.monday + timedelta(days=20)).year:
            self.skipTest("Test window crosses a year boundary; rerun in another week.")

    def submit(self, start_offset=0, length=2, employee=None):
        start = self.monday + timedelta(days=start_offset)
        return services.submit_request(employee or self.emp, self.lt, start, start + timedelta(days=length - 1), "reason")

    def balance(self):
        return LeaveBalance.objects.get(employee=self.emp, leave_type=self.lt, year=self.monday.year)

    def test_submit_calculates_days_and_notifies_hr(self):
        leave = self.submit(length=3)
        self.assertEqual(leave.days, Decimal(3))
        self.assertEqual(leave.status, LeaveRequest.Status.PENDING)
        self.assertTrue(self.hr.user.notifications.exists())

    def test_approve_deducts_once_and_records_reviewer(self):
        leave = self.submit(length=2)
        services.approve_request(leave.pk, self.hr.user, "ok")
        leave.refresh_from_db()
        self.assertEqual(leave.status, LeaveRequest.Status.APPROVED)
        self.assertEqual(leave.reviewer, self.hr.user)
        self.assertIsNotNone(leave.reviewed_at)
        self.assertEqual(self.balance().used, Decimal(2))
        self.assertEqual(self.balance().remaining, Decimal(3))
        self.assertTrue(self.emp.user.notifications.exists())

    def test_double_approval_does_not_double_deduct(self):
        leave = self.submit(length=2)
        services.approve_request(leave.pk, self.hr.user)
        with self.assertRaises(ValidationError):
            services.approve_request(leave.pk, self.hr.user)
        self.assertEqual(self.balance().used, Decimal(2))

    def test_insufficient_balance_blocks_approval(self):
        leave = self.submit(length=5)
        other = self.submit(start_offset=7, length=3)  # total 8 > 5
        services.approve_request(leave.pk, self.hr.user)
        with self.assertRaises(ValidationError):
            services.approve_request(other.pk, self.hr.user)
        other.refresh_from_db()
        self.assertEqual(other.status, LeaveRequest.Status.PENDING)
        self.assertEqual(self.balance().used, Decimal(5))

    def test_reject_leaves_balance_untouched(self):
        leave = self.submit()
        services.reject_request(leave.pk, self.hr.user, "no")
        leave.refresh_from_db()
        self.assertEqual(leave.status, LeaveRequest.Status.REJECTED)
        self.assertFalse(LeaveBalance.objects.filter(employee=self.emp, used__gt=0).exists())
        with self.assertRaises(ValidationError):
            services.approve_request(leave.pk, self.hr.user)

    def test_employee_cannot_review(self):
        leave = self.submit()
        with self.assertRaises(PermissionDenied):
            services.approve_request(leave.pk, self.emp.user)

    def test_cannot_review_own_request(self):
        leave = self.submit(employee=self.hr)
        with self.assertRaises(ValidationError):
            services.approve_request(leave.pk, self.hr.user)

    def test_cancel_approved_restores_balance(self):
        leave = self.submit(length=2)
        services.approve_request(leave.pk, self.hr.user)
        services.cancel_request(leave.pk, self.emp.user)
        leave.refresh_from_db()
        self.assertEqual(leave.status, LeaveRequest.Status.CANCELLED)
        self.assertFalse(leave.balance_deducted)
        self.assertEqual(self.balance().used, Decimal(0))
        with self.assertRaises(ValidationError):
            services.cancel_request(leave.pk, self.emp.user)  # no double restore
        self.assertEqual(self.balance().used, Decimal(0))

    def test_cancel_pending_no_balance_change(self):
        leave = self.submit()
        services.cancel_request(leave.pk, self.emp.user)
        self.assertFalse(LeaveBalance.objects.filter(used__gt=0).exists())

    def test_other_employee_cannot_cancel(self):
        leave = self.submit()
        with self.assertRaises(PermissionDenied):
            services.cancel_request(leave.pk, make_employee().user)


class LeaveFormViewTests(TestCase):
    def setUp(self):
        self.hr = make_employee(role=User.Role.HR)
        self.emp = make_employee()
        self.lt = make_leave_type(allowance="3")
        self.monday = next_weekday(0)
        self.client.login(username=self.emp.user.username, password=PASSWORD)

    def apply(self, start, end, lt=None):
        return self.client.post(reverse("leaves:apply"), {"leave_type": (lt or self.lt).pk, "start_date": start.isoformat(), "end_date": end.isoformat(), "reason": "trip"})

    def test_valid_application(self):
        if self.monday.year != (self.monday + timedelta(days=1)).year:
            self.skipTest("year boundary")
        resp = self.apply(self.monday, self.monday + timedelta(days=1))
        leave = LeaveRequest.objects.get()
        self.assertRedirects(resp, reverse("leaves:detail", args=[leave.pk]))

    def test_end_before_start_rejected(self):
        resp = self.apply(self.monday + timedelta(days=2), self.monday)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(LeaveRequest.objects.exists())

    def test_past_start_rejected(self):
        past = timezone.localdate() - timedelta(days=3)
        self.apply(past, past)
        self.assertFalse(LeaveRequest.objects.exists())

    def test_overlap_rejected(self):
        if self.monday.year != (self.monday + timedelta(days=2)).year:
            self.skipTest("year boundary")
        self.apply(self.monday, self.monday + timedelta(days=1))
        self.apply(self.monday + timedelta(days=1), self.monday + timedelta(days=2))
        self.assertEqual(LeaveRequest.objects.count(), 1)

    def test_weekend_only_rejected(self):
        saturday = next_weekday(5)
        self.apply(saturday, saturday + timedelta(days=1))
        self.assertFalse(LeaveRequest.objects.exists())

    def test_over_balance_rejected(self):
        if self.monday.year != (self.monday + timedelta(days=4)).year:
            self.skipTest("year boundary")
        self.apply(self.monday, self.monday + timedelta(days=4))  # 5 days > 3
        self.assertFalse(LeaveRequest.objects.exists())

    def test_hr_approves_through_view(self):
        if self.monday.year != (self.monday + timedelta(days=1)).year:
            self.skipTest("year boundary")
        self.apply(self.monday, self.monday + timedelta(days=1))
        leave = LeaveRequest.objects.get()
        self.client.login(username=self.hr.user.username, password=PASSWORD)
        self.client.post(reverse("leaves:approve", args=[leave.pk]), {"comments": "fine"})
        leave.refresh_from_db()
        self.assertEqual(leave.status, LeaveRequest.Status.APPROVED)
        self.assertEqual(LeaveBalance.objects.get(employee=self.emp).used, Decimal(2))

    def test_approve_next_param_cannot_redirect_offsite(self):
        if self.monday.year != (self.monday + timedelta(days=1)).year:
            self.skipTest("year boundary")
        self.apply(self.monday, self.monday)
        leave = LeaveRequest.objects.get()
        self.client.login(username=self.hr.user.username, password=PASSWORD)
        resp = self.client.post(reverse("leaves:approve", args=[leave.pk]), {"next": "https://evil.example/"})
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("evil.example", resp.url)
