"""Payroll calculation and workflow. All money uses Decimal; amounts are rounded half-up to 2 places.

This is a documented SAMPLE formula, not statutory compliance: no jurisdiction-specific tax slabs,
provident fund ceilings, insurance or loss-of-pay rules are implemented."""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit import log_action
from employees.models import Employee
from notifications.services import notify

from .models import Payroll, SalaryStructure

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def calculate(basic, allowances, other_earnings, pf_percent, tax_percent, other_deductions):
    basic, allowances = Decimal(basic), Decimal(allowances)
    other_earnings, other_deductions = Decimal(other_earnings), Decimal(other_deductions)
    gross = money(basic + allowances + other_earnings)
    pf = money(basic * Decimal(pf_percent) / HUNDRED)
    tax = money(gross * Decimal(tax_percent) / HUNDRED)
    other = money(other_deductions)
    total = pf + tax + other
    net = gross - total
    if net < 0:
        raise ValueError("Deductions exceed gross salary.")
    return {
        "basic_salary": money(basic),
        "allowances": money(allowances),
        "other_earnings": money(other_earnings),
        "gross_salary": gross,
        "pf_amount": pf,
        "tax_amount": tax,
        "other_deductions": other,
        "total_deductions": total,
        "net_salary": net,
    }


def structure_for(employee, year, month):
    period_end = date(year, month, calendar.monthrange(year, month)[1])
    return (
        SalaryStructure.objects.filter(employee=employee, is_active=True, effective_date__lte=period_end)
        .order_by("-effective_date", "-id")
        .first()
    )


def generate_payroll(year, month, actor, employee=None):
    """Create payroll rows for one employee or all eligible active employees.
    Returns dict(created=n, existing=n, no_structure=n, invalid=n). Existing periods are never overwritten."""
    if not actor.is_payroll_manager:
        raise PermissionDenied
    period_end = date(year, month, calendar.monthrange(year, month)[1])
    employees = Employee.objects.filter(status=Employee.Status.ACTIVE, joining_date__lte=period_end).select_related("user")
    if employee is not None:
        employees = employees.filter(pk=employee.pk)
    result = {"created": 0, "existing": 0, "no_structure": 0, "invalid": 0}
    for emp in employees:
        structure = structure_for(emp, year, month)
        if structure is None:
            result["no_structure"] += 1
            continue
        try:
            figures = calculate(
                structure.basic_salary, structure.allowances, structure.other_earnings,
                structure.pf_percent, structure.tax_percent, structure.other_deductions,
            )
        except ValueError:
            result["invalid"] += 1
            continue
        with transaction.atomic():
            payroll, created = Payroll.objects.get_or_create(
                employee=emp, year=year, month=month, defaults={**figures, "generated_by": actor}
            )
        if created:
            result["created"] += 1
            log_action(actor, "payroll_generated", payroll, f"{emp.employee_id} {year}-{month:02d}")
        else:
            result["existing"] += 1
    return result


@transaction.atomic
def approve_payroll(payroll_id, actor):
    if not actor.is_payroll_manager:
        raise PermissionDenied
    payroll = Payroll.objects.select_for_update().select_related("employee__user").get(pk=payroll_id)
    if payroll.status != Payroll.Status.GENERATED:
        raise ValidationError("Only generated payroll can be approved.")
    payroll.status = Payroll.Status.APPROVED
    payroll.approved_by = actor
    payroll.approved_at = timezone.now()
    payroll.save()
    log_action(actor, "payroll_approved", payroll, f"{payroll.employee.employee_id} {payroll.period_label}")
    notify(payroll.employee.user, f"Your payslip for {payroll.period_label} is available.", f"/payroll/{payroll.pk}/")
    return payroll


@transaction.atomic
def set_payment_status(payroll_id, actor, new_status):
    if not actor.is_payroll_manager:
        raise PermissionDenied
    if new_status not in Payroll.PaymentStatus.values:
        raise ValidationError("Invalid payment status.")
    payroll = Payroll.objects.select_for_update().select_related("employee__user").get(pk=payroll_id)
    if payroll.status != Payroll.Status.APPROVED:
        raise ValidationError("Approve the payroll before changing its payment status.")
    old = payroll.payment_status
    payroll.payment_status = new_status
    payroll.paid_date = timezone.localdate() if new_status == Payroll.PaymentStatus.PAID else None
    payroll.save()
    log_action(actor, "payment_status_changed", payroll, f"{payroll.employee.employee_id} {old} -> {new_status}")
    if new_status == Payroll.PaymentStatus.PAID:
        notify(payroll.employee.user, f"Salary for {payroll.period_label} has been marked as paid.", f"/payroll/{payroll.pk}/")
    return payroll
