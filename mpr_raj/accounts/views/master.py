"""Admin-managed master data: users, districts, projects (and their monthly
parameters), and the reporting months themselves."""

from urllib.parse import urlencode

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, ProtectedError
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse

from ..forms import DistrictForm, PeriodForm, ProjectForm, ProjectParameterForm, UserForm
from ..models import (Department, District, MPRPeriod, PlaceOfPosting, Project, ProjectParameter,
                      SecurityEvent, User)
from ..security import record

admin_required = user_passes_test(lambda u: u.is_staff)

# Role flags, for the security log's before/after on a user edit.
ROLE_FIELDS = ["is_staff", "is_sio", "is_gl", "is_pl", "is_dio"]


def _role_detail(form):
    """"is_staff: No → Yes" for each role the save changed. Django computes the diff."""
    def word(value):
        return "Yes" if value else "No"

    return ", ".join(f"{f}: {word(form.initial.get(f))} → {word(form.cleaned_data.get(f))}"
                     for f in ROLE_FIELDS if f in form.changed_data)

# Which column each sort key orders by, plus the tie-breaker that keeps equal rows
# in a stable order. Roles has no single column, so it groups by seniority — the
# same order the flags are listed in User.ROLES.
# Lower() on the text columns: Postgres sorts by byte value here, which files every
# lowercase name after every uppercase one — "e-Procurement" landing below
# "ShalaDarpan" reads as broken to anyone scanning alphabetically.
USER_SORTS = {
    "username": ["username"],
    "name": [Lower("name"), "username"],
    "designation": [Lower("designation__name"), "username"],
    "place": [Lower("place_of_posting__name"), "username"],
    "roles": [f"-{flag}" for flag, _, _ in User.ROLES] + ["username"],
    "status": ["is_active", "is_activated", "username"],
}
USER_COLUMNS = [
    ("username", "Login ID"),
    ("name", "Name"),
    ("designation", "Designation"),
    ("place", "Place of posting"),
    ("roles", "Roles"),
    ("status", "Status"),
]
STATUS_FILTERS = {
    "active": {"is_active": True, "is_activated": True},
    "pending": {"is_active": True, "is_activated": False},
    "disabled": {"is_active": False},
}

PROJECT_SORTS = {
    "code": ["code"],
    "name": [Lower("name"), "code"],
    "prism": ["prism_id", "code"],
    "category": ["category", Lower("name")],
    "leader": [Lower("leader__name"), "leader__username", "code"],
}
PROJECT_COLUMNS = [
    ("code", "Project ID"),
    ("name", "Name"),
    ("prism", "PRISM ID"),
    ("category", "Category"),
    ("leader", "Assigned employee"),
]


def _flip(field):
    """Reverse one order_by term, which may be a "-name" string or a Lower() call."""
    if hasattr(field, "desc"):
        return field.desc()
    return field[1:] if field.startswith("-") else f"-{field}"


def _ordering(request, sorts, labels, kept, default):
    """
    Read ?sort= and return (order_by fields, header links). Shared by the user and
    project lists — same table, same behaviour: click a heading to sort by it,
    click it again to reverse, and the active filters ride along in every link.
    """
    sort = request.GET.get("sort", default)
    key, desc = sort.lstrip("-"), sort.startswith("-")
    if key not in sorts:
        key, desc = default, False
    # Only the leading field flips; the tie-breaker stays put.
    fields = sorts[key]
    # ponytail: Postgres puts NULLs last ascending, first descending, so rows
    # missing the sorted value bunch at one end. Reach for nulls_last only if that
    # actually bothers anyone.
    order = [_flip(fields[0]) if desc else fields[0], *fields[1:]]
    columns = [
        {
            "label": label,
            # Clicking the sorted column reverses it; clicking any other starts ascending.
            "url": "?" + urlencode({**kept, "sort": f"-{col}" if col == key and not desc else col}),
            "arrow": ("▼" if desc else "▲") if col == key else "",
        }
        for col, label in labels
    ]
    return order, columns


