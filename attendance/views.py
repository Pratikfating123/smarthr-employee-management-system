import calendar

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.permissions import hr_required
from core.utils import month_bounds, paginate, parse_date, parse_int, safe_redirect
from departments.models import Department
from employees.models import Employee
from notifications.services import notify

from . import services
from .forms import AttendanceRecordForm
from .models import Attendance


@login_required
def attendance_list(request):
    user = request.user
    today = timezone.localdate()
    records = Attendance.objects.select_related("employee__user", "employee__department")
    if user.is_hr_or_admin:
        default_from = default_to = today
        q = request.GET.get("q", "").strip()
        if q:
            records = records.filter(
                Q(employee__employee_id__icontains=q)
                | Q(employee__user__first_name__icontains=q)
                | Q(employee__user__last_name__icontains=q)
            )
        department = request.GET.get("department", "")
        if department.isdigit():
            records = records.filter(employee__department_id=int(department))
    else:
        employee = user.employee_profile
        if employee is None:
            raise PermissionDenied
        records = records.filter(employee=employee)  # employees only ever see their own records
        default_from, default_to = month_bounds(today.year, today.month)[0], today
        q = department = ""
    date_from = parse_date(request.GET.get("date_from"), default_from)
    date_to = parse_date(request.GET.get("date_to"), default_to)
    records = records.filter(date__gte=date_from, date__lte=date_to)
    status = request.GET.get("status", "")
    if status in Attendance.Status.values:
        records = records.filter(status=status)
    page_obj, querystring = paginate(request, records, per_page=25)
    return render(
        request,
        "attendance/list.html",
        {
            "page_obj": page_obj,
            "querystring": querystring,
            "departments": Department.objects.all(),
            "statuses": Attendance.Status.choices,
            "filters": {"q": q, "department": department, "status": status, "date_from": date_from, "date_to": date_to},
        },
    )


@hr_required
def attendance_record(request):
    """Create a record or correct the existing one for the chosen employee and date."""
    existing = None
    if request.method == "POST":
        emp_id = parse_int(request.POST.get("employee"))
        day = parse_date(request.POST.get("date"))
        if emp_id and day:
            existing = Attendance.objects.filter(employee_id=emp_id, date=day).first()
        form = AttendanceRecordForm(request.POST, instance=existing)
        if form.is_valid():
            record = form.save()
            action = "attendance_corrected" if existing else "attendance_recorded"
            log_action(request.user, action, record, f"{record.employee.employee_id} {record.date} {record.status}")
            if existing:
                notify(record.employee.user, f"Your attendance for {record.date:%d %b %Y} was updated by HR.", "/attendance/")
            messages.success(request, "Attendance corrected." if existing else "Attendance recorded.")
            return redirect("attendance:list")
    else:
        initial = {"date": timezone.localdate()}
        emp_id = parse_int(request.GET.get("employee"))
        day = parse_date(request.GET.get("date"))
        if emp_id:
            initial["employee"] = emp_id
        if day:
            initial["date"] = day
        if emp_id and day:
            existing = Attendance.objects.filter(employee_id=emp_id, date=day).first()
        form = AttendanceRecordForm(instance=existing, initial=initial)
    return render(
        request,
        "generic_form.html",
        {
            "form": form,
            "title": "Record or correct attendance",
            "intro": "Saving for an employee and date that already has a record corrects that record.",
            "cancel_url": "attendance:list",
            "submit_label": "Save attendance",
        },
    )


@login_required
def attendance_summary(request):
    user = request.user
    today = timezone.localdate()
    year = parse_int(request.GET.get("year"), today.year, 2000, 2100)
    month = parse_int(request.GET.get("month"), today.month, 1, 12)
    start, end = month_bounds(year, month)
    employees = Employee.objects.select_related("user", "department")
    if user.is_hr_or_admin:
        department = request.GET.get("department", "")
        if department.isdigit():
            employees = employees.filter(department_id=int(department))
        employees = employees.filter(status=Employee.Status.ACTIVE)
    else:
        if user.employee_profile is None:
            raise PermissionDenied
        employees = employees.filter(pk=user.employee_profile.pk)
        department = ""
    rows = services.monthly_summary(employees, start, end)
    page_obj, querystring = paginate(request, rows, per_page=25)
    return render(
        request,
        "attendance/summary.html",
        {
            "page_obj": page_obj,
            "querystring": querystring,
            "year": year,
            "month": month,
            "months": [(i, calendar.month_name[i]) for i in range(1, 13)],
            "departments": Department.objects.all(),
            "department": department,
        },
    )


def _self_service_guard(request):
    if not settings.SMARTHR["ENABLE_SELF_CHECKIN"]:
        messages.error(request, "Self check-in is disabled by your organization.")
        return None
    employee = request.user.employee_profile
    if employee is None or employee.status != Employee.Status.ACTIVE:
        messages.error(request, "No active employee profile is linked to your account.")
        return None
    return employee


@login_required
@require_POST
def check_in(request):
    employee = _self_service_guard(request)
    if employee:
        try:
            record = services.check_in_employee(employee)
            messages.success(request, f"Checked in at {record.check_in:%H:%M}.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return safe_redirect(request, "core:dashboard")


@login_required
@require_POST
def check_out(request):
    employee = _self_service_guard(request)
    if employee:
        try:
            record = services.check_out_employee(employee)
            messages.success(request, f"Checked out at {record.check_out:%H:%M}. Worked {record.worked_display}.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return safe_redirect(request, "core:dashboard")
