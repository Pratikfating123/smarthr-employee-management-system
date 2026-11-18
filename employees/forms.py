import secrets

from django import forms
from django.db import transaction
from django.db.models import Q

from accounts.models import User
from core.forms import BootstrapFormMixin, DateInput

from .models import Employee, next_employee_id

ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PHOTO_BYTES = 2 * 1024 * 1024


class EmployeeForm(BootstrapFormMixin, forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    work_email = forms.EmailField()
    role = forms.ChoiceField(choices=User.Role.choices, required=False)
    can_manage_payroll = forms.BooleanField(required=False, label="Can manage payroll (HR only)")

    field_order = [
        "employee_id", "first_name", "last_name", "work_email", "phone", "department", "designation",
        "joining_date", "employment_type", "status", "reporting_manager", "role", "can_manage_payroll",
        "photo", "address", "emergency_contact_name", "emergency_contact_phone",
    ]

    class Meta:
        model = Employee
        fields = [
            "employee_id", "phone", "photo", "department", "designation", "joining_date", "employment_type",
            "status", "reporting_manager", "address", "emergency_contact_name", "emergency_contact_phone",
        ]
        widgets = {"joining_date": DateInput(), "address": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.temp_password = None
        if self.instance.pk:
            user = self.instance.user
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["work_email"].initial = user.email
            self.fields["role"].initial = user.role
            self.fields["can_manage_payroll"].initial = user.can_manage_payroll
        else:
            self.fields["employee_id"].initial = next_employee_id()
            self.fields["role"].initial = User.Role.EMPLOYEE
        if not actor.is_admin_role:
            # Only admins may change roles or payroll permission.
            del self.fields["role"]
            del self.fields["can_manage_payroll"]
        from departments.models import Department, Designation

        dept_q = Q(is_active=True)
        desig_q = Q(is_active=True)
        if self.instance.pk:
            dept_q |= Q(pk=self.instance.department_id)
            desig_q |= Q(pk=self.instance.designation_id)
        self.fields["department"].queryset = Department.objects.filter(dept_q)
        self.fields["designation"].queryset = Designation.objects.filter(desig_q)
        managers = Employee.objects.filter(status=Employee.Status.ACTIVE)
        if self.instance.pk:
            managers = managers.exclude(pk=self.instance.pk)
        self.fields["reporting_manager"].queryset = managers.select_related("user")
        self.fields["department"].required = True
        self.fields["designation"].required = True

    def clean_employee_id(self):
        value = self.cleaned_data["employee_id"].strip().upper()
        if not self.instance.pk and User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("A user with this login name already exists.")
        return value

    def clean_work_email(self):
        email = self.cleaned_data["work_email"].strip().lower()
        clash = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.user_id)
        if clash.exists():
            raise forms.ValidationError("This work email is already in use.")
        return email

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "content_type"):
            if photo.content_type not in ALLOWED_PHOTO_TYPES:
                raise forms.ValidationError("Upload a JPEG, PNG or WebP image.")
            if photo.size > MAX_PHOTO_BYTES:
                raise forms.ValidationError("Photo must be 2 MB or smaller.")
        return photo

    @transaction.atomic
    def save(self, commit=True):
        employee = super().save(commit=False)
        data = self.cleaned_data
        if employee.pk:
            user = employee.user
        else:
            user = User(username=data["employee_id"].lower())
            self.temp_password = secrets.token_urlsafe(10)
            user.set_password(self.temp_password)
        user.first_name = data["first_name"]
        user.last_name = data["last_name"]
        user.email = data["work_email"]
        if "role" in self.fields and data.get("role") and not user.is_superuser:
            user.role = data["role"]
            user.can_manage_payroll = bool(data.get("can_manage_payroll")) and user.role == User.Role.HR
        user.is_active = employee.status == Employee.Status.ACTIVE
        user.save()
        employee.user = user
        employee.save()
        self.save_m2m()
        return employee