@admin_required
def user_list(request):
    """
    Filter and sort in the URL, so a filtered list is a link an admin can bookmark
    or paste to a colleague. Everything is done in the query — no JS table library,
    and no pagination until the roster outgrows one page.
    """
    users = User.objects.select_related("designation", "place_of_posting")

    role = request.GET.get("role", "")
    place = request.GET.get("place", "")
    status = request.GET.get("status", "")
    if any(role == flag for flag, _, _ in User.ROLES):
        users = users.filter(**{role: True})
    if place.isdigit():
        users = users.filter(place_of_posting=place)
    if status in STATUS_FILTERS:
        users = users.filter(**STATUS_FILTERS[status])

    kept = {k: v for k, v in (("role", role), ("place", place), ("status", status)) if v}
    order, columns = _ordering(request, USER_SORTS, USER_COLUMNS, kept, "username")
    users = users.order_by(*order)

    return render(request, "accounts/user_list.html", {
        "users": users,
        "columns": columns,
        "filters": [
            {
                "name": "role",
                "label": "Role",
                "blank": "Any role",
                "selected": role,
                "options": [(flag, full) for flag, full, _ in User.ROLES],
            },
            {
                "name": "place",
                "label": "Place of posting",
                "blank": "Anywhere",
                "selected": place,
                "options": PlaceOfPosting.objects.values_list("pk", "name"),
            },
            {
                "name": "status",
                "label": "Status",
                "blank": "Any status",
                "selected": status,
                "options": [
                    ("active", "Active"),
                    ("pending", "Pending first sign-in"),
                    ("disabled", "Disabled"),
                ],
            },
        ],
        "filtered": bool(kept),
        "showing": len(users),
        "total": User.objects.count(),
        "clear_url": "user_list",
    })


