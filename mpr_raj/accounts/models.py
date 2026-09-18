import calendar
import re

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import capfirst


class District(models.Model):
    """A Rajasthan district. Filled/locked by its assigned DIO. Admin-managed."""

    name = models.CharField(max_length=100, unique=True)
    # One DIO per district; a DIO may hold several districts (reverse: user.districts).
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="districts",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(models.Model):
    """Owning department of a project (Transport, Revenue, …). Admin-managed list."""

    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PlaceOfPosting(models.Model):
    """Where an employee sits (a district, the State Centre, a division). Admin-managed."""

    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "place of posting"
        verbose_name_plural = "places of posting"

    def __str__(self):
        return self.name


class Designation(models.Model):
    """An NIC grade/post (Scientist-D, Section Officer, …). Admin-managed."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        # ponytail: alphabetical, not by seniority. Add an `order` field if the
        # employee list ever needs ranking (see ProjectParameter.order).
        ordering = ["name"]

    def __str__(self):
        return self.name


class Project(models.Model):
    """An NIC project. Filled/locked by its assigned Project Leader. Admin-managed."""

    CENTRAL = "central"
    STATE = "state"
    CATEGORY_CHOICES = [(CENTRAL, "Central"), (STATE, "State")]

    # The portal's own handle for a project: P001, P002, … Assigned on first save
    # and never shown as an editable field, unlike prism_id, which is issued by
    # PRISM and typed in by the admin.
    code = models.CharField("Project ID", max_length=10, unique=True, blank=True)
    name = models.CharField(max_length=150)
    # NULL rather than "" when unknown — plenty of projects have no PRISM ID yet,
    # and Postgres counts NULLs as distinct, so they don't fight over the unique
    # index the way empty strings would. The usual "no null on a CharField" rule
    # doesn't survive contact with a unique column that is often blank.
    prism_id = models.CharField("PRISM ID", max_length=50, unique=True, null=True, blank=True)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default=STATE)
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="projects",
    )
    targeted_user = models.CharField(
        max_length=200, blank=True, help_text="Who the project serves, e.g. Citizens, Dept. officials."
    )
    url = models.URLField("URL", blank=True)
    # One PL per project; a PL may hold several projects (reverse: user.projects).
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="projects",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.prism_id})" if self.prism_id else self.name

    @classmethod
    def next_code(cls):
        """
        One past the highest P-number in use. Reads the numbers rather than
        counting rows, so deleting P003 doesn't hand its code to the next project.

        Numbering is gapless, so deleting the newest project frees its number for
        the next one. Deleting one from the middle leaves a hole that stays a hole.

        ponytail: scans the code column, which is fine for a few hundred projects.
        Two admins saving at the same instant would compute the same code — the
        unique constraint turns that into a loud error, not a duplicate. Switch to
        a Postgres sequence if either the reuse or the race ever matters; that
        trades gapless numbering for codes that are never handed out twice.
        """
        used = [
            int(m.group(1))
            for code in cls.objects.values_list("code", flat=True)
            if (m := re.fullmatch(r"P(\d+)", code or ""))
        ]
        return f"P{max(used, default=0) + 1:03d}"

    def save(self, *args, **kwargs):  # noqa: DJ012 — reads after next_code(), which it calls.
        if not self.code:
            self.code = self.next_code()
        super().save(*args, **kwargs)


class User(AbstractUser):
    """NIC employee. Login ID (username) = email prefix. Admin role = is_staff."""

    name = models.CharField(max_length=150, blank=True)
    employee_code = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    ip_phone = models.CharField(max_length=15, blank=True)

    # Admin-managed lists, same as District/Department — deleting one leaves the
    # employees behind without a posting/grade rather than taking them with it.

    place_of_posting = models.ForeignKey(
        PlaceOfPosting,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )

    designation = models.ForeignKey(
        Designation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )

    # Role flags (a user can hold several). Admin uses Django's is_staff.
    is_sio = models.BooleanField("SIO / Addl. SIO", default=False)
    is_gl = models.BooleanField("Group Leader", default=False)
    is_pl = models.BooleanField("Project Leader", default=False)
    is_dio = models.BooleanField("DIO", default=False)

    must_change_password = models.BooleanField(default=True)
    is_activated = models.BooleanField(default=False)

    # Master data this employee owns lives on the reverse side of the FKs above:
    # user.projects (Project.leader) and user.districts (District.officer).

    def save(self, *args, **kwargs):
        if not self.username and self.email:
            self.username = self.email.split("@")[0]
        super().save(*args, **kwargs)

    # (flag, full name, abbreviation), in the order roles are listed everywhere.
    # Admin is Django's is_staff; the rest are the fields above. Templates read
    # roles_display / roles_short instead of testing each flag, so adding a role
    # is one line here.
    ROLES = [
        ("is_staff", "Admin", "Admin"),
        ("is_sio", "SIO / Additional SIO", "SIO"),
        ("is_gl", "Group Leader", "GL"),
        ("is_pl", "Project Leader", "PL"),
        ("is_dio", "District Informatics Officer", "DIO"),
    ]

    @property
    def roles_display(self):
        held = [full for flag, full, _ in self.ROLES if getattr(self, flag)]
        return ", ".join(held) or "No role assigned"

    @property
    def can_monitor(self):
        """
        Who sees the compilation screens: admins, the SIO office and Group Leaders.
        Read-only — approving an unlock stays admin_required.
        """
        return self.is_staff or self.is_sio or self.is_gl

    @property
    def roles_short(self):
        """Same list, abbreviated — for table cells the full names don't fit."""
        return ", ".join(short for flag, _, short in self.ROLES if getattr(self, flag))


