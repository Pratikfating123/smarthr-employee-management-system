from django import forms
from django.utils import timezone

from core.forms import BootstrapFormMixin, DateInput, TimeInput
from employees.models import Employee

from .models import Attendance


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return str(obj)


class AttendanceRecordForm(BootstrapFormMixin, forms.ModelForm):
    employee = EmployeeChoiceField(queryset=Employee.objects.none())

    class Meta:
        model = Attendance
        fields = ["employee", "date", "status", "check_in", "check_out", "notes"]
        widgets = {
            "date": DateInput(),
            "check_in": TimeInput(),
            "check_out": TimeInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.filter(status=Employee.Status.ACTIVE).select_related("user")

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise forms.ValidationError("Attendance cannot be recorded for a future date.")
        return value

    def clean(self):
        cleaned = super().clean()
        check_in, check_out = cleaned.get("check_in"), cleaned.get("check_out")
        if check_in and check_out and check_out <= check_in:
            self.add_error("check_out", "Check-out must be later than check-in.")
        return cleaned