@admin_required
def user_form(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        creating = user is None
        roles = _role_detail(form)          # read before save(), while initial still holds
        activity = "is_active" in form.changed_data
        saved = form.save()
        if creating:
            record(SecurityEvent.USER_CREATED, actor=request.user, target=saved, request=request)
        else:
            if roles:
                record(SecurityEvent.ROLE_CHANGED, actor=request.user, target=saved,
                       request=request, detail=roles)
            if activity:
                record(SecurityEvent.USER_ENABLED if saved.is_active else SecurityEvent.USER_DISABLED,
                       actor=request.user, target=saved, request=request)
        return redirect("user_list")
    ctx = {"form": form, "edit_user": user}
    if user and user != request.user:  # no self-deletion, so no link either
        ctx["delete_url"] = reverse("user_delete", args=[user.pk])
    return render(request, "accounts/user_form.html", ctx)


@admin_required
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        # An admin deleting their own account would lock themselves out mid-request.
        return redirect("user_list")
    warnings = []
    # Only entries are PROTECT — they block the delete rather than follow the user
    # out. Districts and projects are SET_NULL, so those really do just come loose.
    entries = user.mpr_entries.count()
    if entries:
        warnings.append(f"{entries} monthly report {'entry' if entries == 1 else 'entries'} "
                        "filed by this user — deletion is blocked until they are removed.")
    districts = [d.name for d in user.districts.all()]
    if districts:
        warnings.append("Left without an officer: " + ", ".join(districts) +
                        " — nobody files their MPR until reassigned.")
    projects = [p.name for p in user.projects.all()]
    if projects:
        warnings.append("Left unassigned: " + ", ".join(projects) + ".")
    gone = user.username        # captured now; the row is unreadable afterwards
    return _confirm_delete(request, user, "user_list", f"user “{user.name or user.username}”", warnings,
                           on_deleted=lambda: record(SecurityEvent.USER_DELETED, actor=request.user,
                                                     target_label=gone, request=request))


@admin_required
def district_list(request):
    districts = District.objects.select_related("officer")
    return render(request, "accounts/district_list.html", {"districts": districts})


@admin_required
def district_form(request, pk=None):
    district = get_object_or_404(District, pk=pk) if pk else None
    form = DistrictForm(request.POST or None, instance=district)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("district_list")
    ctx = {
        "form": form,
        "title": "Edit district" if district else "Add district",
        "list_url": "district_list",
        "back_label": "Back to districts",
    }
    if district:
        ctx["delete_url"] = reverse("district_delete", args=[district.pk])
    return render(request, "accounts/master_form.html", ctx)


def _confirm_delete(request, obj, back, label, warnings=(), on_deleted=None):
    """
    `back` is anything redirect() takes — a URL name, or a path when it needs args.
    `on_deleted` fires only after the delete actually succeeds; shared by every
    master delete, so only the caller knows whether the row is worth logging.
    """
    blocked = None
    if request.method == "POST":
        try:
            obj.delete()
            if on_deleted:
                on_deleted()
            return redirect(back)
        except ProtectedError as exc:
            # A PROTECT row still points here (a district's officer, an author's
            # filed entries). Name what holds it instead of returning a 500.
            kinds = sorted({str(type(o)._meta.verbose_name_plural) for o in exc.protected_objects})
            blocked = "Can’t delete — still referenced by " + ", ".join(kinds) + "."
    return render(request, "accounts/confirm_delete.html", {
        "obj_label": label, "back_url": resolve_url(back),
        "warnings": warnings, "blocked": blocked,
    })


def _assigned_warning(user):
    if not user:
        return []
    return [f"Currently assigned to {user.name or user.username} — they’ll be unassigned."]


@admin_required
def district_delete(request, pk):
    d = get_object_or_404(District, pk=pk)
    return _confirm_delete(request, d, "district_list", f"district “{d.name}”", _assigned_warning(d.officer))


@admin_required
def period_list(request):
    """Reporting months: due dates and whether each still accepts data."""
    # Explicit: Meta.ordering is dropped on GROUP BY queries.
    periods = MPRPeriod.objects.annotate(filed=Count("entries")).order_by("-year", "-month")
    return render(request, "accounts/period_list.html", {"periods": periods})


@admin_required
def period_form(request, pk=None):
    period = get_object_or_404(MPRPeriod, pk=pk) if pk else None
    form = PeriodForm(request.POST or None, instance=period)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("period_list")
    return render(request, "accounts/master_form.html", {
        "form": form,
        "title": str(period) if period else "Open a reporting month",
        "list_url": "period_list",
        "back_label": "Back to reporting months",
    })


@admin_required
def project_list(request):
    """Same filter-and-sort-in-the-URL treatment as the user list."""
    projects = Project.objects.select_related("leader", "department")

    category = request.GET.get("category", "")
    department = request.GET.get("department", "")
    leader = request.GET.get("leader", "")
    if category in dict(Project.CATEGORY_CHOICES):
        projects = projects.filter(category=category)
    if department.isdigit():
        projects = projects.filter(department=department)
    # Unassigned is the one worth finding: a project with no leader is a project
    # nobody files an MPR for.
    if leader in ("assigned", "unassigned"):
        projects = projects.filter(leader__isnull=leader == "unassigned")

    kept = {k: v for k, v in (("category", category), ("department", department), ("leader", leader)) if v}
    order, columns = _ordering(request, PROJECT_SORTS, PROJECT_COLUMNS, kept, "code")
    projects = projects.order_by(*order)

    return render(request, "accounts/project_list.html", {
        "projects": projects,
        "columns": columns,
        "filters": [
            {
                "name": "category",
                "label": "Category",
                "blank": "Any category",
                "selected": category,
                "options": Project.CATEGORY_CHOICES,
            },
            {
                "name": "department",
                "label": "Department",
                "blank": "Any department",
                "selected": department,
                "options": Department.objects.values_list("pk", "name"),
            },
            {
                "name": "leader",
                "label": "Project Leader",
                "blank": "Anyone",
                "selected": leader,
                "options": [("assigned", "Assigned"), ("unassigned", "Not assigned")],
            },
        ],
        "filtered": bool(kept),
        "showing": len(projects),
        "total": Project.objects.count(),
        "clear_url": "project_list",
    })


@admin_required
def project_form(request, pk=None):
    project = get_object_or_404(Project, pk=pk) if pk else None
    # Two forms, one page: the parameter box posts back here and names its button,
    # so only the form that was actually submitted gets bound.
    adding = "add_parameter" in request.POST
    form = ProjectForm(None if adding else request.POST or None, instance=project)
    param_form = ProjectParameterForm(request.POST if adding else None, project=project) if project else None
    if request.method == "POST":
        if adding and param_form.is_valid():
            param_form.save()
            return redirect("project_edit", pk=project.pk)
        if not adding and form.is_valid():
            form.save()
            return redirect("project_list")
    ctx = {
        "form": form,
        "title": "Edit project" if project else "Add project",
        # The code is assigned by Project.save(), so it's shown, not edited.
        "subtitle": f"Project ID {project.code}" if project else "",
        "list_url": "project_list",
        "back_label": "Back to projects",
        "param_form": param_form,
    }
    if project:
        ctx["delete_url"] = reverse("project_delete", args=[project.pk])
        ctx["parameters"] = project.parameters.annotate(months=Count("values"))
    return render(request, "accounts/master_form.html", ctx)


@admin_required
def project_delete(request, pk):
    p = get_object_or_404(Project, pk=pk)
    warnings = _assigned_warning(p.leader)
    # Entries and parameters are PROTECT — they keep the project (and their own
    # history) alive rather than following it out. Say so before the admin clicks.
    entries = p.mpr_entries.count()
    if entries:
        warnings.append(
            f"{entries} monthly report {'entry' if entries == 1 else 'entries'} "
            "filed against this project — deletion is blocked so the "
            "reported data is kept."
        )
    return _confirm_delete(request, p, "project_list", f"project “{p.name}”", warnings)


@admin_required
def project_parameter_delete(request, pk):
    param = get_object_or_404(ProjectParameter, pk=pk)
    months = param.values.count()
    # Removing a parameter takes every month of figures filed against it, which
    # silently changes past reports and exports. Say so before, not after.
    warnings = (
        [
            f"Figures filed for {months} month{'' if months == 1 else 's'} go with it — "
            "past reports and exports will change."
        ]
        if months
        else []
    )
    return _confirm_delete(
        request,
        param,
        reverse("project_edit", args=[param.project_id]),
        f"parameter “{param.name}”",
        warnings,
    )
