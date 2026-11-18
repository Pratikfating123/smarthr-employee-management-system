from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Employee(models.Model):
    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        INTERN = "intern", "Intern"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        TERMINATED = "terminated", "Terminated"

    employee_id = models.CharField(max_length=20, unique=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="employee")
    phone = models.CharField(max_length=20, blank=True)
    photo = models.ImageField(upload_to="employee_photos/", blank=True)
    department = models.ForeignKey(
        "departments.Department", null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    designation = models.ForeignKey(
        "departments.Designation", null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    joining_date = models.DateField()
    employment_type = models.CharField(max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    reporting_manager = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_reports"
    )
    address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee_id"]

    def clean(self):
        if self.reporting_manager_id and self.pk and self.reporting_manager_id == self.pk:
            raise ValidationError({"reporting_manager": "An employee cannot report to themselves."})

    @property
    def full_name(self):
        return self.user.display_name

    @property
    def work_email(self):
        return self.user.email

    @property
    def is_active_employee(self):
        return self.status == self.Status.ACTIVE

    def __str__(self):
        return f"{self.employee_id} · {self.full_name}"


def next_employee_id():
    """Suggest the next EMP#### id (informational; the form field stays editable)."""
    last = Employee.objects.filter(employee_id__startswith="EMP").order_by("-employee_id").first()
    if last:
        digits = last.employee_id[3:]
        if digits.isdigit():
            return f"EMP{int(digits) + 1:04d}"
    return "EMP0001"
