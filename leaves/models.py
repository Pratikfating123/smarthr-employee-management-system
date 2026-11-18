from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class LeaveType(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True)
    default_allowance = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))],
        help_text="Default annual allowance in working days.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeaveBalance(models.Model):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="leave_balances")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="balances")
    year = models.PositiveSmallIntegerField()
    allocated = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))
    used = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "leave_type", "year"], name="uniq_leave_balance"),
            models.CheckConstraint(condition=Q(used__gte=0), name="leave_balance_used_non_negative"),
        ]
        ordering = ["year", "leave_type__name"]

    @property
    def remaining(self):
        return self.allocated - self.used

    def __str__(self):
        return f"{self.employee.employee_id} {self.leave_type} {self.year}"


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_leaves"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comments = models.TextField(blank=True)
    balance_deducted = models.BooleanField(default=False, help_text="Guards against duplicate balance deductions.")

    class Meta:
        ordering = ["-submitted_at", "-id"]
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="leave_end_after_start")]

    @property
    def year(self):
        return self.start_date.year

    def __str__(self):
        return f"{self.employee.employee_id} {self.leave_type} {self.start_date}→{self.end_date}"
