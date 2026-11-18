"""Development-only demo data. Requires DEBUG=True and DEMO_PASSWORD in the environment.

    python manage.py seed_demo

Creates clearly fictional departments, employees, attendance, leave and payroll. Safe to re-run."""
import os
import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from attendance.models import Attendance
from core.models import Holiday
from departments.models import Department, Designation
from employees.models import Employee
from leaves import services as leave_services
from leaves.models import LeaveRequest, LeaveType
from payroll import services as payroll_services
from payroll.models import Payroll, SalaryStructure

PEOPLE = [
    ("EMP0001", "Asha", "Verma", "admin", "Human Resources", "HR Director"),
    ("EMP0002", "Rohan", "Mehta", "hr", "Human Resources", "HR Manager"),
    ("EMP0003", "Priya", "Nair", "employee", "Engineering", "Software Engineer"),
    ("EMP0004", "Kabir", "Shah", "employee", "Engineering", "Senior Engineer"),
    ("EMP0005", "Neha", "Iyer", "employee", "Finance", "Accountant"),
    ("EMP0006", "Arjun", "Rao", "employee", "Sales", "Sales Executive"),
    ("EMP0007", "Meera", "Das", "employee", "Sales", "Sales Executive"),
    ("EMP0008", "Vikram", "Singh", "employee", "Operations", "Operations Analyst"),
]
DEPARTMENTS = [("Human Resources", "HR"), ("Engineering", "ENG"), ("Finance", "FIN"), ("Sales", "SAL"), ("Operations", "OPS")]
LEAVE_TYPES = [("Annual Leave", "18"), ("Sick Leave", "10"), ("Casual Leave", "8")]


class Command(BaseCommand):
    help = "Create fictional demo data (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DJANGO_DEBUG=True.")
        password = os.environ.get("DEMO_PASSWORD", "")
        if len(password) < 10:
            raise CommandError("Set DEMO_PASSWORD (min 10 characters) in your environment or .env first.")
        rng = random.Random(42)
        today = timezone.localdate()

        departments = {n: Department.objects.get_or_create(name=n, defaults={"code": c})[0] for n, c in DEPARTMENTS}
        for _, _, _, _, _, title in PEOPLE:
            Designation.objects.get_or_create(name=title)
        for name, days in LEAVE_TYPES:
            LeaveType.objects.get_or_create(name=name, defaults={"default_allowance": Decimal(days)})

        employees = []
        for emp_id, first, last, role, dept, title in PEOPLE:
            user, created = User.objects.get_or_create(
                username=emp_id.lower(),
                defaults={"first_name": first, "last_name": last, "email": f"{first.lower()}.{last.lower()}@demo.smarthr.example", "role": role},
            )
            if created:
                user.set_password(password)
                user.can_manage_payroll = role == "hr"
                user.save()
            employee, _ = Employee.objects.get_or_create(
                employee_id=emp_id,
                defaults={"user": user, "department": departments[dept], "designation": Designation.objects.get(name=title),
                          "joining_date": today - timedelta(days=400), "phone": "0000000000"},
            )
            employees.append(employee)
            SalaryStructure.objects.get_or_create(
                employee=employee, effective_date=today - timedelta(days=365),
                defaults={"basic_salary": Decimal(rng.randrange(30000, 90000, 500)), "allowances": Decimal("5000.00"),
                          "pf_percent": Decimal("12.00"), "tax_percent": Decimal("5.00"), "other_deductions": Decimal("200.00")},
            )

        # Attendance for the last 14 days (working days only)
        start_time = settings.SMARTHR["WORK_START"]
        for offset in range(14):
            day = today - timedelta(days=offset)
            if day.weekday() not in settings.SMARTHR["WORKING_WEEKDAYS"]:
                continue
            for emp in employees:
                if Attendance.objects.filter(employee=emp, date=day).exists():
                    continue
                roll = rng.random()
                if roll < 0.06:
                    Attendance.objects.create(employee=emp, date=day, status=Attendance.Status.ABSENT)
                    continue
                minutes = rng.choice([-25, -20, -10, 0, 5, 10, 30, 45])
                check_in = (datetime.combine(day, start_time) + timedelta(minutes=minutes)).time()
                check_out = None if (offset == 0 and rng.random() < 0.5) or roll > 0.97 else (
                    datetime.combine(day, settings.SMARTHR["WORK_END"]) + timedelta(minutes=rng.choice([0, 15, 30]))
                ).time()
                late = minutes > settings.SMARTHR["GRACE_MINUTES"]
                Attendance.objects.create(
                    employee=emp, date=day, check_in=check_in, check_out=check_out,
                    status=Attendance.Status.LATE if late else Attendance.Status.PRESENT,
                )

        # Leave: a few pending and one approved (processed through the real workflow)
        reviewer = User.objects.get(username="emp0002")
        annual = LeaveType.objects.get(name="Annual Leave")
        sick = LeaveType.objects.get(name="Sick Leave")
        next_monday = today + timedelta(days=(7 - today.weekday()))
        if not LeaveRequest.objects.exists():
            for emp, lt, shift, length in ((employees[2], annual, 0, 2), (employees[4], sick, 7, 1), (employees[5], annual, 14, 3)):
                s = next_monday + timedelta(days=shift)
                if s.year != (s + timedelta(days=length)).year:
                    continue
                leave_services.submit_request(emp, lt, s, s + timedelta(days=length - 1), "Demo leave request")
            approve = LeaveRequest.objects.filter(employee=employees[4]).first()
            if approve:
                leave_services.approve_request(approve.pk, reviewer, "Approved (demo)")

        Holiday.objects.get_or_create(date=today.replace(month=12, day=25), defaults={"name": "Demo holiday"})

        # Payroll for the previous month (approved) via the real service
        first_of_month = today.replace(day=1)
        prev = first_of_month - timedelta(days=1)
        admin = User.objects.get(username="emp0001")
        payroll_services.generate_payroll(prev.year, prev.month, admin)
        for payroll_id in Payroll.objects.filter(year=prev.year, month=prev.month, status=Payroll.Status.GENERATED).values_list("pk", flat=True):
            payroll_services.approve_payroll(payroll_id, admin)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write("Logins (password = your DEMO_PASSWORD): emp0001 (admin), emp0002 (HR, payroll), emp0003 … emp0008 (employees).")
