"""Report builders. Each takes the request and returns (headers, rows) as plain Python values."""
from django.db.models import Count, Q
from django.utils import timezone

from attendance import services as attendance_services
from attendance.models import Attendance
from core.utils import month_bounds, parse_date, parse_int
from employees.models import Employee
from leaves.models import LeaveBalance, LeaveRequest
from payroll.models import Payroll


def _dept(request):
    value = request.GET.get("department", "")
    return int(value) if value.isdigit() else None


def _name(emp):
    return emp.full_name


def employee_directory(request):
    qs = Employee.objects.select_related("user", "department", "designation")
    if _dept(request):
        qs = qs.filter(department_id=_dept(request))
    status = request.GET.get("status", "")
    if status in Employee.Status.values:
        qs = qs.filter(status=status)
    headers = ["Employee ID", "Name", "Work email", "Department", "Designation", "Employment type", "Status", "Joining date"]
    rows = [
        [e.employee_id, e.full_name, e.work_email, e.department or "", e.designation or "", e.get_employment_type_display(), e.get_status_display(), e.joining_date]
        for e in qs
    ]
    return headers, rows


def department_headcount(request):
    from departments.models import Department

    qs = Department.objects.annotate(
        active=Count("employees", filter=Q(employees__status=Employee.Status.ACTIVE)),
        total=Count("employees"),
    )
    headers = ["Department", "Code", "Active employees", "All employees", "Department active"]
    return headers, [[d.name, d.code, d.active, d.total, "Yes" if d.is_active else "No"] for d in qs]


def daily_attendance(request):
    day = parse_date(request.GET.get("date"), timezone.localdate())
    qs = Attendance.objects.filter(date=day).select_related("employee__user", "employee__department")
    if _dept(request):
        qs = qs.filter(employee__department_id=_dept(request))
    status = request.GET.get("status", "")
    if status in Attendance.Status.values:
        qs = qs.filter(status=status)
    headers = ["Date", "Employee ID", "Name", "Department", "Status", "Check-in", "Check-out", "Worked"]
    rows = [
        [a.date, a.employee.employee_id, a.employee.full_name, a.employee.department or "", a.get_status_display(),
         a.check_in.strftime("%H:%M") if a.check_in else "", a.check_out.strftime("%H:%M") if a.check_out else "", a.worked_display]
        for a in qs
    ]
    return headers, rows


def monthly_attendance(request):
    today = timezone.localdate()
    year = parse_int(request.GET.get("year"), today.year, 2000, 2100)
    month = parse_int(request.GET.get("month"), today.month, 1, 12)
    start, end = month_bounds(year, month)
    employees = Employee.objects.filter(status=Employee.Status.ACTIVE).select_related("user", "department")
    if _dept(request):
        employees = employees.filter(department_id=_dept(request))
    headers = ["Employee ID", "Name", "Department", "Present", "Late", "Half-day", "Absent", "On leave"]
    rows = [
        [e.employee_id, e.full_name, e.department or "", e.present_days, e.late_days, e.half_days, e.absent_days, e.leave_days]
        for e in attendance_services.monthly_summary(employees, start, end)
    ]
    return headers, rows


def _range(request):
    today = timezone.localdate()
    start = parse_date(request.GET.get("date_from"), month_bounds(today.year, today.month)[0])
    end = parse_date(request.GET.get("date_to"), today)
    return start, end


def _attendance_rows(qs, request):
    if _dept(request):
        qs = qs.filter(employee__department_id=_dept(request))
    headers = ["Date", "Employee ID", "Name", "Department", "Status", "Check-in", "Check-out"]
    rows = [
        [a.date, a.employee.employee_id, a.employee.full_name, a.employee.department or "", a.get_status_display(),
         a.check_in.strftime("%H:%M") if a.check_in else "", a.check_out.strftime("%H:%M") if a.check_out else ""]
        for a in qs.select_related("employee__user", "employee__department")
    ]
    return headers, rows


def late_arrivals_report(request):
    start, end = _range(request)
    return _attendance_rows(attendance_services.late_arrivals(start, end), request)


def missing_punches_report(request):
    start, end = _range(request)
    return _attendance_rows(attendance_services.missing_punches(start, end), request)


def leave_history(request):
    start, end = _range(request)
    qs = LeaveRequest.objects.filter(start_date__lte=end, end_date__gte=start).select_related(
        "employee__user", "employee__department", "leave_type", "reviewer"
    )
    if _dept(request):
        qs = qs.filter(employee__department_id=_dept(request))
    status = request.GET.get("status", "")
    if status in LeaveRequest.Status.values:
        qs = qs.filter(status=status)
    headers = ["Employee ID", "Name", "Leave type", "Start", "End", "Days", "Status", "Reviewer", "Reviewed at", "Comments"]
    rows = [
        [r.employee.employee_id, r.employee.full_name, r.leave_type.name, r.start_date, r.end_date, r.days,
         r.get_status_display(), r.reviewer.display_name if r.reviewer else "",
         timezone.localtime(r.reviewed_at).strftime("%Y-%m-%d %H:%M") if r.reviewed_at else "", r.review_comments]
        for r in qs
    ]
    return headers, rows


def leave_utilization(request):
    year = parse_int(request.GET.get("year"), timezone.localdate().year, 2000, 2100)
    qs = LeaveBalance.objects.filter(year=year).select_related("employee__user", "employee__department", "leave_type")
    if _dept(request):
        qs = qs.filter(employee__department_id=_dept(request))
    headers = ["Employee ID", "Name", "Department", "Leave type", "Year", "Allocated", "Used", "Remaining"]
    rows = [
        [b.employee.employee_id, b.employee.full_name, b.employee.department or "", b.leave_type.name, b.year, b.allocated, b.used, b.remaining]
        for b in qs.order_by("employee__employee_id", "leave_type__name")
    ]
    return headers, rows


def payroll_summary(request):
    today = timezone.localdate()
    year = parse_int(request.GET.get("year"), today.year, 2000, 2100)
    month = parse_int(request.GET.get("month"), today.month, 1, 12)
    qs = Payroll.objects.filter(year=year, month=month).select_related("employee__user", "employee__department")
    if _dept(request):
        qs = qs.filter(employee__department_id=_dept(request))
    status = request.GET.get("status", "")
    if status in Payroll.Status.values:
        qs = qs.filter(status=status)
    headers = ["Employee ID", "Name", "Department", "Period", "Gross", "Total deductions", "Net", "Approval", "Payment"]
    rows = [
        [p.employee.employee_id, p.employee.full_name, p.employee.department or "", p.period_label, p.gross_salary,
         p.total_deductions, p.net_salary, p.get_status_display(), p.get_payment_status_display()]
        for p in qs
    ]
    return headers, rows
