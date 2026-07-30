"""
Filling a month. A month holds one report per thing the user owns — one for their
districts, one per project they lead — and every view here is scoped to request.user.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.forms import modelformset_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..forms import entry_form_class
from ..models import MPREntry, MPRLock, MPRPeriod, ParameterValue, Project




def _kinds(scope):
    """Sections in one report. The Project-Leader-only ones aren't part of a district report."""
    return [(k, label) for k, label in MPREntry.KIND_CHOICES
            if scope == MPREntry.PROJECT or k not in MPREntry.PL_ONLY_KINDS]


def _lock(user, period):
    return MPRLock.objects.filter(period=period, user=user).first()


def _back(user, period, project):
    """Where a form returns to: the report the row belongs to, or the month page."""
    if len(_my_reports(user)) < 2:
        return redirect("mpr_month", pk=period.pk)   # one report, and it lives there
    if project:
        return redirect("mpr_project_report", pk=period.pk, project_pk=project.pk)
    return redirect("mpr_district_report", pk=period.pk)


def _editable(user, period):
    """The single answer to "can this person still change this month?" — every view asks here."""
    return period.is_open and not _lock(user, period)


@login_required
def mpr_list(request):
    periods = MPRPeriod.objects.annotate(
        mine=Count("entries", filter=Q(entries__author=request.user)))
    return render(request, "accounts/mpr_list.html", {"periods": periods})


def _my_reports(user):
    """
    Every report this user owes, as (scope, project). A DIO files one district report;
    a Project Leader files one per project, because a single merged set of sections
    can't say which project an event or training belonged to.
    """
    reports = [(MPREntry.DISTRICT, None)] if user.is_dio else []
    if user.is_pl:
        reports += [(MPREntry.PROJECT, p) for p in user.projects.all()]
    return reports


def _group(user, period, entries, scope, project):
    """One report: its sections, what it covers, how much is in it, and where it lives."""
    rows = [e for e in entries if e.scope == scope and e.project_id == (project.pk if project else None)]
    if project:
        url = reverse("mpr_project_report", args=[period.pk, project.pk])
        sub = f"{project.get_category_display()} project · {project.prism_id}"
    else:
        url = reverse("mpr_district_report", args=[period.pk])
        held = ", ".join(d.name for d in user.districts.all())
        sub = held or "No district assigned to you yet."
    return {
        "scope": scope,
        "project": project,
        "label": project.name if project else dict(MPREntry.SCOPE_CHOICES)[scope],
        "sub": sub,
        "url": url,
        "sections": [
            {"kind": kind, "label": label, "rows": [e for e in rows if e.kind == kind]}
            for kind, label in _kinds(scope)
        ],
        # A project report carries its own figures table; a district report has none.
        "projects": [project] if project else [],
        "count": len(rows),
    }


@login_required
def mpr_month(request, pk):
    """
    The month. One report to fill means filling it here; several means picking one
    first — every section of every report on one page is what made this confusing.
    """
    period = get_object_or_404(MPRPeriod, pk=pk)
    entries = list(period.entries.filter(author=request.user).select_related("project"))
    groups = [_group(request.user, period, entries, s, p) for s, p in _my_reports(request.user)]
    return render(request, "accounts/mpr_month.html", {
        "period": period,
        "groups": groups,
        "split": len(groups) > 1,
        "lock": _lock(request.user, period),
        "editable": _editable(request.user, period),
        "filled": len(entries),
    })


@login_required
def mpr_report(request, pk, scope, project_pk=None):
    """One report on its own page. Only reachable for a report you actually owe."""
    period = get_object_or_404(MPRPeriod, pk=pk)
    project = get_object_or_404(Project, pk=project_pk, leader=request.user) if project_pk else None
    if (scope, project) not in _my_reports(request.user):
        raise Http404("That report isn't yours to fill")
    entries = list(period.entries.filter(author=request.user).select_related("project"))
    return render(request, "accounts/mpr_report.html", {
        "period": period,
        "g": _group(request.user, period, entries, scope, project),
        "lock": _lock(request.user, period),
        "editable": _editable(request.user, period),
    })


