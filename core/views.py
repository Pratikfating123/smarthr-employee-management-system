from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from attendance import services as attendance_services
from attendance.models import Attendance
from core.models import AuditLog, Holiday
from core.permissions import admin_required
from core.utils import month_bounds, paginate, parse_date
from departments.models import Department
from employees.models import Employee
from leaves.models import LeaveRequest
from leaves.services import balance_summary
from payroll.models import Payroll

PRESENT_LIKE = [Attendance.Status.PRESENT, Attendance.Status.LATE, Attendance.Status.HALF_DAY]


def _greeting():
    hour = timezone.localtime().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


@login_required
def dashboard(request):
    if request.user.is_hr_or_admin:
        return _hr_dashboard(request)
    return _employee_dashboard(request)


def _is_working_day(day):
    return day.weekday() in settings.SMARTHR["WORKING_WEEKDAYS"] and not Holiday.objects.filter(date=day).exists()


def _hr_dashboard(request):
    today = timezone.localdate()
    day = parse_date(request.GET.get("date"), today)
    active = Employee.objects.filter(status=Employee.Status.ACTIVE)
    records = Attendance.objects.filter(date=day, employee__status=Employee.Status.ACTIVE)

    present = records.filter(status__in=PRESENT_LIKE).count()
    late_qs = attendance_services.late_arrivals(day).filter(employee__status=Employee.Status.ACTIVE)
    early_qs = attendance_services.early_arrivals(day).filter(employee__status=Employee.Status.ACTIVE)
    missing_qs = attendance_services.missing_punches(day).filter(employee__status=Employee.Status.ACTIVE)

    absent = 0
    if day <= today and _is_working_day(day):
        accounted = set(
            records.filter(status__in=PRESENT_LIKE + [Attendance.Status.ON_LEAVE, Attendance.Status.HOLIDAY]).values_list("employee_id", flat=True)
        )
        on_leave = set(
            LeaveRequest.objects.filter(status=LeaveRequest.Status.APPROVED, start_date__lte=day, end_date__gte=day)
            .values_list("employee_id", flat=True)
        )
        absent = active.exclude(pk__in=accounted | on_leave).count()

    pending_qs = LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING)
    distribution = (
        Department.objects.annotate(headcount=Count("employees", filter=Q(employees__status=Employee.Status.ACTIVE)))
        .filter(headcount__gt=0)
        .order_by("-headcount", "name")
    )
    stats = [
        {"label": "Active employees", "value": active.count(), "icon": "people"},
        {"label": "Present", "value": present, "icon": "person-check"},
        {"label": "Late arrivals", "value": late_qs.count(), "icon": "alarm"},
        {"label": "Pending leave requests", "value": pending_qs.count(), "icon": "calendar-event"},
        {"label": "Absent", "value": absent, "icon": "person-x"},
    ]
    context = {
        "greeting": _greeting(),
        "day": day,
        "today": today,
        "stats": stats,
        "pending_leaves": pending_qs.select_related("employee__user", "leave_type")[:8],
        "early": early_qs.select_related("employee__user")[:6],
        "early_count": early_qs.count(),
        "late": late_qs.select_related("employee__user")[:6],
        "late_count": late_qs.count(),
        "missing": missing_qs.select_related("employee__user")[:6],
        "missing_count": missing_qs.count(),
        "chart_labels": [d.name for d in distribution],
        "chart_values": [d.headcount for d in distribution],
        "schedule": settings.SMARTHR,
    }
    return render(request, "dashboard/hr.html", context)


def _employee_dashboard(request):
    employee = request.user.employee_profile
    today = timezone.localdate()
    context = {"greeting": _greeting(), "today": today, "employee": employee}
    if employee is not None:
        start, end = month_bounds(today.year, today.month)
        month_records = Attendance.objects.filter(employee=employee, date__range=(start, end))
        record = Attendance.objects.filter(employee=employee, date=today).first()
        context.update(
            {
                "record": record,
                "month_summary": [
                    (label, month_records.filter(status=value).count()) for value, label in Attendance.Status.choices
                ],
                "balances": balance_summary(employee, today.year),
                "pending_leaves": LeaveRequest.objects.filter(employee=employee, status=LeaveRequest.Status.PENDING).select_related("leave_type"),
                "recent_leaves": LeaveRequest.objects.filter(employee=employee).select_related("leave_type")[:5],
                "payslips": Payroll.objects.filter(employee=employee, status=Payroll.Status.APPROVED)[:3],
                "self_checkin": settings.SMARTHR["ENABLE_SELF_CHECKIN"] and employee.status == Employee.Status.ACTIVE,
                "can_check_in": record is None or (record.check_in is None and record.status not in (Attendance.Status.ON_LEAVE, Attendance.Status.HOLIDAY)),
                "can_check_out": record is not None and record.check_in is not None and record.check_out is None,
            }
        )
    return render(request, "dashboard/employee.html", context)


@admin_required
def audit_log(request):
    entries = AuditLog.objects.select_related("actor")
    action = request.GET.get("action", "").strip()
    if action:
        entries = entries.filter(action__icontains=action)
    page_obj, querystring = paginate(request, entries, per_page=30)
    return render(request, "core/audit_log.html", {"page_obj": page_obj, "querystring": querystring, "action": action})


def error_403(request, exception=None):
    return render(request, "403.html", status=403)


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
