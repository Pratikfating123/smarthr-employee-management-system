from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from payroll import services
from payroll.models import Payroll

from .factories import PASSWORD, make_employee, make_structure


class CalculationTests(TestCase):
    def test_sample_formula(self):
        r = services.calculate("50000", "10000", "0", "12", "10", "500")
        self.assertEqual(r["gross_salary"], Decimal("60000.00"))
        self.assertEqual(r["pf_amount"], Decimal("6000.00"))
        self.assertEqual(r["tax_amount"], Decimal("6000.00"))
        self.assertEqual(r["total_deductions"], Decimal("12500.00"))
        self.assertEqual(r["net_salary"], Decimal("47500.00"))

    def test_rounding_half_up_and_decimal_types(self):
        r = services.calculate("1000.05", "0", "0", "12.5", "0", "0")
        self.assertEqual(r["pf_amount"], Decimal("125.01"))  # 125.00625 -> 125.01
        for value in r.values():
            self.assertIsInstance(value, Decimal)

    def test_no_float_drift(self):
        r = services.calculate("0.10", "0.20", "0", "0", "0", "0")
        self.assertEqual(r["gross_salary"], Decimal("0.30"))

    def test_deductions_over_gross_rejected(self):
        with self.assertRaises(ValueError):
            services.calculate("100", "0", "0", "0", "0", "500")


class PayrollWorkflowTests(TestCase):
    def setUp(self):
        self.admin = make_employee(role=User.Role.ADMIN)
        self.hr_no = make_employee(role=User.Role.HR)
        self.emp = make_employee(joining_date=date(2025, 1, 1))
        make_structure(self.emp)

    def test_generate_snapshots_and_net(self):
        result = services.generate_payroll(2026, 1, self.admin.user, self.emp)
        self.assertEqual(result["created"], 1)
        payroll = Payroll.objects.get(employee=self.emp)
        self.assertEqual(payroll.net_salary, Decimal("47500.00"))
        self.assertEqual(payroll.generated_by, self.admin.user)
        self.assertEqual(payroll.status, Payroll.Status.GENERATED)

    def test_salary_change_does_not_rewrite_history(self):
        services.generate_payroll(2026, 1, self.admin.user, self.emp)
        structure = self.emp.salary_structures.get()
        structure.basic_salary = Decimal("99999.00")
        structure.save()
        self.assertEqual(Payroll.objects.get(employee=self.emp).basic_salary, Decimal("50000.00"))

    def test_second_run_is_idempotent(self):
        services.generate_payroll(2026, 1, self.admin.user)
        again = services.generate_payroll(2026, 1, self.admin.user)
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["existing"], 1)
        self.assertEqual(Payroll.objects.filter(employee=self.emp).count(), 1)

    def test_database_blocks_duplicate_period(self):
        services.generate_payroll(2026, 1, self.admin.user, self.emp)
        existing = Payroll.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payroll.objects.create(
                employee=self.emp, year=2026, month=1,
                **{k: Decimal("1.00") for k in ("basic_salary", "allowances", "other_earnings", "gross_salary", "pf_amount", "tax_amount", "other_deductions", "total_deductions", "net_salary")},
            )
        self.assertEqual(Payroll.objects.count(), 1)
        self.assertEqual(existing.pk, Payroll.objects.get().pk)

    def test_employee_without_structure_skipped(self):
        no_structure = make_employee(joining_date=date(2025, 1, 1))
        result = services.generate_payroll(2026, 1, self.admin.user)
        self.assertEqual(result["created"], 1)  # only self.emp has a structure
        self.assertGreaterEqual(result["no_structure"], 1)
        self.assertFalse(Payroll.objects.filter(employee=no_structure).exists())

    def test_structure_effective_date_respected(self):
        late = make_employee(joining_date=date(2025, 1, 1))
        make_structure(late, effective=date(2026, 6, 1))
        result = services.generate_payroll(2026, 1, self.admin.user, late)
        self.assertEqual(result["no_structure"], 1)

    def test_not_yet_joined_excluded(self):
        new = make_employee(joining_date=date(2026, 5, 1))
        make_structure(new)
        services.generate_payroll(2026, 1, self.admin.user)
        self.assertFalse(Payroll.objects.filter(employee=new).exists())

    def test_hr_without_flag_cannot_generate_or_approve(self):
        with self.assertRaises(PermissionDenied):
            services.generate_payroll(2026, 1, self.hr_no.user)
        services.generate_payroll(2026, 1, self.admin.user, self.emp)
        with self.assertRaises(PermissionDenied):
            services.approve_payroll(Payroll.objects.get().pk, self.hr_no.user)

    def test_approve_then_pay(self):
        services.generate_payroll(2026, 1, self.admin.user, self.emp)
        payroll = Payroll.objects.get()
        with self.assertRaises(ValidationError):
            services.set_payment_status(payroll.pk, self.admin.user, "paid")  # must approve first
        services.approve_payroll(payroll.pk, self.admin.user)
        with self.assertRaises(ValidationError):
            services.approve_payroll(payroll.pk, self.admin.user)  # not twice
        services.set_payment_status(payroll.pk, self.admin.user, "paid")
        payroll.refresh_from_db()
        self.assertEqual(payroll.payment_status, "paid")
        self.assertIsNotNone(payroll.paid_date)
        self.assertEqual(payroll.approved_by, self.admin.user)
        self.assertEqual(self.emp.user.notifications.count(), 2)

    def test_invalid_payment_status_rejected(self):
        services.generate_payroll(2026, 1, self.admin.user, self.emp)
        payroll = Payroll.objects.get()
        services.approve_payroll(payroll.pk, self.admin.user)
        with self.assertRaises(ValidationError):
            services.set_payment_status(payroll.pk, self.admin.user, "bogus")


