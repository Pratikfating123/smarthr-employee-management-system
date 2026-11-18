from django import forms
from django.utils import timezone

from core.forms import BootstrapFormMixin, DateInput

from . import services
from .models import LeaveRequest, LeaveType


class LeaveRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, employee, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        self.fields["leave_type"].queryset = LeaveType.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        leave_type = cleaned.get("leave_type")
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if not (leave_type and start and end):
            return cleaned
        if end < start:
            self.add_error("end_date", "End date cannot be before the start date.")
            return cleaned
        if start < timezone.localdate():
            self.add_error("start_date", "Leave cannot start in the past.")
        if start.year != end.year:
            self.add_error("end_date", "Split requests that span two calendar years.")
            return cleaned
        overlap = LeaveRequest.objects.filter(
            employee=self.employee,
            status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
            start_date__lte=end,
            end_date__gte=start,
        )
        if overlap.exists():
            raise forms.ValidationError("This overlaps with an existing pending or approved leave request.")
        days = services.working_days(start, end)
        if days <= 0:
            raise forms.ValidationError("The selected dates contain no working days.")
        remaining = services.remaining_preview(self.employee, leave_type, start.year)
        if days > remaining:
            raise forms.ValidationError(f"Insufficient {leave_type.name} balance: {remaining} day(s) remaining, {days} requested.")
        return cleaned

    def save(self, commit=True):
        cleaned = self.cleaned_data
        return services.submit_request(
            self.employee, cleaned["leave_type"], cleaned["start_date"], cleaned["end_date"], cleaned["reason"]
        )