class MPRPeriod(models.Model):
    """One reporting month. Admin opens it; everyone fills against it."""

    MONTHS = [(i, calendar.month_name[i]) for i in range(1, 13)]

    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(choices=MONTHS)
    due_date = models.DateField()
    is_open = models.BooleanField(default=True)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [models.UniqueConstraint(fields=["year", "month"], name="unique_mpr_period")]

    def __str__(self):
        return f"{calendar.month_name[self.month]} {self.year}"


class MPREntry(models.Model):
    """
    One row in one MPR section, for one user in one month.

    All sections share this table: they overlap heavily and only a handful of
    fields are section-specific. `FIELDS` says which columns a section actually
    uses — forms and admin read it, so a new section is one dict entry.
    ponytail: single table, split a section out only if it grows real structure.
    """

    EVENT = "event"
    REVIEW = "review"
    TRAINING = "training"
    AWARD = "award"
    SIGNIFICANT = "significant"
    NEW_ACTIVITY = "new_activity"
    ENHANCEMENT = "enhancement"

    # Which report this row belongs to. A DIO files one district report; a Project
    # Leader files one report per project they lead. Someone holding both files both.
    DISTRICT = "district"
    PROJECT = "project"
    SCOPE_CHOICES = [(DISTRICT, "District report"), (PROJECT, "Project report")]

    KIND_CHOICES = [
        (EVENT, "Major events planned"),
        (REVIEW, "Review by Hon'ble Minister / Others"),
        (TRAINING, "Major training"),
        (AWARD, "Major awards"),
        (SIGNIFICANT, "Significant activities planned"),
        (NEW_ACTIVITY, "New activities planned"),
        (ENHANCEMENT, "Major enhancements"),
    ]
    # Project Leaders get these on top of the common sections; DIOs don't.
    PL_ONLY_KINDS = [ENHANCEMENT]
    # One row per report per month; Add opens the existing row instead.
    SINGLE_KINDS = [EVENT, SIGNIFICANT, NEW_ACTIVITY]

    # Column headings for the monitoring table, where the full labels don't fit.
    SHORT_LABELS = {
        EVENT: "Events",
        REVIEW: "Reviews",
        TRAINING: "Training",
        AWARD: "Awards",
        SIGNIFICANT: "Significant",
        NEW_ACTIVITY: "New",
        ENHANCEMENT: "Enhance.",
    }

    EVENT_CATEGORIES = [
        ("inauguration", "Inauguration"),
        ("launch", "Launch"),
        ("press", "Press coverage"),
        ("other", "Others"),
    ]
    AWARD_LEVELS = [
        ("international", "International"),
        ("national", "National"),
        ("state", "State"),
        ("district", "District"),
        ("local", "Local"),
    ]

    FIELDS = {
        # `project` isn't here: which project a row belongs to comes from the report
        # it was filed in, not from a dropdown the user has to get right.
        EVENT: ["event_category", "date", "description", "remarks"],
        REVIEW: ["description", "date", "suggestions", "remarks"],
        TRAINING: ["title", "date", "to_date", "participants", "target_user", "remarks"],
        AWARD: ["award_level", "title", "date", "description", "photo"],
        SIGNIFICANT: ["description"],
        NEW_ACTIVITY: ["description"],
        ENHANCEMENT: ["title", "description", "remarks"],
    }
    # Same column, different name depending on the section.
    LABELS = {
        REVIEW: {"date": "Date of review"},
        TRAINING: {
            "title": "Topic",
            "date": "From date",
            "to_date": "To date",
            "participants": "No. of participants",
            "target_user": "Target user",
        },
        AWARD: {"title": "Award title", "date": "Award date"},
        EVENT: {"date": "Event date", "event_category": "Event category"},
        SIGNIFICANT: {"description": "Brief description"},
        NEW_ACTIVITY: {"description": "Brief description"},
    }

    period = models.ForeignKey(MPRPeriod, on_delete=models.PROTECT, related_name="entries")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="mpr_entries")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default=PROJECT)

    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    remarks = models.TextField(blank=True)
    date = models.DateField(null=True, blank=True)
    to_date = models.DateField(null=True, blank=True)
    participants = models.PositiveIntegerField(null=True, blank=True)
    target_user = models.CharField(max_length=200, blank=True)
    suggestions = models.TextField(blank=True)
    event_category = models.CharField(max_length=20, choices=EVENT_CATEGORIES, blank=True)
    award_level = models.CharField(max_length=20, choices=AWARD_LEVELS, blank=True)
    # Set from the report the row was filed in, not by the user. Null on district rows.
    # PROTECT, like period and author: a filed entry names the project it reports on,
    # and deleting the project would leave the row behind belonging to nothing, quietly
    # changing every past report and export. A project with history isn't deletable.
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.PROTECT, related_name="mpr_entries"
    )
    photo = models.ImageField(upload_to="mpr/awards/", blank=True)

    class Meta:
        ordering = ["scope", "kind", "date", "id"]
        verbose_name_plural = "MPR entries"

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title or self.description[:40]}"

    @property
    def headline(self):
        return self.title or self.description or "(no description)"

    @classmethod
    def label(cls, kind, name):
        """Column heading for one field of one section — LABELS wins, else the field's own."""
        return capfirst(cls.LABELS.get(kind, {}).get(name) or cls._meta.get_field(name).verbose_name)

    def value(self, name):
        """The displayable value of one field (choice fields resolve to their label)."""
        display = getattr(self, f"get_{name}_display", None)
        return display() if display else getattr(self, name)

    def cells(self):
        """
        (label, value) for the fields this kind uses, minus the ones already shown
        as the headline or as a thumbnail. One generic row renderer for all 7 sections.
        """
        shown = {"photo", "title" if self.title else "description"}
        for name in self.FIELDS[self.kind]:
            if name in shown:
                continue
            value = self.value(name)
            if value in (None, ""):
                continue
            yield self.label(self.kind, name), value