@login_required
def mpr_lock(request, pk):
    """GET states what locking costs; POST does it. ponytail: no JS confirm to dodge."""
    period = get_object_or_404(MPRPeriod, pk=pk)
    if not _editable(request.user, period):
        return redirect("mpr_month", pk=period.pk)
    if request.method == "POST":
        MPRLock.objects.create(period=period, user=request.user)
        return redirect("mpr_month", pk=period.pk)
    return render(request, "accounts/mpr_lock_confirm.html", {
        "period": period,
        "filled": period.entries.filter(author=request.user).count(),
    })


@login_required
def mpr_unlock_request(request, pk):
    lock = get_object_or_404(MPRLock, period_id=pk, user=request.user)
    if request.method == "POST":
        lock.unlock_requested = True
        lock.unlock_reason = request.POST.get("reason", "").strip()
        lock.save(update_fields=["unlock_requested", "unlock_reason"])
    return redirect("mpr_month", pk=pk)


@login_required
def mpr_entry_form(request, period_pk, kind, pk=None):
    period = get_object_or_404(MPRPeriod, pk=period_pk)
    if kind not in MPREntry.FIELDS:
        raise Http404("Unknown section")
    if not _editable(request.user, period):
        return redirect("mpr_month", pk=period.pk)
    # Editing is limited to the signed-in user's own rows.
    entry = (get_object_or_404(MPREntry, pk=pk, author=request.user, period=period) if pk
             else MPREntry(period=period, author=request.user, kind=kind))
    if not pk:
        # New row: the query string says which report it belongs to. Users who owe
        # only one never see the question, and nobody can file into a report they
        # don't owe — the pair has to be one of _my_reports().
        reports = _my_reports(request.user)
        only = reports[0] if len(reports) == 1 else (None, None)
        wanted = request.GET.get("project")
        entry.scope = request.GET.get("scope") or only[0]
        # A named project must be one of theirs. Don't fall back to their own project
        # when the name doesn't match — that would file the row somewhere they didn't ask.
        entry.project = (next((p for _, p in reports if p and str(p.pk) == wanted), None)
                         if wanted else only[1])
        if (entry.scope, entry.project) not in reports or kind not in dict(_kinds(entry.scope)):
            raise Http404("That section isn't part of this report")
    form = entry_form_class(kind)(request.POST or None, request.FILES or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        form.save()
        return _back(request.user, period, entry.project)
    return render(request, "accounts/mpr_entry_form.html", {
        "form": form, "period": period, "entry": entry if pk else None,
        "label": dict(MPREntry.KIND_CHOICES)[kind],
        "scope_label": entry.project.name if entry.project else dict(MPREntry.SCOPE_CHOICES)[entry.scope],
    })


@login_required
def mpr_entry_delete(request, pk):
    entry = get_object_or_404(MPREntry, pk=pk, author=request.user)
    if request.method == "POST" and _editable(request.user, entry.period):
        entry.delete()
    return _back(request.user, entry.period, entry.project)


def _previous_period(period):
    return MPRPeriod.objects.filter(
        Q(year__lt=period.year) | Q(year=period.year, month__lt=period.month)
    ).first()  # ordering is newest first


@login_required
def mpr_parameters(request, period_pk, project_pk):
    period = get_object_or_404(MPRPeriod, pk=period_pk)
    project = get_object_or_404(Project, pk=project_pk, leader=request.user)

    # Carry last month's reporting figure into "previous month" so it isn't retyped.
    prev = _previous_period(period)
    carried = dict(ParameterValue.objects.filter(
        period=prev, parameter__project=project).values_list("parameter_id", "reporting_month"))
    for param in project.parameters.all():
        ParameterValue.objects.get_or_create(
            period=period, parameter=param,
            defaults={"previous_month": carried.get(param.id, "")})

    values = ParameterValue.objects.filter(
        period=period, parameter__project=project).select_related("parameter")
    FormSet = modelformset_factory(
        ParameterValue, fields=["previous_month", "reporting_month", "cumulative"], extra=0)
    editable = _editable(request.user, period)
    formset = FormSet(request.POST or None, queryset=values)
    if not editable:
        # Read-only month: disabled fields also make Django ignore anything POSTed.
        for form in formset:
            for field in form.fields.values():
                field.disabled = True
    if request.method == "POST" and editable and formset.is_valid():
        formset.save()
        return _back(request.user, period, project)
    return render(request, "accounts/mpr_parameters.html",
                  {"formset": formset, "period": period, "project": project,
                   "editable": editable})
