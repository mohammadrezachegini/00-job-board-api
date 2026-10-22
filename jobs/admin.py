from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CandidateProfile, User, Company


@admin.register(User)
class JobBoradUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_staff")
    list_filter = ("role", "is_staff")
    fieldsets = UserAdmin.fieldsets + (("Job board", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Job board",
            {
                "fields": (
                    "email",
                    "role",
                )
            },
        ),
    )


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "is_verified", "created_at")
    list_filter = ("is_verified",)
    list_editable = ("is_verified",)
    search_fields = ("name", "user__email")


@admin.register(CandidateProfile)
class CandidateProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "headline", "location")
    search_fields = ("user__username", "user__email")
