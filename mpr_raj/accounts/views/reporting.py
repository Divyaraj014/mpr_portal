"""Compilation for admin and SIO: filing status, one report per category, exports."""
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .. import exports
from .master import admin_required
from ..models import MPREntry, MPRLock, MPRPeriod, ParameterValue, User


# is_authenticated first: AnonymousUser carries is_staff but not our role flags.
monitor_required = user_passes_test(lambda u: u.is_authenticated and u.can_monitor)


def _pick_period(request):
    """Every report screen is 'one month at a time', chosen by ?period= and linkable."""
    periods = list(MPRPeriod.objects.all())
    period = next((p for p in periods if str(p.pk) == request.GET.get("period")),
                  periods[0] if periods else None)
    return periods, period


@monitor_required
def reports(request):
    """
    Compilation index: pick a month, then a report. One row per category with its size,
    so the SIO office can see where the month's data actually is before opening anything.
    """
    periods, period = _pick_period(request)
    return render(request, "accounts/reports.html", {
        "periods": periods,
        "period": period,
        "tables": exports.tables(period) if period else [],
        "locked": period.locks.count() if period else 0,
        "requests": period.locks.filter(unlock_requested=True).count() if period else 0,
        # "1 locked" means nothing without the denominator.
        "reporters": User.objects.filter(Q(is_pl=True) | Q(is_dio=True)).count(),
    })


def _column_layout(table):
    """
    (track list, min width) sized to what's actually in each column — the same clamp the
    xlsx writer uses. A three-column report then fits without scrolling sideways.

    Tracks are fixed pixels on purpose. Every row is its own grid, so `auto` and
    `max-content` resolve per row; and `ch` resolves against each element's own
    font-size, which is 12px in the header and 14px in the rows — either way the
    columns drift further out of line with each column.
    """
    px_per_char, cell_padding = 7.4, 14
    widths = [round(min(max([len(h)] + [len(r[i]) for r in table["rows"]]), 34) * px_per_char)
              + cell_padding
              for i, h in enumerate(table["headers"])]
    fixed = " ".join(f"{w}px" for w in widths[:-1])
    return f"{fixed} minmax({widths[-1]}px, 1fr)", f"{sum(widths)}px"


@monitor_required
def report_table(request, key):
    """One category, every row filed in it this month. Same block the exports write."""
    periods, period = _pick_period(request)
    table = next((t for t in exports.tables(period, only=key)), None) if period else None
    if period and table is None:
        raise Http404("Unknown report")
    cols, grid_width = _column_layout(table) if table else ("", "")
    return render(request, "accounts/report_table.html", {
        "periods": periods, "period": period, "table": table, "key": key,
        "cols": cols, "grid_width": grid_width,
    })


@monitor_required
def report_status(request):
    periods, period = _pick_period(request)
    ctx = {"periods": periods, "period": period, "kinds": []}
    if period:
        kinds = [(k, MPREntry.SHORT_LABELS[k]) for k, _ in MPREntry.KIND_CHOICES]
        counts = {(r["author"], r["kind"]): r["n"] for r in MPREntry.objects
                  .filter(period=period).values("author", "kind").annotate(n=Count("id"))}
        # A figure counts as entered once the reporting month column is filled in.
        figures = dict(ParameterValue.objects.filter(period=period)
                       .exclude(reporting_month="")
                       .values_list("parameter__project__leader")
                       .annotate(n=Count("id")))
        locks = {lock.user_id: lock for lock in
                 MPRLock.objects.filter(period=period).select_related("user")}
        rows = [{
            "user": u,
            "counts": [counts.get((u.id, k), 0) for k, _ in kinds],
            "total": sum(n for (author, _), n in counts.items() if author == u.id),
            "figures": figures.get(u.id, 0),
            "lock": locks.get(u.id),
        } for u in User.objects.filter(Q(is_pl=True) | Q(is_dio=True)).order_by("name", "username")]
        ctx |= {
            "kinds": kinds,
            "rows": rows,
            "locked": sum(1 for r in rows if r["lock"]),
            "requests": sum(1 for r in rows if r["lock"] and r["lock"].unlock_requested),
            # Driven by the section count, so adding one stays "a new dict entry".
            "cols": ("minmax(140px, 1.4fr) minmax(215px, auto) "
                     f"repeat({len(kinds)}, 80px) 66px"),
            "grid_width": f"{620 + 80 * len(kinds)}px",
        }
    return render(request, "accounts/report_status.html", ctx)


@monitor_required
def report_export(request, pk, fmt):
    """One month in one format, or one category of it via ?only=. Shaping lives in exports."""
    period = get_object_or_404(MPRPeriod, pk=pk)
    if fmt not in exports.WRITERS:
        raise Http404("Unknown export format")
    only = request.GET.get("only") or None
    tables = exports.tables(period, only)
    if only and not tables:
        raise Http404("Unknown report")
    try:
        content, content_type = exports.WRITERS[fmt](period, tables)
    except OSError as exc:
        # WeasyPrint needs Pango/Cairo from the OS; say so instead of a blank 500.
        return HttpResponse(
            f"PDF export needs the WeasyPrint system libraries on this server "
            f"(pango, cairo, gdk-pixbuf). Original error: {exc}",
            status=503, content_type="text/plain")
    name = f"MPR {period}" + (f" - {tables[0]['title']}" if only else "")
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}.{fmt}"'
    return response


@admin_required
def report_unlock(request, pk):
    lock = get_object_or_404(MPRLock, pk=pk)
    period_id = lock.period_id
    if request.method == "POST":
        lock.delete()  # the row is the lock, so removing it reopens the month
    return redirect(f"{reverse('report_status')}?period={period_id}")
