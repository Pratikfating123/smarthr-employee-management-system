
import os
import django
from datetime import date, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from departments.models import Department, Designation
from employees.models import Employee

User = get_user_model()

# Read password from Django settings, which loads .env
from django.conf import settings
password = os.getenv("DEMO_PASSWORD") or getattr(settings, "DEMO_PASSWORD", None)

if not password:
    raise ValueError("DEMO_PASSWORD is missing from your environment/.env file.")

first_names = [
    "Aarav", "Aditya", "Akash", "Amit", "Aniket",
    "Arjun", "Ashish", "Karan", "Rahul", "Rohan",
    "Sahil", "Saurabh"
]

last_names = [
    "Sharma", "Patil", "Deshmukh", "Kulkarni",
    "Joshi", "Pawar", "Jadhav", "More",
    "Kadam", "Chavan", "Verma", "Singh"
]

designation_map = {
    "Information Technology": [
        "IT Manager", "Software Developer", "Network Engineer",
        "System Administrator", "IT Support Engineer",
        "Database Administrator", "Cybersecurity Analyst"
    ],
    "Maintenance": [
        "Maintenance Manager", "Maintenance Technician",
        "Electrician", "Plumber", "HVAC Technician",
        "Facility Technician", "Maintenance Supervisor"
    ],
    "Finance": [
        "Finance Manager", "Accountant", "Accounts Executive",
        "Payroll Officer", "Auditor", "Tax Consultant",
        "Financial Analyst"
    ],
    "Finance & Accounts": [
        "Finance Manager", "Accountant", "Accounts Executive",
        "Payroll Officer", "Auditor", "Tax Consultant",
        "Financial Analyst"
    ],
    "Marketing": [
        "Marketing Manager", "Marketing Executive", "SEO Specialist",
        "Content Writer", "Social Media Executive",
        "Graphic Designer", "Brand Executive"
    ],
    "Operations": [
        "Operations Manager", "Operations Executive", "Team Leader",
        "Process Analyst", "Operations Coordinator",
        "Quality Analyst", "Shift Supervisor"
    ],
    "Administration": [
        "Admin Manager", "Admin Officer", "Office Assistant",
        "Receptionist", "Office Coordinator",
        "Documentation Executive", "Facilities Coordinator"
    ],
    "Security": [
        "Security Manager", "Security Officer", "Security Supervisor",
        "Safety Officer", "CCTV Operator", "Security Guard",
        "Fire Safety Officer"
    ],
    "Customer Support": [
        "Support Manager", "Customer Support Executive",
        "Helpdesk Executive", "Customer Relationship Officer",
        "Call Centre Executive", "Technical Support Executive",
        "Service Coordinator"
    ],
    "Procurement": [
        "Procurement Manager", "Purchase Officer", "Vendor Manager",
        "Inventory Executive", "Store Keeper",
        "Supply Chain Analyst", "Procurement Executive"
    ],
    "Human Resources": [
        "HR Manager", "HR Executive", "Recruitment Specialist",
        "HR Coordinator", "Training Officer",
        "Talent Acquisition Executive", "Employee Relations Officer"
    ],
    "Engineering": [
        "Engineering Manager", "Project Engineer", "Software Engineer",
        "Quality Engineer", "Design Engineer",
        "Technical Engineer", "Junior Engineer"
    ],
    "Sales": [
        "Sales Manager", "Sales Executive", "Business Development Executive",
        "Sales Coordinator", "Account Manager",
        "Inside Sales Executive", "Sales Representative"
    ],
}

created = 0

for department in Department.objects.filter(is_active=True).order_by("name"):
    existing_count = Employee.objects.filter(department=department).count()
    required = max(0, 7 - existing_count)

    if required == 0:
        print(f"SKIPPED: {department.name}, already has {existing_count}")
        continue

    titles = designation_map.get(
        department.name,
        [
            "Department Manager", "Senior Executive", "Executive",
            "Assistant", "Officer", "Associate", "Junior Executive"
        ]
    )

    department_code = department.code.upper()

    for i in range(required):
        number = 1

        while True:
            employee_id = f"DEMO-{department_code}-{number:03d}"
            username = f"demo_{department_code.lower()}_{number:03d}"
            email = f"{username}@smarthr.demo"

            if (
                not Employee.objects.filter(employee_id=employee_id).exists()
                and not User.objects.filter(username=username).exists()
                and not User.objects.filter(email=email).exists()
            ):
                break

            number += 1

        first_name = first_names[(number - 1) % len(first_names)]
        last_name = last_names[(number - 1) % len(last_names)]

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role="employee",
        )

        designation, _ = Designation.objects.get_or_create(
            name=titles[(number - 1) % len(titles)]
        )

        Employee.objects.create(
            employee_id=employee_id,
            user=user,
            department=department,
            designation=designation,
            joining_date=date.today() - timedelta(days=30 + number * 15),
            employment_type="full_time",
            status="active",
        )

        created += 1

    print(f"UPDATED: {department.name}, now has {Employee.objects.filter(department=department).count()} employees")

print("\nEMPLOYEE GENERATION COMPLETED")
print("New employees created:", created)
print("Total employee profiles:", Employee.objects.count())

print("\nFINAL DEPARTMENT COUNTS:")
for department in Department.objects.filter(is_active=True).order_by("name"):
    count = Employee.objects.filter(department=department).count()
    print(f"{department.name}: {count}")
