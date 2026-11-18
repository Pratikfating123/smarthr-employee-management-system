from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class SmartHRUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "can_manage_payroll", "is_active")
    list_filter = ("role", "is_active", "can_manage_payroll")
    fieldsets = UserAdmin.fieldsets + (("SmartHR", {"fields": ("role", "can_manage_payroll")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("SmartHR", {"fields": ("email", "role", "can_manage_payroll")}),)
