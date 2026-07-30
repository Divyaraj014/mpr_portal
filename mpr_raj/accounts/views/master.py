"""Admin-managed master data: users, districts, projects (and their monthly
parameters), and the reporting months themselves."""
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse

from ..forms import DistrictForm, PeriodForm, ProjectForm, ProjectParameterForm, UserForm
from ..models import District, MPRPeriod, Project, ProjectParameter, User

admin_required = user_passes_test(lambda u: u.is_staff)

@admin_required
def user_list(request):
    return render(request, "accounts/user_list.html", {"users": User.objects.order_by("username")})


@admin_required
def user_form(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
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
    # Entries and districts are PROTECT — they block the delete rather than follow
    # the user out. Projects are SET_NULL, so those really do just come loose.
    entries = user.mpr_entries.count()
    if entries:
        warnings.append(f"{entries} monthly report {'entry' if entries == 1 else 'entries'} "
                        "filed by this user — deletion is blocked until they are removed.")
    districts = [d.name for d in user.districts.all()]
    if districts:
        warnings.append("Officer for " + ", ".join(districts) +
                        " — reassign the district first.")
    projects = [p.name for p in user.projects.all()]
    if projects:
        warnings.append("Left unassigned: " + ", ".join(projects) + ".")
    return _confirm_delete(request, user, "user_list",
                           f"user “{user.name or user.username}”", warnings)


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
    ctx = {"form": form, "title": "Edit district" if district else "Add district",
           "list_url": "district_list", "back_label": "Back to districts"}
    if district:
        ctx["delete_url"] = reverse("district_delete", args=[district.pk])
    return render(request, "accounts/master_form.html", ctx)


def _confirm_delete(request, obj, back, label, warnings=()):
    """`back` is anything redirect() takes — a URL name, or a path when it needs args."""
    blocked = None
    if request.method == "POST":
        try:
            obj.delete()
            return redirect(back)
        except ProtectedError as exc:
            # A PROTECT row still points here (a district's officer, an author's
            # filed entries). Name what holds it instead of returning a 500.
            kinds = sorted({str(type(o)._meta.verbose_name_plural) for o in exc.protected_objects})
            blocked = "Can’t delete — still referenced by " + ", ".join(kinds) + "."
    return render(request, "accounts/confirm_delete.html",
                  {"obj_label": label, "back_url": resolve_url(back),
                   "warnings": warnings, "blocked": blocked})


def _assigned_warning(user):
    if not user:
        return []
    return [f"Currently assigned to {user.name or user.username} — they’ll be unassigned."]


@admin_required
def district_delete(request, pk):
    d = get_object_or_404(District, pk=pk)
    return _confirm_delete(request, d, "district_list", f"district “{d.name}”",
                           _assigned_warning(d.officer))


@admin_required
def period_list(request):
    """Reporting months: due dates and whether each still accepts data."""
    periods = MPRPeriod.objects.annotate(filed=Count("entries"))
    return render(request, "accounts/period_list.html", {"periods": periods})


@admin_required
def period_form(request, pk=None):
    period = get_object_or_404(MPRPeriod, pk=pk) if pk else None
    form = PeriodForm(request.POST or None, instance=period)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("period_list")
    return render(request, "accounts/master_form.html",
                  {"form": form, "title": str(period) if period else "Open a reporting month",
                   "list_url": "period_list", "back_label": "Back to reporting months"})


@admin_required
def project_list(request):
    projects = Project.objects.select_related("leader")
    return render(request, "accounts/project_list.html", {"projects": projects})


@admin_required
def project_form(request, pk=None):
    project = get_object_or_404(Project, pk=pk) if pk else None
    # Two forms, one page: the parameter box posts back here and names its button,
    # so only the form that was actually submitted gets bound.
    adding = "add_parameter" in request.POST
    form = ProjectForm(None if adding else request.POST or None, instance=project)
    param_form = ProjectParameterForm(request.POST if adding else None,
                                      project=project) if project else None
    if request.method == "POST":
        if adding and param_form.is_valid():
            param_form.save()
            return redirect("project_edit", pk=project.pk)
        if not adding and form.is_valid():
            form.save()
            return redirect("project_list")
    ctx = {"form": form, "title": "Edit project" if project else "Add project",
           "list_url": "project_list", "back_label": "Back to projects",
           "param_form": param_form}
    if project:
        ctx["delete_url"] = reverse("project_delete", args=[project.pk])
        ctx["parameters"] = project.parameters.annotate(months=Count("values"))
    return render(request, "accounts/master_form.html", ctx)


@admin_required
def project_delete(request, pk):
    p = get_object_or_404(Project, pk=pk)
    return _confirm_delete(request, p, "project_list", f"project “{p.name}”",
                           _assigned_warning(p.leader))


@admin_required
def project_parameter_delete(request, pk):
    param = get_object_or_404(ProjectParameter, pk=pk)
    months = param.values.count()
    # Removing a parameter takes every month of figures filed against it, which
    # silently changes past reports and exports. Say so before, not after.
    warnings = [f"Figures filed for {months} month{'' if months == 1 else 's'} go with it — "
                "past reports and exports will change."] if months else []
    return _confirm_delete(request, param, reverse("project_edit", args=[param.project_id]),
                           f"parameter “{param.name}”", warnings)
