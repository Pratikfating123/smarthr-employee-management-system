import calendar

from django import forms
from django.utils import timezone

from core.forms import BootstrapFormMixin, DateInput
from employees.models import Employee

from .models import SalaryStructure
from .services import calculate


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return str(obj)


class SalaryStructureForm(BootstrapFormMixin, forms.ModelForm):
    employee = EmployeeChoiceField(queryset=Employee.objects.none())

    class Meta:
        model = SalaryStructure
        fields = [
            "employee", "basic_salary", "allowances", "other_earnings", "pf_percent", "tax_percent",
            "other_deductions", "effective_date", "is_active",
        ]
        widgets = {"effective_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.filter(status=Employee.Status.ACTIVE).select_related("user")
        if self.instance.pk:
            self.fields["employee"].disabled = True

    def clean(self):
        cleaned = super().clean()
        try:
            if all(k in cleaned for k in ("basic_salary", "allowances", "other_earnings", "pf_percent", "tax_percent", "other_deductions")):
                calculate(
                    cleaned["basic_salary"], cleaned["allowances"], cleaned["other_earnings"],
                    cleaned["pf_percent"], cleaned["tax_percent"], cleaned["other_deductions"],
                )
        except ValueError:
            raise forms.ValidationError("Total deductions would exceed gross salary.")
        return cleaned


class PayrollGenerateForm(BootstrapFormMixin, forms.Form):
    year = forms.IntegerField(min_value=2000, max_value=2100)
    month = forms.TypedChoiceField(
        choices=[(i, calendar.month_name[i]) for i in range(1, 13)], coerce=int
    )
    employee = EmployeeChoiceField(
        queryset=Employee.objects.none(), required=False, empty_label="All active employees with a salary structure"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["year"].initial = today.year
        self.fields["month"].initial = today.month
        self.fields["employee"].queryset = Employee.objects.filter(status=Employee.Status.ACTIVE).select_related("user")

    def clean(self):
        cleaned = super().clean()
        year, month = cleaned.get("year"), cleaned.get("month")
        if year and month:
            today = timezone.localdate()
            if (year, month) > (today.year, today.month):
                raise forms.ValidationError("Payroll cannot be generated for a future month.")
        return cleaned