class PayslipViewTests(TestCase):
    def setUp(self):
        self.admin = make_employee(role=User.Role.ADMIN)
        self.emp = make_employee(joining_date=date(2025, 1, 1))
        self.other = make_employee(joining_date=date(2025, 1, 1))
        make_structure(self.emp)
        make_structure(self.other)
        services.generate_payroll(2026, 1, self.admin.user)
        self.mine = Payroll.objects.get(employee=self.emp)
        self.theirs = Payroll.objects.get(employee=self.other)

    def test_employee_list_shows_only_own_approved(self):
        services.approve_payroll(self.mine.pk, self.admin.user)
        services.approve_payroll(self.theirs.pk, self.admin.user)
        self.client.login(username=self.emp.user.username, password=PASSWORD)
        resp = self.client.get(reverse("payroll:list"))
        self.assertEqual([p.pk for p in resp.context["page_obj"]], [self.mine.pk])
        self.assertEqual(self.client.get(reverse("payroll:detail", args=[self.theirs.pk])).status_code, 404)

    def test_employee_cannot_use_payroll_actions(self):
        self.client.login(username=self.emp.user.username, password=PASSWORD)
        self.assertEqual(self.client.post(reverse("payroll:approve", args=[self.mine.pk])).status_code, 403)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Payroll.Status.GENERATED)

    def test_admin_generate_via_view(self):
        Payroll.objects.all().delete()
        self.client.login(username=self.admin.user.username, password=PASSWORD)
        resp = self.client.post(reverse("payroll:create"), {"year": 2026, "month": 1, "employee": ""})
        self.assertRedirects(resp, reverse("payroll:list"))
        self.assertEqual(Payroll.objects.count(), 2)

    def test_future_month_rejected(self):
        Payroll.objects.all().delete()
        self.client.login(username=self.admin.user.username, password=PASSWORD)
        self.client.post(reverse("payroll:create"), {"year": 2999, "month": 1, "employee": ""})
        self.assertEqual(Payroll.objects.count(), 0)
