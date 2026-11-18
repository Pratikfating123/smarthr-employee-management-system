"""Leave workflow rules. Weekends come from settings.SMARTHR['WORKING_WEEKDAYS']; public holidays from core.Holiday.
Simplification: whole days only, and a request must stay inside one calendar year."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit import log_action
from core.models import Holiday
from notifications.services import notify, notify_hr

from .models import LeaveBalance, LeaveRequest, LeaveType


def working_days(start, end):
    """Number of configured working days between start and end inclusive, excluding holidays."""
    holidays = set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))
    weekdays = set(settings.SMARTHR["WORKING_WEEKDAYS"])
    count, day = 0, start
    while day <= end:
        if day.weekday() in weekdays and day not in holidays:
            count += 1
        day += timedelta(days=1)
    return Decimal(count)


def remaining_preview(employee, leave_type, year):
    """Read-only remaining balance (falls back to the default allowance if no row exists yet)."""
    row = LeaveBalance.objects.filter(employee=employee, leave_type=leave_type, year=year).first()
    return row.remaining if row else leave_type.default_allowance


def balance_summary(employee, year):
    """List of dicts for display; does not write to the database."""
    rows = {b.leave_type_id: b for b in LeaveBalance.objects.filter(employee=employee, year=year)}
    summary = []
    for leave_type in LeaveType.objects.filter(is_active=True):
        row = rows.get(leave_type.pk)
        allocated = row.allocated if row else leave_type.default_allowance
        used = row.used if row else Decimal("0")
        summary.append({"leave_type": leave_type, "allocated": allocated, "used": used, "remaining": allocated - used})
    return summary


def _locked_balance(employee, leave_type, year):
    balance, _ = LeaveBalance.objects.get_or_create(
        employee=employee, leave_type=leave_type, year=year, defaults={"allocated": leave_type.default_allowance}
    )
    return LeaveBalance.objects.select_for_update().get(pk=balance.pk)


def submit_request(employee, leave_type, start_date, end_date, reason):
    days = working_days(start_date, end_date)
    leave = LeaveRequest.objects.create(
        employee=employee, leave_type=leave_type, start_date=start_date, end_date=end_date, reason=reason, days=days
    )
    notify_hr(f"{employee.full_name} requested {days} day(s) of {leave_type.name}.", f"/leaves/{leave.pk}/")
    return leave


def _require_reviewer(reviewer, leave):
    if not reviewer.is_hr_or_admin:
        raise PermissionDenied
    if leave.employee.user_id == reviewer.pk:
        raise ValidationError("You cannot review your own leave request.")


@transaction.atomic
def approve_request(leave_id, reviewer, comments=""):
    leave = LeaveRequest.objects.select_for_update().select_related("employee__user", "leave_type").get(pk=leave_id)
    _require_reviewer(reviewer, leave)
    if leave.status != LeaveRequest.Status.PENDING:
        raise ValidationError("Only pending requests can be approved.")
    if leave.balance_deducted:  # defensive: never deduct twice
        raise ValidationError("Leave has already been deducted for this request.")
    balance = _locked_balance(leave.employee, leave.leave_type, leave.start_date.year)
    if balance.remaining < leave.days:
        raise ValidationError(f"Insufficient balance: {balance.remaining} day(s) remaining, {leave.days} requested.")
    balance.used += leave.days
    balance.save(update_fields=["used"])
    leave.status = LeaveRequest.Status.APPROVED
    leave.reviewer = reviewer
    leave.reviewed_at = timezone.now()
    leave.review_comments = comments
    leave.balance_deducted = True
    leave.save()
    log_action(reviewer, "leave_approved", leave, f"{leave.employee.employee_id} {leave.days}d")
    notify(leave.employee.user, f"Your {leave.leave_type.name} request was approved.", f"/leaves/{leave.pk}/")
    return leave


@transaction.atomic
def reject_request(leave_id, reviewer, comments=""):
    leave = LeaveRequest.objects.select_for_update().select_related("employee__user", "leave_type").get(pk=leave_id)
    _require_reviewer(reviewer, leave)
    if leave.status != LeaveRequest.Status.PENDING:
        raise ValidationError("Only pending requests can be rejected.")
    leave.status = LeaveRequest.Status.REJECTED
    leave.reviewer = reviewer
    leave.reviewed_at = timezone.now()
    leave.review_comments = comments
    leave.save()
    log_action(reviewer, "leave_rejected", leave, leave.employee.employee_id)
    notify(leave.employee.user, f"Your {leave.leave_type.name} request was rejected.", f"/leaves/{leave.pk}/")
    return leave


@transaction.atomic
def cancel_request(leave_id, user):
    """Owner may cancel pending requests, or approved ones that have not started. HR/admin may cancel either."""
    leave = LeaveRequest.objects.select_for_update().select_related("employee__user", "leave_type").get(pk=leave_id)
    is_owner = leave.employee.user_id == user.pk
    if not (is_owner or user.is_hr_or_admin):
        raise PermissionDenied
    if leave.status not in (LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED):
        raise ValidationError("This request can no longer be cancelled.")
    if (
        leave.status == LeaveRequest.Status.APPROVED
        and not user.is_hr_or_admin
        and leave.start_date <= timezone.localdate()
    ):
        raise ValidationError("Approved leave that has already started can only be cancelled by HR.")
    if leave.balance_deducted:
        balance = _locked_balance(leave.employee, leave.leave_type, leave.start_date.year)
        balance.used = max(Decimal("0"), balance.used - leave.days)
        balance.save(update_fields=["used"])
        leave.balance_deducted = False
    leave.status = LeaveRequest.Status.CANCELLED
    leave.save()
    log_action(user, "leave_cancelled", leave, leave.employee.employee_id)
    if not is_owner:
        notify(leave.employee.user, f"Your {leave.leave_type.name} request was cancelled by HR.", f"/leaves/{leave.pk}/")
    return leave
