"""The admin-only security log: list, filter, and the lockout override."""
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from ..models import SecurityEvent
from ..security import record
from .master import admin_required

PER_PAGE = 100


def _filtered(request):
    """(queryset, kept, filters) — shared with the text export so the two can't drift."""
    events = SecurityEvent.objects.select_related("actor", "target")

    user = request.GET.get("user", "").strip()
    action = request.GET.get("action", "")
    if user:
        # actor_label, not the FK: a failed sign-in can name a user that never existed.
        events = events.filter(actor_label__icontains=user)
    if action in dict(SecurityEvent.ACTIONS):
        events = events.filter(action=action)

    kept = {k: v for k, v in (("user", user), ("action", action)) if v}
    filters = [
        {"name": "user", "label": "User", "blank": "Any login ID", "selected": user,
         "type": "text", "options": []},
        {"name": "action", "label": "Event", "blank": "Any event", "selected": action,
         "options": SecurityEvent.ACTIONS},
    ]
    return events, kept, filters


def _locked_out():
    """Currently locked username+IP pairs, newest first."""
    from axes.models import AccessAttempt

    return AccessAttempt.objects.order_by("-attempt_time")[:50]


@admin_required
def security_log(request):
    """
    Unlike the master lists this one paginates: retention is keep-everything and
    every sign-in adds a row, so it grows without bound.
    """
    events, kept, filters = _filtered(request)
    page = Paginator(events, PER_PAGE).get_page(request.GET.get("page"))

    return render(request, "accounts/security_log.html", {
        "events": page, "page": page,
        # Filters ride along in the page links so a filtered view stays linkable.
        "qs": ("&" + urlencode(kept)) if kept else "",
        "filters": filters, "filtered": bool(kept),
        "showing": page.paginator.count, "total": SecurityEvent.objects.count(),
        "clear_url": "security_log", "locked": _locked_out(),
    })


@admin_required
def security_unlock(request):
    """
    Clear one lockout now. The cool-off would expire on its own, but a DIO locked
    out at 9pm on the 5th cannot wait for it.
    """
    if request.method != "POST":
        return redirect("security_log")
    username = request.POST.get("username", "").strip()
    if username:
        from axes.utils import reset

        reset(username=username)
        record(SecurityEvent.LOCK_CLEARED, actor=request.user, target_label=username,
               request=request)
    return redirect("security_log")


@admin_required
def security_export(request):
    """
    The filtered log as plain text. Respects the filters, ignores the pagination —
    downloading page 1 of a filtered view would look like the whole story.

    ponytail: builds in memory. Fine for years at this volume; swap to
    StreamingHttpResponse if it ever gets slow.
    """
    events, kept, _ = _filtered(request)
    events = list(events)
    stamp = timezone.localtime()

    shown = "; ".join([
        f'user contains "{kept["user"]}"' if kept.get("user") else "user: all",
        f'action: {kept["action"]}' if kept.get("action") else "action: all",
    ])
    lines = [
        "NIC Rajasthan — MPR Portal security log",
        f"Generated   {stamp:%Y-%m-%d %H:%M} IST by {request.user.username}",
        f"Filter      {shown}",
        # No row cap. If one is ever added it must be stated here — a silent
        # truncation in a security export is the worst available failure.
        f"Events      {('1–' + str(len(events))) if events else '0'} of {len(events)}",
        "",
        f"{'WHEN':<18}{'EVENT':<18}{'USER':<20}{'TARGET':<20}{'IP':<16}DETAIL",
        "-" * 110,
    ]
    for e in events:
        lines.append(
            f"{timezone.localtime(e.at):%Y-%m-%d %H:%M}  "
            f"{e.get_action_display():<18}{e.actor_label:<20}"
            f"{e.target_label or '-':<20}{e.ip or '-':<16}{e.detail}".rstrip()
        )

    response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="security-log-{stamp:%Y-%m-%d}.txt"'
    return response
