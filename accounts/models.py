from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        HR = "hr", "HR Manager"
        EMPLOYEE = "employee", "Employee"

    email = models.EmailField("work email", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    can_manage_payroll = models.BooleanField(
        default=False,
        help_text="Allows an HR Manager to manage salary structures and payroll. Admins always can.",
    )

    class Meta:
        ordering = ["username"]

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def is_hr_role(self):
        return self.role == self.Role.HR

    @property
    def is_hr_or_admin(self):
        return self.role in (self.Role.ADMIN, self.Role.HR)

    @property
    def is_payroll_manager(self):
        return self.is_admin_role or (self.is_hr_role and self.can_manage_payroll)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = (self.get_full_name() or self.username).split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def employee_profile(self):
        """The linked Employee or None (superusers may not have one)."""
        return getattr(self, "employee", None)

    def __str__(self):
        return self.display_name
