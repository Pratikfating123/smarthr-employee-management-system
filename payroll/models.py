from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

MONEY = {"max_digits": 12, "decimal_places": 2}
ZERO = Decimal("0.00")


class SalaryStructure(models.Model):
    """Sample formula (see README): gross = basic + allowances + other earnings;
    PF = pf_percent of basic; tax = tax_percent of gross (flat sample rate); plus fixed other deductions."""

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="salary_structures")
    basic_salary = models.DecimalField(validators=[MinValueValidator(ZERO)], **MONEY)
    allowances = models.DecimalField(default=ZERO, validators=[MinValueValidator(ZERO)], **MONEY)
    other_earnings = models.DecimalField(default=ZERO, validators=[MinValueValidator(ZERO)], **MONEY)
    pf_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal("100"))],
        verbose_name="Provident-fund % of basic (sample)",
    )
    tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal("100"))],
        verbose_name="Flat tax % of gross (sample)",
    )
    other_deductions = models.DecimalField(default=ZERO, validators=[MinValueValidator(ZERO)], **MONEY)
    effective_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__employee_id", "-effective_date"]

    def __str__(self):
        return f"{self.employee.employee_id} from {self.effective_date}"


class Payroll(models.Model):
    class Status(models.TextChoices):
        GENERATED = "generated", "Generated"
        APPROVED = "approved", "Approved"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        ON_HOLD = "on_hold", "On hold"

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="payrolls")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    # Snapshots: later salary-structure changes never rewrite history.
    basic_salary = models.DecimalField(**MONEY)
    allowances = models.DecimalField(**MONEY)
    other_earnings = models.DecimalField(**MONEY)
    gross_salary = models.DecimalField(**MONEY)
    pf_amount = models.DecimalField(**MONEY)
    tax_amount = models.DecimalField(**MONEY)
    other_deductions = models.DecimalField(**MONEY)
    total_deductions = models.DecimalField(**MONEY)
    net_salary = models.DecimalField(**MONEY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATED, db_index=True)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="payrolls_generated"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="payrolls_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "-month", "employee__employee_id"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "year", "month"], name="uniq_payroll_employee_period"),
            models.CheckConstraint(condition=Q(month__gte=1) & Q(month__lte=12), name="payroll_month_valid"),
        ]

    @property
    def period_label(self):
        import calendar

        return f"{calendar.month_name[self.month]} {self.year}"

    def __str__(self):
        return f"{self.employee.employee_id} {self.year}-{self.month:02d}"
