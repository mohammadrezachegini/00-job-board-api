from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class JobBoradUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_staff")
    list_filter = ("role", "is_staff")
    fieldsets = UserAdmin.fieldsets + (("Job board", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Job board", {"fields": ("email", "role",)}),)