class MPRLock(models.Model):
    """
    A user freezing their whole month. The row existing IS the lock, so an admin
    approving an unlock simply deletes it.
    ponytail: no history kept; add an audit table if "who unlocked what" ever matters.
    """

    period = models.ForeignKey(MPRPeriod, on_delete=models.CASCADE, related_name="locks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mpr_locks")
    locked_at = models.DateTimeField(auto_now_add=True)
    unlock_requested = models.BooleanField(default=False)
    unlock_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-locked_at"]
        constraints = [models.UniqueConstraint(fields=["period", "user"], name="unique_mpr_lock")]

    def __str__(self):
        return f"{self.user} locked {self.period}"


class ProjectParameter(models.Model):
    """
    A recurring figure a project reports every month. Admin adds/removes these on
    the project page; `order` is assigned there so new rows land at the bottom.

    ponytail: removal is a hard delete and takes its ParameterValues with it — the
    confirm page names how many months that is. Add an `is_active` flag only if a
    parameter needs retiring while its history stays visible.
    """

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="parameters")
    name = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["project", "name"], name="unique_project_parameter")]

    def __str__(self):
        return f"{self.project.name} — {self.name}"


class ParameterValue(models.Model):
    """The monthly numbers a PL enters for one ProjectParameter."""

    period = models.ForeignKey(MPRPeriod, on_delete=models.PROTECT, related_name="parameter_values")
    parameter = models.ForeignKey(ProjectParameter, on_delete=models.CASCADE, related_name="values")
    # ponytail: text, because parameters range from counts to "NA"/"₹ 2.4 Cr".
    # Switch to Decimal if exports need arithmetic on them.
    previous_month = models.CharField(max_length=100, blank=True)
    reporting_month = models.CharField(max_length=100, blank=True)
    cumulative = models.CharField("Cumulative since inception", max_length=100, blank=True)

    class Meta:
        ordering = ["parameter"]
        constraints = [models.UniqueConstraint(fields=["period", "parameter"], name="unique_parameter_value")]

    def __str__(self):
        return f"{self.parameter.name} @ {self.period}"


