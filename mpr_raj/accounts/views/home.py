"""Signing in, the forced first-login password change, and the dashboard."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils import timezone

from ..forms import CaptchaAuthenticationForm
from ..models import MPRPeriod, SecurityEvent, User
from ..security import record
from .monthly import _lock, _my_reports


class CaptchaLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = CaptchaAuthenticationForm
    redirect_authenticated_user = True


class ForcedPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("dashboard")

    def get_form_class(self):
        # First login (temp password just typed at the login screen): no
        # "old password" field, per the design. Later changes require it.
        if self.request.user.must_change_password:
            return SetPasswordForm
        return super().get_form_class()

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        if user.must_change_password:
            # First successful password set = account activation (plan §2).
            user.must_change_password = False
            user.is_activated = True
            user.save(update_fields=["must_change_password", "is_activated"])
        record(SecurityEvent.PASSWORD_CHANGED, actor=user, request=self.request)
        return response


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@login_required
def settings(request):
    return render(request, "accounts/settings.html")


def _due_phrase(period):
    """The due date as the thing you actually need: 'Due in 9 days', '3 days overdue'."""
    days = (period.due_date - timezone.localdate()).days
    if days > 1:
        return f"Due in {days} days"
    if days == 1:
        return "Due tomorrow"
    if days == 0:
        return "Due today"
    return f"{-days} day{'' if days == -1 else 's'} overdue"


@login_required
def dashboard(request):
    """
    One block per thing the signed-in user can act on, and nothing else. Roles stack,
    so an admin who is also a DIO sees both their own report and the month's progress.
    """
    user = request.user
    period = MPRPeriod.objects.filter(is_open=True).first()
    ctx = {"period": period, "due_phrase": _due_phrase(period) if period else ""}

    if period and (user.is_pl or user.is_dio):
        ctx |= {
            "my_entries": period.entries.filter(author=user).count(),
            "my_lock": _lock(user, period),
            "split": len(_my_reports(user)) > 1,
        }
    if period and user.can_monitor:
        reporters = User.objects.filter(Q(is_pl=True) | Q(is_dio=True)).count()
        ctx |= {
            "reporters": reporters,
            "locked": period.locks.count(),
            "requests": period.locks.filter(unlock_requested=True).count(),
            "not_started": reporters - period.entries.values("author").distinct().count(),
        }
    if user.is_staff:
        # Accounts that were created but never signed in — invisible anywhere else.
        ctx["pending"] = User.objects.filter(is_activated=False, is_active=True).count()
    return render(request, "accounts/dashboard.html", ctx)
