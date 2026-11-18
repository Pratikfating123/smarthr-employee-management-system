from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"
        HALF_DAY = "half_day", "Half-day"
        ON_LEAVE = "on_leave", "On leave"
        HOLIDAY = "holiday", "Holiday"

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="attendance_records")
    date = models.DateField(db_index=True)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRESENT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "employee__employee_id"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="uniq_attendance_employee_date"),
            models.CheckConstraint(
                condition=Q(check_in__isnull=True) | Q(check_out__isnull=True) | Q(check_out__gt=F("check_in")),
                name="attendance_checkout_after_checkin",
            ),
        ]
        indexes = [models.Index(fields=["date", "status"])]

    def clean(self):
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValidationError({"check_out": "Check-out must be later than check-in. Overnight shifts are not supported."})

    @property
    def worked_duration(self):
        if self.check_in and self.check_out and self.check_out > self.check_in:
            return datetime.combine(self.date, self.check_out) - datetime.combine(self.date, self.check_in)
        return None

    @property
    def worked_hours(self):
        duration = self.worked_duration
        if duration is None:
            return None
        return (Decimal(duration.seconds) / Decimal(3600)).quantize(Decimal("0.01"))

    @property
    def worked_display(self):
        duration = self.worked_duration
        if duration is None:
            return "—"
        minutes = duration.seconds // 60
        return f"{minutes // 60}h {minutes % 60:02d}m"

    def __str__(self):
        return f"{self.employee.employee_id} {self.date} {self.status}"