class SecurityEvent(models.Model):
    """
    One security-relevant thing that happened: a sign-in, a failure, a lockout, a
    role change. Written by accounts/security.py, never edited.

    actor/target link while the user exists; the *_label fields are what the log
    actually says. Two required cases break a bare FK — a deleted account leaves
    the row pointing at NULL, and a failed login can name a user that never
    existed, which is exactly what guessing looks like.
    """

    LOGIN_OK = "login_ok"
    LOGIN_FAIL = "login_fail"
    LOGOUT = "logout"
    LOCKED_OUT = "locked_out"
    LOCK_CLEARED = "lock_cleared"
    PASSWORD_CHANGED = "password_changed"
    ROLE_CHANGED = "role_changed"
    USER_CREATED = "user_created"
    USER_DISABLED = "user_disabled"
    USER_ENABLED = "user_enabled"
    USER_DELETED = "user_deleted"

    ACTIONS = [
        (LOGIN_OK, "Signed in"), (LOGIN_FAIL, "Sign-in failed"), (LOGOUT, "Signed out"),
        (LOCKED_OUT, "Locked out"), (LOCK_CLEARED, "Lock cleared"),
        (PASSWORD_CHANGED, "Password changed"), (ROLE_CHANGED, "Roles changed"),
        (USER_CREATED, "User created"), (USER_DISABLED, "User disabled"),
        (USER_ENABLED, "User re-enabled"), (USER_DELETED, "User deleted"),
    ]

    at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20, choices=ACTIONS)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="security_events")
    actor_label = models.CharField(max_length=150)
    target = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="security_events_about")
    target_label = models.CharField(max_length=150, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["-at"]), models.Index(fields=["actor_label"])]

    def __str__(self):
        return f"{self.actor_label} — {self.get_action_display()}"
