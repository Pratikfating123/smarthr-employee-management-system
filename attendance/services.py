"""Attendance business rules. Schedule values come from settings.SMARTHR (env-configurable)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Attendance

_REF = date(2000, 1, 1)


def cfg():
    return settings.SMARTHR


def _shift(t, minutes):
    return (datetime.combine(_REF, t) + timedelta(minutes=minutes)).time()


def early_threshold():
    """Check-ins at or before this time count as early arrivals."""
    return _shift(cfg()["WORK_START"], -cfg()["EARLY_ARRIVAL_MINUTES"])


def late_threshold():
    """Check-ins after this time (work start + grace) count as late."""
    return _shift(cfg()["WORK_START"], cfg()["GRACE_MINUTES"])


def classify_arrival(check_in: time) -> str:
    if check_in <= early_threshold():
        return "early"
    if check_in > late_threshold():
        return "late"
    return "on_time"


def local_now():
    return timezone.localtime(timezone.now())


@transaction.atomic
def check_in_employee(employee, when=None):
    when = when or local_now()
    today = when.date()
    now_time = when.time().replace(microsecond=0)
    status = Attendance.Status.LATE if classify_arrival(now_time) == "late" else Attendance.Status.PRESENT
    record, created = Attendance.objects.select_for_update().get_or_create(
        employee=employee, date=today, defaults={"check_in": now_time, "status": status}
    )
    if created:
        return record
    if record.status in (Attendance.Status.ON_LEAVE, Attendance.Status.HOLIDAY):
        raise ValidationError(f"Today is marked as {record.get_status_display().lower()}; check-in is not available.")
    if record.check_in:
        raise ValidationError("You have already checked in today.")
    record.check_in = now_time
    record.status = status
    record.full_clean()
    record.save()
    return record


@transaction.atomic
def check_out_employee(employee, when=None):
    when = when or local_now()
    now_time = when.time().replace(microsecond=0)
    try:
        record = Attendance.objects.select_for_update().get(employee=employee, date=when.date())
    except Attendance.DoesNotExist:
        raise ValidationError("You have not checked in today.")
    if not record.check_in:
        raise ValidationError("You have not checked in today.")
    if record.check_out:
        raise ValidationError("You have already checked out today.")
    if now_time <= record.check_in:
        raise ValidationError("Check-out must be later than check-in.")
    record.check_out = now_time
    worked = record.worked_hours
    if worked is not None and worked < Decimal(cfg()["HALF_DAY_MIN_HOURS"]):
        record.status = Attendance.Status.HALF_DAY
    record.full_clean()
    record.save()
    return record


def early_arrivals(day):
    return Attendance.objects.filter(
        date=day, check_in__isnull=False, check_in__lte=early_threshold()
    ).exclude(status__in=[Attendance.Status.ABSENT, Attendance.Status.ON_LEAVE, Attendance.Status.HOLIDAY])


def late_arrivals(day, end=None):
    """Late arrivals on `day`, or between `day` and `end` inclusive."""
    return Attendance.objects.filter(date__range=(day, end or day)).filter(
        Q(status=Attendance.Status.LATE) | Q(check_in__gt=late_threshold())
    ).exclude(status__in=[Attendance.Status.ABSENT, Attendance.Status.ON_LEAVE, Attendance.Status.HOLIDAY])


def missing_punches(day, end=None, now=None):
    """Records with only one punch between day and end. Today's missing check-out only counts after work end."""
    now = now or local_now()
    today = now.date()
    end = min(end or day, today)
    if day > end:
        return Attendance.objects.none()
    qs = Attendance.objects.filter(date__range=(day, end)).exclude(
        status__in=[Attendance.Status.ABSENT, Attendance.Status.ON_LEAVE, Attendance.Status.HOLIDAY]
    )
    missing_out = Q(check_in__isnull=False, check_out__isnull=True)
    missing_in = Q(check_in__isnull=True, check_out__isnull=False)
    if now.time() > cfg()["WORK_END"]:
        return qs.filter(missing_in | missing_out)
    return qs.filter(missing_in | (missing_out & ~Q(date=today)))


def monthly_summary(employees, start, end):
    """Annotate an Employee queryset with per-status counts between start and end (inclusive)."""
    window = Q(attendance_records__date__gte=start, attendance_records__date__lte=end)
    kwargs = {
        key: Count("attendance_records", filter=window & Q(attendance_records__status=value))
        for key, value in (
            ("present_days", Attendance.Status.PRESENT),
            ("late_days", Attendance.Status.LATE),
            ("half_days", Attendance.Status.HALF_DAY),
            ("absent_days", Attendance.Status.ABSENT),
            ("leave_days", Attendance.Status.ON_LEAVE),
        )
    }
    return employees.annotate(**kwargs)
