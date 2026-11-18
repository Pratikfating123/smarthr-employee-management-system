from django import forms

from accounts.models import User
from core.forms import BootstrapFormMixin

from .models import Department, Designation


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.display_name


class DepartmentForm(BootstrapFormMixin, forms.ModelForm):
    head = UserChoiceField(queryset=User.objects.none(), required=False, label="Department head")

    class Meta:
        model = Department
        fields = ["name", "code", "description", "head", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["head"].queryset = User.objects.filter(is_active=True, employee__isnull=False).order_by("first_name", "username")

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and not cleaned.get("is_active", True):
            if self.instance.employees.filter(status="active").exists():
                self.add_error("is_active", "Move or deactivate this department's active employees first.")
        return cleaned


class DesignationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Designation
        fields = ["name"]
