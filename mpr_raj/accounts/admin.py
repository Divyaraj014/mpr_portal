from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count

from .models import (
    Department, Designation, District, MPREntry, MPRLock, MPRPeriod, ParameterValue,
    PlaceOfPosting, Project, ProjectParameter, User,
)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(PlaceOfPosting, Designation)
class LookupAdmin(admin.ModelAdmin):
    """Name-only lists an admin adds to as postings and grades appear."""

    list_display = ("name", "user_count")
    search_fields = ("name",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_users=Count("users"))

    @admin.display(description="Employees", ordering="_users")
    def user_count(self, obj):
        return obj._users


admin.site.register(Department)


class ProjectParameterInline(admin.TabularInline):
    model = ProjectParameter
    extra = 1


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "prism_id", "category", "department", "targeted_user")
    readonly_fields = ("code",)  # assigned by Project.save()
    list_filter = ("category", "department")
    search_fields = ("name", "prism_id")
    inlines = [ProjectParameterInline]


@admin.register(MPRPeriod)
class MPRPeriodAdmin(admin.ModelAdmin):
    list_display = ("__str__", "due_date", "is_open")
    list_filter = ("is_open", "year")


@admin.register(MPREntry)
class MPREntryAdmin(admin.ModelAdmin):
    list_display = ("period", "author", "kind", "scope", "project", "title", "date")
    list_filter = ("kind", "period", "scope")
    search_fields = ("title", "description")

    # Which row this is, before which section's columns it gets.
    BASE_FIELDS = ["period", "author", "kind", "scope", "project"]

    def get_fields(self, request, obj=None):
        """
        Only the columns this section actually uses — same `FIELDS` map the filling
        forms read, so admin can't put an award level on a training row. Adding is
        two steps (pick the kind, then fill it), like Django's own UserAdmin.
        """
        if obj is None:
            return self.BASE_FIELDS
        return self.BASE_FIELDS + MPREntry.FIELDS.get(obj.kind, [])

    def get_readonly_fields(self, request, obj=None):
        # Re-kinding an existing row would strand the old section's columns behind it.
        return ("kind",) if obj else ()


@admin.register(MPRLock)
class MPRLockAdmin(admin.ModelAdmin):
    list_display = ("user", "period", "locked_at", "unlock_requested")
    list_filter = ("period", "unlock_requested")


@admin.register(ParameterValue)
class ParameterValueAdmin(admin.ModelAdmin):
    list_display = ("period", "parameter", "previous_month", "reporting_month", "cumulative")
    list_filter = ("period", "parameter__project")


@admin.register(User)
class NICUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "NIC details",
            {
                "fields": (
                    "name",
                    "employee_code",
                    "phone",
                    "ip_phone",
                    "place_of_posting",
                    "designation",
                )
            },
        ),
        ("Roles", {"fields": ("is_sio", "is_gl", "is_pl", "is_dio")}),
        ("Account state", {"fields": ("must_change_password", "is_activated")}),
    )
    list_display = ("username", "name", "email", "is_staff", "is_sio", "is_gl", "is_pl", "is_dio",
                    "is_activated")
    list_filter = UserAdmin.list_filter + ("is_sio", "is_gl", "is_pl", "is_dio", "is_activated")
    search_fields = ("username", "name", "email", "employee_code")
