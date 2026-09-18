# Security Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record security-relevant events (sign-ins, failures, lockouts, role and account changes), show them on an admin-only screen with filters, and export them as plain text.

**Architecture:** One `SecurityEvent` model. Authentication events arrive via Django's auth signals plus axes's lockout signal; role, account and password events are recorded explicitly from the views where `request.user` is available. `django-axes` provides lockout enforcement only — the viewing, filtering and export are ours.

**Tech Stack:** Django 6.0, PostgreSQL, `django-axes` 8.3.1, uv, Django's test runner, ruff (lint only — there is no formatter, see Global Constraints).

**Spec:** `docs/superpowers/specs/2026-09-18-security-log-design.md` (commit `63a6154`)

## Global Constraints

- All commands run from `mpr_raj/` (the inner directory holding `manage.py`) unless stated otherwise. Tests: `uv run python manage.py test`.
- Lint from the repo root: `uv run ruff check .` — must pass before every commit.
- **There is no auto-formatter.** Code is fill-wrapped by hand to a 110-column limit. Do **not** run `ruff format`. Do not explode short collections one-item-per-line.
- Quote style: existing files vary. Match the file you are editing; `settings.py` uses single quotes, everything else uses double.
- Python 3.12. Django 6.0. `django-axes >= 8.3.1`.
- Lockout keys on the username and IP **combined** (the pair), never either alone.
- Readership is `is_staff` only, enforced with the existing `admin_required` decorator from `accounts/views/master.py`.
- Actor = who performed the action. Target = who it was done to. See the spec's table; easy to implement backwards.
- The baseline suite is **78 tests, all passing**. Every task must leave it at 78+ passing.

---

### Task 1: Install and configure django-axes

Done first deliberately: axes is the only change that can break the existing 78 tests, and that risk should surface before anything is built on top of it.

**Files:**
- Modify: `pyproject.toml`
- Modify: `mpr_raj/mpr_raj/settings.py`
- Modify: `mpr_raj/.env.example`
- Test: `mpr_raj/accounts/tests/test_security.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: axes installed and enforcing; `axes.helpers.get_client_ip_address(request)` available to Task 3; `AXES_ENABLED` false during test runs.

- [ ] **Step 1: Add the dependency**

From the repo root:

```bash
uv add "django-axes>=8.3.1"
```

- [ ] **Step 2: Confirm the existing suite still passes before configuring anything**

Run: `cd mpr_raj && uv run python manage.py test`
Expected: `Ran 78 tests` / `OK`. Installing the package without wiring it up must change nothing.

- [ ] **Step 3: Wire axes into settings**

In `mpr_raj/mpr_raj/settings.py`, add `import sys` and `from datetime import timedelta` beside the existing imports at the top. Add `'axes'` to the end of `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    'accounts',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'axes',
]
```

Add the middleware as the **last** entry in `MIDDLEWARE`:

```python
    'accounts.middleware.ForcePasswordChangeMiddleware',
    'axes.middleware.AxesMiddleware',
]
```

Add this block immediately after `AUTH_PASSWORD_VALIDATORS`:

```python
# Lockout. Axes only enforces; accounts/security.py records what it does.
# All three of INSTALLED_APPS, AUTHENTICATION_BACKENDS and the middleware are
# required — miss one and enforcement silently does nothing.

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# The nested list locks the PAIR. Username alone lets anyone lock out a known
# DIO on purpose; IP alone means one typist locks out a whole NAT'd district office.
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_FAILURE_LIMIT = env.int('AXES_FAILURE_LIMIT', default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int('AXES_COOLOFF_MINUTES', default=30))
AXES_RESET_ON_SUCCESS = True

# Tests drive the login view directly and would lock one another out. The
# lockout tests re-enable this with @override_settings.
AXES_ENABLED = 'test' not in sys.argv
```

- [ ] **Step 4: Add the new env vars to the example file**

Append to `mpr_raj/.env.example`:

```
# Lockout thresholds. Cool-off is in minutes; django-environ has no duration type.
AXES_FAILURE_LIMIT=5
AXES_COOLOFF_MINUTES=30
```

- [ ] **Step 5: Migrate and re-run the full suite**

Run:
```bash
cd mpr_raj && uv run python manage.py migrate && uv run python manage.py test
```
Expected: axes migrations apply; `Ran 78 tests` / `OK`.

If anything fails here, stop and report rather than working around it — this is exactly the risk the task exists to surface.

- [ ] **Step 6: Write the lockout test**

Create `mpr_raj/accounts/tests/test_security.py`:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from ..captcha import SESSION_KEY

User = get_user_model()


class LockoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dio.kota", password="Right@12345",
                                             must_change_password=False)

    def solve_captcha(self):
        self.client.get(reverse("captcha_image"))
        return self.client.session[SESSION_KEY][-1]

    def attempt(self, password):
        return self.client.post(reverse("login"), {
            "username": "dio.kota", "password": password, "captcha": self.solve_captcha(),
        })

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_lockout_after_the_failure_limit(self):
        for _ in range(3):
            self.attempt("Wrong@12345")
        # The right password now fails too: the pair is locked, not the password.
        self.attempt("Right@12345")
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_a_wrong_captcha_is_not_a_login_failure(self):
        # CaptchaAuthenticationForm.clean() returns early when the captcha fails,
        # so authenticate() is never called and axes never counts it.
        for _ in range(5):
            self.client.post(reverse("login"), {
                "username": "dio.kota", "password": "Right@12345", "captcha": "XXXXX",
            })
        self.attempt("Right@12345")
        self.assertIn("_auth_user_id", self.client.session)
```

- [ ] **Step 7: Run the new tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security -v 2`
Expected: both PASS.

If `test_lockout_after_the_failure_limit` fails, `override_settings` is not reaching axes (it caches its handler). Fix by adding `AXES_HANDLER = 'axes.handlers.database.AxesDatabaseHandler'` to settings and re-run; report if it still fails.

- [ ] **Step 8: Lint and commit**

```bash
cd .. && uv run ruff check .
git add pyproject.toml uv.lock mpr_raj/mpr_raj/settings.py mpr_raj/.env.example mpr_raj/accounts/tests/test_security.py
git commit -m "Add django-axes lockout on the username and IP pair"
```

---

### Task 2: The SecurityEvent model

**Files:**
- Modify: `mpr_raj/accounts/models.py` (append at end of file)
- Create: `mpr_raj/accounts/migrations/0017_securityevent.py` (generated)
- Test: `mpr_raj/accounts/tests/test_security.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `accounts.models.SecurityEvent` with the action constants `LOGIN_OK`, `LOGIN_FAIL`, `LOGOUT`, `LOCKED_OUT`, `LOCK_CLEARED`, `PASSWORD_CHANGED`, `ROLE_CHANGED`, `USER_CREATED`, `USER_DISABLED`, `USER_ENABLED`, `USER_DELETED`, and the class attribute `ACTIONS` (list of `(value, label)` tuples).

- [ ] **Step 1: Write the failing test**

Append to `mpr_raj/accounts/tests/test_security.py`:

```python
class SecurityEventModelTests(TestCase):
    def test_labels_outlive_the_user_they_name(self):
        from ..models import SecurityEvent

        admin = User.objects.create_user("admin.one", password="x", is_staff=True)
        victim = User.objects.create_user("dio.gone", password="x")
        SecurityEvent.objects.create(
            action=SecurityEvent.USER_DELETED,
            actor=admin, actor_label=admin.username,
            target=victim, target_label=victim.username,
        )
        victim.delete()

        event = SecurityEvent.objects.get()
        self.assertIsNone(event.target)              # FK went null
        self.assertEqual(event.target_label, "dio.gone")   # the record still reads

    def test_a_failed_login_can_name_a_user_that_never_existed(self):
        from ..models import SecurityEvent

        SecurityEvent.objects.create(
            action=SecurityEvent.LOGIN_FAIL, actor=None, actor_label="root",
        )
        self.assertEqual(SecurityEvent.objects.get().actor_label, "root")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.SecurityEventModelTests`
Expected: FAIL — `ImportError: cannot import name 'SecurityEvent'`.

- [ ] **Step 3: Add the model**

Append to the end of `mpr_raj/accounts/models.py`:

```python
class SecurityEvent(models.Model):
    """
    One security-relevant thing that happened: a sign-in, a failure, a lockout,
    a role change. Written by accounts/security.py, never edited.

    actor/target are for linking while the user exists; the *_label fields are
    what the log actually says. Two required cases break a bare FK — a deleted
    account leaves the row pointing at NULL, and a failed login can name a user
    that never existed, which is exactly what guessing looks like.
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
```

- [ ] **Step 4: Generate and apply the migration**

Run:
```bash
cd mpr_raj && uv run python manage.py makemigrations accounts && uv run python manage.py migrate
```
Expected: creates `0017_securityevent.py`.

- [ ] **Step 5: Run the tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
cd .. && uv run ruff check .
git add mpr_raj/accounts/models.py mpr_raj/accounts/migrations/0017_securityevent.py mpr_raj/accounts/tests/test_security.py
git commit -m "Add the SecurityEvent model"
```

---

### Task 3: The record() helper

**Files:**
- Create: `mpr_raj/accounts/security.py`
- Modify: `README.md`
- Test: `mpr_raj/accounts/tests/test_security.py`

**Interfaces:**
- Consumes: `accounts.models.SecurityEvent` from Task 2; `axes.helpers.get_client_ip_address` from Task 1.
- Produces:
  - `client_ip(request) -> str | None`
  - `record(action, *, actor=None, actor_label="", target=None, target_label="", request=None, detail="") -> None`

- [ ] **Step 1: Write the failing tests**

Append to `mpr_raj/accounts/tests/test_security.py`:

```python
class RecordTests(TestCase):
    def test_a_spoofed_forwarded_header_does_not_change_the_logged_ip(self):
        from ..models import SecurityEvent
        from ..security import record

        request = self.client.request().wsgi_request
        request.META["REMOTE_ADDR"] = "10.0.0.5"
        request.META["HTTP_X_FORWARDED_FOR"] = "1.2.3.4"
        record(SecurityEvent.LOGIN_OK, actor_label="dio.kota", request=request)

        # Without a trusted-proxy configuration, the client-supplied header must
        # not win. A forgeable IP in a security log is worse than no IP at all.
        self.assertNotEqual(SecurityEvent.objects.get().ip, "1.2.3.4")

    def test_over_long_labels_are_truncated_not_rejected(self):
        from ..models import SecurityEvent
        from ..security import record

        record(SecurityEvent.LOGIN_FAIL, actor_label="z" * 400)
        self.assertEqual(len(SecurityEvent.objects.get().actor_label), 150)

    def test_a_write_failure_does_not_propagate(self):
        from unittest.mock import patch
        from ..models import SecurityEvent
        from ..security import record

        with patch.object(SecurityEvent.objects, "create", side_effect=RuntimeError("db down")):
            record(SecurityEvent.LOGIN_OK, actor_label="dio.kota")   # must not raise
        self.assertEqual(SecurityEvent.objects.count(), 0)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.RecordTests`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.security'`.

- [ ] **Step 3: Write the module**

Create `mpr_raj/accounts/security.py`:

```python
"""
Writing the security log. Every SecurityEvent row in the system is created here.

Nothing in this module may raise into a request: a logging failure must not stop
someone signing in. The accepted trade is that anyone able to cause database
errors could suppress logging — acceptable for monitoring, not for a formal audit.
"""
import logging

from axes.helpers import get_client_ip_address

from .models import SecurityEvent

logger = logging.getLogger(__name__)


def client_ip(request):
    """
    Axes owns this parse. Taking HTTP_X_FORWARDED_FOR's first value by hand is
    spoofable — a client can forge its own address into the log.

    Deployment note: nginx must OVERWRITE X-Forwarded-For, not append to a
    client-supplied value, or this is forgeable again upstream of us.
    """
    if request is None:
        return None
    try:
        return get_client_ip_address(request) or None
    except Exception:
        return request.META.get("REMOTE_ADDR") or None


def _name(user):
    return getattr(user, "username", "") or ""


def record(action, *, actor=None, actor_label="", target=None, target_label="",
           request=None, detail=""):
    """Write one event. Swallows its own failures by design — see module docstring."""
    try:
        SecurityEvent.objects.create(
            action=action,
            actor=actor if getattr(actor, "pk", None) else None,
            actor_label=(actor_label or _name(actor))[:150],
            target=target if getattr(target, "pk", None) else None,
            target_label=(target_label or _name(target))[:150],
            ip=client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else "")[:256],
            detail=detail,
        )
    except Exception:
        logger.exception("security event not recorded: %s", action)
```

- [ ] **Step 4: Run the tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.RecordTests`
Expected: PASS.

- [ ] **Step 5: Document the nginx requirement**

In `README.md`, in the `## Deployment` section, append to the paragraph that already mentions serving `staticfiles/` and `media/`:

```markdown
The security log records the client IP from `X-Forwarded-For`. nginx must
**overwrite** that header rather than append to it —
`proxy_set_header X-Forwarded-For $remote_addr;` — or a client can forge its own
address into the log.
```

- [ ] **Step 6: Lint and commit**

```bash
cd .. && uv run ruff check .
git add mpr_raj/accounts/security.py mpr_raj/accounts/tests/test_security.py README.md
git commit -m "Add the security log record() helper"
```

---

### Task 4: Signal receivers for auth and lockout

**Files:**
- Create: `mpr_raj/accounts/apps.py`
- Modify: `mpr_raj/accounts/security.py`
- Test: `mpr_raj/accounts/tests/test_security.py`

**Interfaces:**
- Consumes: `record()` from Task 3.
- Produces: `accounts.apps.AccountsConfig`; receivers connected at startup. No new callables for later tasks.

Note: `accounts/` has no `apps.py` today. Django auto-discovers one named `apps.py` with a single `AppConfig` subclass, so `INSTALLED_APPS` needs no change.

- [ ] **Step 1: Write the failing tests**

Append to `mpr_raj/accounts/tests/test_security.py`:

```python
class AuthSignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dio.kota", password="Right@12345",
                                             must_change_password=False)

    def solve_captcha(self):
        self.client.get(reverse("captcha_image"))
        return self.client.session[SESSION_KEY][-1]

    def sign_in(self, username="dio.kota", password="Right@12345"):
        return self.client.post(reverse("login"), {
            "username": username, "password": password, "captcha": self.solve_captcha(),
        })

    def test_a_successful_sign_in_is_recorded(self):
        from ..models import SecurityEvent

        self.sign_in()
        event = SecurityEvent.objects.get(action=SecurityEvent.LOGIN_OK)
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.actor_label, "dio.kota")

    def test_a_failure_against_a_user_that_does_not_exist_is_recorded(self):
        from ..models import SecurityEvent

        self.sign_in(username="root", password="anything")
        event = SecurityEvent.objects.get(action=SecurityEvent.LOGIN_FAIL)
        self.assertIsNone(event.actor)            # nothing to point at
        self.assertEqual(event.actor_label, "root")   # but we know what was tried

    def test_signing_out_is_recorded(self):
        from ..models import SecurityEvent

        self.sign_in()
        self.client.post(reverse("logout"))
        self.assertTrue(SecurityEvent.objects.filter(action=SecurityEvent.LOGOUT).exists())
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.AuthSignalTests`
Expected: FAIL — `SecurityEvent.DoesNotExist`, nothing is being recorded yet.

- [ ] **Step 3: Add the receivers**

Append to `mpr_raj/accounts/security.py`:

```python
def connect():
    """Wire the receivers. Called once from AccountsConfig.ready()."""
    from axes.signals import user_locked_out
    from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
    from django.dispatch import receiver

    @receiver(user_logged_in, dispatch_uid="seclog_login_ok")
    def _login_ok(sender, request, user, **kwargs):
        record(SecurityEvent.LOGIN_OK, actor=user, request=request)

    @receiver(user_logged_out, dispatch_uid="seclog_logout")
    def _logout(sender, request, user, **kwargs):
        record(SecurityEvent.LOGOUT, actor=user, request=request)

    @receiver(user_login_failed, dispatch_uid="seclog_login_fail")
    def _login_fail(sender, credentials, request=None, **kwargs):
        # The username may match no user at all — that is the case worth seeing.
        record(SecurityEvent.LOGIN_FAIL,
               actor_label=str(credentials.get("username") or "(blank)"), request=request)

    @receiver(user_locked_out, dispatch_uid="seclog_locked_out")
    def _locked_out(sender, request=None, username=None, **kwargs):
        record(SecurityEvent.LOCKED_OUT, actor_label=str(username or "(blank)"), request=request)
```

`dispatch_uid` on each receiver keeps a double `ready()` call from double-recording.

- [ ] **Step 4: Create the AppConfig**

Create `mpr_raj/accounts/apps.py`:

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from . import security

        security.connect()
```

- [ ] **Step 5: Run the tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security`
Expected: all PASS.

If `test_a_failure_against_a_user_that_does_not_exist_is_recorded` fails with nothing recorded, check that `AXES_ENABLED` being false in tests has not disabled the auth backend — `user_login_failed` is Django's own signal and must fire regardless.

- [ ] **Step 6: Run the whole suite**

Run: `cd mpr_raj && uv run python manage.py test`
Expected: `Ran 8x tests` / `OK`. Every existing test that signs in now writes a `SecurityEvent`; none should break.

- [ ] **Step 7: Lint and commit**

```bash
cd .. && uv run ruff check .
git add mpr_raj/accounts/apps.py mpr_raj/accounts/security.py mpr_raj/accounts/tests/test_security.py
git commit -m "Record sign-ins, failures, sign-outs and lockouts"
```

---

### Task 5: Record role, account and password events

**Files:**
- Modify: `mpr_raj/accounts/views/master.py` (`_confirm_delete`, `user_form`, `user_delete`)
- Modify: `mpr_raj/accounts/views/home.py` (`ForcedPasswordChangeView.form_valid`)
- Test: `mpr_raj/accounts/tests/test_security.py`

**Interfaces:**
- Consumes: `record()` from Task 3; `SecurityEvent` constants from Task 2.
- Produces: `_confirm_delete(request, obj, back, label, warnings=(), on_deleted=None)` — one new keyword-only-in-practice parameter, default `None`, called with no arguments immediately after a successful `obj.delete()`.

`_confirm_delete` is shared by `user_delete`, `district_delete` and `project_delete`, so the user event cannot be recorded inside it. The callback lets `user_delete` hook only its own case.

- [ ] **Step 1: Write the failing tests**

Append to `mpr_raj/accounts/tests/test_security.py`:

```python
class ViewCaptureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin.one", password="x", is_staff=True,
                                              must_change_password=False)
        self.client.force_login(self.admin)

    def test_a_role_change_records_who_changed_what(self):
        from ..models import SecurityEvent

        staff = User.objects.create_user("emp.one", password="x", name="Asha")
        self.client.post(reverse("user_edit", args=[staff.pk]), {
            "email": "emp.one@nic.in", "name": "Asha", "employee_code": "", "phone": "",
            "ip_phone": "", "is_dio": "on", "is_active": "on",
        })
        event = SecurityEvent.objects.get(action=SecurityEvent.ROLE_CHANGED)
        self.assertEqual(event.actor, self.admin)     # the admin acted
        self.assertEqual(event.target, staff)         # on this person
        self.assertIn("is_dio", event.detail)
        self.assertIn("No → Yes", event.detail)

    def test_deleting_a_user_records_it_before_the_row_goes(self):
        from ..models import SecurityEvent

        doomed = User.objects.create_user("emp.gone", password="x")
        self.client.post(reverse("user_delete", args=[doomed.pk]))
        self.assertFalse(User.objects.filter(pk=doomed.pk).exists())

        event = SecurityEvent.objects.get(action=SecurityEvent.USER_DELETED)
        self.assertEqual(event.target_label, "emp.gone")   # readable after the fact
        self.assertEqual(event.actor, self.admin)

    def test_a_password_change_is_recorded(self):
        from ..models import SecurityEvent

        self.client.post(reverse("password_change"), {
            "old_password": "x",
            "new_password1": "My0wn-Str0ng-Pass", "new_password2": "My0wn-Str0ng-Pass",
        })
        self.assertTrue(
            SecurityEvent.objects.filter(action=SecurityEvent.PASSWORD_CHANGED).exists())
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.ViewCaptureTests`
Expected: FAIL — `SecurityEvent.DoesNotExist` on all three.

- [ ] **Step 3: Add the callback to `_confirm_delete`**

In `mpr_raj/accounts/views/master.py`, change the signature and the success branch:

```python
def _confirm_delete(request, obj, back, label, warnings=(), on_deleted=None):
    """`back` is anything redirect() takes — a URL name, or a path when it needs args."""
    blocked = None
    if request.method == "POST":
        try:
            obj.delete()
            if on_deleted:
                on_deleted()
            return redirect(back)
```

The rest of the function is unchanged.

- [ ] **Step 4: Record from `user_form` and `user_delete`**

Add to the imports at the top of `mpr_raj/accounts/views/master.py`:

```python
from ..models import SecurityEvent
from ..security import record
```

(`SecurityEvent` joins the existing `from ..models import (...)` block — keep it fill-wrapped, do not explode it one-per-line.)

Add this helper just above `user_form`:

```python
ROLE_FIELDS = ["is_staff", "is_sio", "is_gl", "is_pl", "is_dio"]


def _role_detail(form):
    """"is_staff: No → Yes" for each role the save changed. Django computes the diff."""
    def word(value):
        return "Yes" if value else "No"

    return ", ".join(f"{f}: {word(form.initial.get(f))} → {word(form.cleaned_data.get(f))}"
                     for f in ROLE_FIELDS if f in form.changed_data)
```

In `user_form`, replace the save branch:

```python
    if request.method == "POST" and form.is_valid():
        creating = user is None
        roles = _role_detail(form)
        activity = "is_active" in form.changed_data
        saved = form.save()
        if creating:
            record(SecurityEvent.USER_CREATED, actor=request.user, target=saved,
                   request=request)
        else:
            if roles:
                record(SecurityEvent.ROLE_CHANGED, actor=request.user, target=saved,
                       request=request, detail=roles)
            if activity:
                record(SecurityEvent.USER_ENABLED if saved.is_active
                       else SecurityEvent.USER_DISABLED,
                       actor=request.user, target=saved, request=request)
        return redirect("user_list")
```

In `user_delete`, replace the final `return`:

```python
    label = user.username          # captured before the row goes
    return _confirm_delete(request, user, "user_list",
                           f"user “{user.name or user.username}”", warnings,
                           on_deleted=lambda: record(SecurityEvent.USER_DELETED,
                                                     actor=request.user, target_label=label,
                                                     request=request))
```

- [ ] **Step 5: Record the password change**

In `mpr_raj/accounts/views/home.py`, add to the imports:

```python
from ..models import MPRPeriod, SecurityEvent, User
from ..security import record
```

and in `ForcedPasswordChangeView.form_valid`, after the existing activation block:

```python
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
```

- [ ] **Step 6: Run the tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security`
Expected: all PASS.

- [ ] **Step 7: Run the whole suite**

Run: `cd mpr_raj && uv run python manage.py test`
Expected: `OK`. `_confirm_delete` gained a defaulted parameter, so the district and project delete callers are unaffected.

- [ ] **Step 8: Lint and commit**

```bash
cd .. && uv run ruff check .
git add mpr_raj/accounts/views/master.py mpr_raj/accounts/views/home.py mpr_raj/accounts/tests/test_security.py
git commit -m "Record role changes, account lifecycle and password changes"
```

---

### Task 6: Let the filter row render a text input

**Files:**
- Modify: `mpr_raj/accounts/templates/accounts/_filters.html`
- Test: `mpr_raj/accounts/tests/test_master.py` (guard the existing callers)

**Interfaces:**
- Consumes: nothing.
- Produces: `_filters.html` accepts an optional `"type": "text"` key on a filter dict. Absent or any other value renders the existing `<select>`, so `user_list` and `project_list` are untouched.

Why a text input at all: the user filter must match `actor_label`, and a failed login against a username that does not exist has no `User` to appear in a dropdown. A select would hide exactly the rows the filter exists to find.

- [ ] **Step 1: Write the guard test**

Append to `mpr_raj/accounts/tests/test_master.py`, inside `MasterDataTests`:

```python
    def test_existing_filter_rows_still_render_selects(self):
        # _filters.html grew a text-input branch for the security log; the master
        # lists must be unaffected by it.
        self.client.force_login(self.admin)
        for url in ("user_list", "project_list"):
            resp = self.client.get(reverse(url))
            self.assertContains(resp, "<select")
            self.assertNotContains(resp, 'type="search"')
```

- [ ] **Step 2: Run it**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_master.MasterDataTests.test_existing_filter_rows_still_render_selects`
Expected: PASS already — this is a regression guard, not a red test.

- [ ] **Step 3: Add the text branch**

In `mpr_raj/accounts/templates/accounts/_filters.html`, replace the `<select>` block inside the `{% for f in filters %}` loop:

```html
  {% for f in filters %}
  <div>
    <label for="f-{{ f.name }}">{{ f.label }}</label>
    {% if f.type == "text" %}
    <input type="search" id="f-{{ f.name }}" name="{{ f.name }}"
           value="{{ f.selected }}" placeholder="{{ f.blank }}">
    {% else %}
    <select id="f-{{ f.name }}" name="{{ f.name }}" data-submit-on-change>
      <option value="">{{ f.blank }}</option>
      {% for value, label in f.options %}
      <option value="{{ value }}" {% if f.selected == value|stringformat:"s" %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
    {% endif %}
  </div>
  {% endfor %}
```

Also update the `{% comment %}` block at the top of the file to mention the new key:

```
Context: `filters` (one dict per control: name, label, blank, options, selected,
and optional type — "text" for a search box, anything else for a select),
`filtered`, `showing`, `total`, `clear_url`.
```

The text input deliberately has no `data-submit-on-change` — it submits on Enter, since submitting on every keystroke would fire a request per character.

- [ ] **Step 4: Run the whole suite**

Run: `cd mpr_raj && uv run python manage.py test`
Expected: `OK`.

- [ ] **Step 5: Lint and commit**

```bash
cd .. && uv run ruff check .
git add mpr_raj/accounts/templates/accounts/_filters.html mpr_raj/accounts/tests/test_master.py
git commit -m "Let the filter row render a text input"
```

---

### Task 7: The security log screen

**Files:**
- Create: `mpr_raj/accounts/views/security.py`
- Create: `mpr_raj/accounts/templates/accounts/security_log.html`
- Modify: `mpr_raj/accounts/views/__init__.py`
- Modify: `mpr_raj/accounts/urls.py`
- Modify: `mpr_raj/accounts/templates/accounts/app.html`
- Modify: `mpr_raj/accounts/static/accounts/app.css`
- Test: `mpr_raj/accounts/tests/test_security.py`

**Interfaces:**
- Consumes: `SecurityEvent` (Task 2), `admin_required` from `accounts.views.master`.
- Produces:
  - `security_log(request)` at url name `security_log`, path `/security/`
  - `_filtered(request) -> (queryset, kept_dict, filters_list)` — reused by the export in Task 9. `kept_dict` holds only the non-empty filter values; `filters_list` is the `_filters.html` context.

- [ ] **Step 1: Write the failing tests**

Append to `mpr_raj/accounts/tests/test_security.py`:

```python
class SecurityScreenTests(TestCase):
    def setUp(self):
        from ..models import SecurityEvent

        self.admin = User.objects.create_user("admin.one", password="x", is_staff=True,
                                              must_change_password=False)
        SecurityEvent.objects.create(action=SecurityEvent.LOGIN_OK, actor_label="dio.kota")
        SecurityEvent.objects.create(action=SecurityEvent.LOGIN_FAIL, actor_label="root")

    def test_a_non_admin_cannot_reach_it(self):
        plain = User.objects.create_user("dio.kota", password="x", must_change_password=False)
        self.client.force_login(plain)
        self.assertNotEqual(self.client.get(reverse("security_log")).status_code, 200)

    def test_an_admin_sees_every_event(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security_log"))
        self.assertContains(resp, "dio.kota")
        self.assertContains(resp, "root")

    def test_the_user_filter_matches_a_name_with_no_account(self):
        # The whole reason this filter is a text box and not a dropdown.
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security_log"), {"user": "root"})
        self.assertContains(resp, "root")
        self.assertNotContains(resp, "dio.kota")

    def test_the_action_filter_narrows_by_kind(self):
        from ..models import SecurityEvent

        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security_log"), {"action": SecurityEvent.LOGIN_FAIL})
        self.assertEqual(len(resp.context["events"]), 1)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.SecurityScreenTests`
Expected: FAIL — `NoReverseMatch: 'security_log' is not a valid view function or pattern name`.

- [ ] **Step 3: Write the view**

Create `mpr_raj/accounts/views/security.py`:

```python
"""The admin-only security log: list, filter, and the lockout override."""
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from ..models import SecurityEvent
from .master import admin_required

PER_PAGE = 100


def _filtered(request):
    """(queryset, kept, filters) — shared with the text export so they can't drift."""
    events = SecurityEvent.objects.select_related("actor", "target")

    user = request.GET.get("user", "").strip()
    action = request.GET.get("action", "")
    if user:
        # actor_label, not the FK: a failed login can name a user that never existed.
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


@admin_required
def security_log(request):
    """
    Unlike the master lists this one paginates: retention is keep-everything and
    every sign-in adds a row, so it grows without bound.
    """
    events, kept, filters = _filtered(request)
    total = SecurityEvent.objects.count()
    page = Paginator(events, PER_PAGE).get_page(request.GET.get("page"))

    return render(request, "accounts/security_log.html", {
        "events": page, "page": page,
        # Filters ride along in the page links so a filtered view stays linkable.
        "qs": ("&" + urlencode(kept)) if kept else "",
        "filters": filters, "filtered": bool(kept),
        "showing": page.paginator.count, "total": total,
        "clear_url": "security_log",
    })
```

- [ ] **Step 4: Export the view and add the URL**

In `mpr_raj/accounts/views/__init__.py`, add a re-export block matching the existing style (fill-wrapped, `# noqa: F401` on the import line):

```python
from .security import security_log  # noqa: F401
```

In `mpr_raj/accounts/urls.py`, add before the `reports/` group:

```python
    path("security/", views.security_log, name="security_log"),
```

- [ ] **Step 5: Write the template**

Create `mpr_raj/accounts/templates/accounts/security_log.html`:

```html
{% extends "accounts/app.html" %}
{% block title %}Security log{% endblock %}
{% block content %}
<div class="page-head">
  <div class="t">Security log</div>
</div>

{% include "accounts/_filters.html" %}

{# Column widths live in app.css, under .tbl-security. #}
<div class="table tbl-security">
  <div class="thead">
    <div>When</div><div>Event</div><div>User</div>
    <div>Target</div><div>IP</div><div>Detail</div>
  </div>
  {% for e in events %}
  <div class="trow">
    <div class="t-val">{{ e.at|date:"d-m-Y H:i" }}</div>
    <div class="t-key">{{ e.get_action_display }}</div>
    <div class="t-id">{{ e.actor_label|default:"-" }}</div>
    <div class="t-id">{{ e.target_label|default:"-" }}</div>
    <div class="t-val">{{ e.ip|default:"-" }}</div>
    <div class="t-note">{{ e.detail|default:"-" }}</div>
  </div>
  {% empty %}
  <div class="trow empty">
    {% if filtered %}
    <div class="t-block">No events match these filters</div>
    <div class="t-note"><a href="{% url 'security_log' %}">Clear the filters</a> to see all {{ total }}.</div>
    {% else %}
    <div class="t-block">No events recorded yet</div>
    {% endif %}
  </div>
  {% endfor %}
</div>

{% if page.has_other_pages %}
<div class="pager">
  {% if page.has_previous %}
  <a class="btn-outline" href="?page={{ page.previous_page_number }}{{ qs }}">Previous</a>
  {% endif %}
  <span>Page {{ page.number }} of {{ page.paginator.num_pages }}</span>
  {% if page.has_next %}
  <a class="btn-outline" href="?page={{ page.next_page_number }}{{ qs }}">Next</a>
  {% endif %}
</div>
{% endif %}
{% endblock %}
```

Note the download link is wired now but its URL name arrives in Task 9 — this template will not render until then. That is why Task 9 immediately follows.

- [ ] **Step 6: Add the nav item**

In `mpr_raj/accounts/templates/accounts/app.html`, inside the `{% if user.is_staff %}` Administration group, after the "Reporting months" link:

```html
        <a href="{% url 'security_log' %}" title="Security log" {% if 'security' in n %}class="active" aria-current="page"{% endif %}>
          <span class="material-symbols-outlined" aria-hidden="true">shield</span>
          <span>Security log</span>
        </a>
```

- [ ] **Step 7: Add the column widths**

In `mpr_raj/accounts/static/accounts/app.css`, next to the other `.tbl-*` rules:

```css
/* Six columns; Detail takes the slack because it holds sentences. */
.tbl-security .thead, .tbl-security .trow {
  grid-template-columns: 130px 130px 130px 130px 120px 1fr;
}

/* Pager under a paginated table. The security log is the only list long enough
   to need one. */
.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
```

- [ ] **Step 8: Run the tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.SecurityScreenTests -v 2`
Expected: all four PASS.

The download button is deliberately absent from this template — it arrives in Task 9 with the view it points at, so this task stands on its own.

- [ ] **Step 9: Run the whole suite**

Run: `cd mpr_raj && uv run python manage.py test`
Expected: `OK`.

- [ ] **Step 10: Lint and commit**

```bash
cd .. && uv run ruff check .
git add mpr_raj/accounts/views/security.py mpr_raj/accounts/views/__init__.py \
        mpr_raj/accounts/urls.py \
        mpr_raj/accounts/templates/accounts/security_log.html \
        mpr_raj/accounts/templates/accounts/app.html \
        mpr_raj/accounts/static/accounts/app.css \
        mpr_raj/accounts/tests/test_security.py
git commit -m "Add the admin-only security log screen"
```

---

### Task 8: The lockout override

**Files:**
- Modify: `mpr_raj/accounts/views/security.py`
- Modify: `mpr_raj/accounts/views/__init__.py`
- Modify: `mpr_raj/accounts/urls.py`
- Modify: `mpr_raj/accounts/templates/accounts/security_log.html`
- Test: `mpr_raj/accounts/tests/test_security.py`

**Interfaces:**
- Consumes: `record()` (Task 3), `admin_required`.
- Produces: `security_unlock(request)` at url name `security_unlock`, path `/security/unlock/`. POST only.

- [ ] **Step 1: Write the failing test**

Append to `mpr_raj/accounts/tests/test_security.py`:

```python
class UnlockTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin.one", password="x", is_staff=True,
                                              must_change_password=False)

    def test_a_non_admin_cannot_clear_a_lock(self):
        plain = User.objects.create_user("dio.kota", password="x", must_change_password=False)
        self.client.force_login(plain)
        resp = self.client.post(reverse("security_unlock"), {"username": "dio.kota"})
        self.assertNotEqual(resp.status_code, 302)

    def test_clearing_a_lock_is_itself_recorded(self):
        from ..models import SecurityEvent

        self.client.force_login(self.admin)
        self.client.post(reverse("security_unlock"), {"username": "dio.kota"})
        event = SecurityEvent.objects.get(action=SecurityEvent.LOCK_CLEARED)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.target_label, "dio.kota")

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_clearing_a_lock_actually_restores_access(self):
        # Recording the clear is not the point — letting the person back in is.
        User.objects.create_user("dio.kota", password="Right@12345",
                                 must_change_password=False)

        def solve():
            self.client.get(reverse("captcha_image"))
            return self.client.session[SESSION_KEY][-1]

        for _ in range(3):
            self.client.post(reverse("login"), {
                "username": "dio.kota", "password": "Wrong@12345", "captcha": solve()})

        self.client.force_login(self.admin)
        self.client.post(reverse("security_unlock"), {"username": "dio.kota"})
        self.client.logout()

        self.client.post(reverse("login"), {
            "username": "dio.kota", "password": "Right@12345", "captcha": solve()})
        self.assertIn("_auth_user_id", self.client.session)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.UnlockTests`
Expected: FAIL — `NoReverseMatch: 'security_unlock'`.

- [ ] **Step 3: Write the view**

Append to `mpr_raj/accounts/views/security.py`:

```python
def _locked_out():
    """Currently locked username+IP pairs, newest first. Empty when axes is off."""
    try:
        from axes.models import AccessAttempt
    except ImportError:
        return []
    return AccessAttempt.objects.order_by("-attempt_time")[:50]


@admin_required
def security_unlock(request):
    """
    Clear one lockout immediately. The cool-off would expire on its own, but a DIO
    locked out at 9pm on the 5th cannot wait for it.
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
```

Add `record` to the module's imports:

```python
from ..security import record
```

- [ ] **Step 4: Show the locked pairs on the screen**

In `security_log`, add `"locked": _locked_out(),` to the render context.

In `security_log.html`, immediately after the `page-head` block:

```html
{% if locked %}
<div class="card">
  <div class="c-head">Currently locked out</div>
  {% for a in locked %}
  <div class="lock-row">
    <span class="t-id">{{ a.username }}</span>
    <span class="t-val">{{ a.ip_address|default:"-" }}</span>
    <span class="t-note">{{ a.attempt_time|date:"d-m-Y H:i" }}</span>
    <form method="post" action="{% url 'security_unlock' %}">
      {% csrf_token %}
      <input type="hidden" name="username" value="{{ a.username }}">
      <button type="submit" class="btn-outline">Clear</button>
    </form>
  </div>
  {% endfor %}
</div>
{% endif %}
```

Nothing renders when nothing is locked, so the common case stays quiet.

- [ ] **Step 5: Export and route it**

`views/__init__.py`:

```python
from .security import security_log, security_unlock  # noqa: F401
```

`urls.py`, beside the `security/` path:

```python
    path("security/unlock/", views.security_unlock, name="security_unlock"),
```

- [ ] **Step 6: Add the row style**

In `app.css`, beside `.pager`:

```css
/* One locked-out pair and its Clear button. */
.lock-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
}
```

- [ ] **Step 7: Run the tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.UnlockTests -v 2`
Expected: all three PASS.

If `test_clearing_a_lock_actually_restores_access` fails at the lockout stage, axes is not honouring `override_settings` — see the note in Task 1 Step 7.

- [ ] **Step 8: Run the whole suite and commit**

```bash
cd mpr_raj && uv run python manage.py test
cd .. && uv run ruff check .
git add mpr_raj/accounts/views/security.py mpr_raj/accounts/views/__init__.py \
        mpr_raj/accounts/urls.py \
        mpr_raj/accounts/templates/accounts/security_log.html \
        mpr_raj/accounts/static/accounts/app.css \
        mpr_raj/accounts/tests/test_security.py
git commit -m "Let an admin clear a lockout before the cool-off expires"
```

---

### Task 9: The plain-text export

**Files:**
- Modify: `mpr_raj/accounts/views/security.py`
- Modify: `mpr_raj/accounts/views/__init__.py`
- Modify: `mpr_raj/accounts/urls.py`
- Test: `mpr_raj/accounts/tests/test_security.py`

**Interfaces:**
- Consumes: `_filtered(request)` (Task 7).
- Produces: `security_export(request)` at url name `security_export`, path `/security/export.txt`.

- [ ] **Step 1: Write the failing tests**

Append to `mpr_raj/accounts/tests/test_security.py`:

```python
class ExportTests(TestCase):
    def setUp(self):
        from ..models import SecurityEvent

        self.admin = User.objects.create_user("admin.one", password="x", is_staff=True,
                                              must_change_password=False)
        for i in range(150):
            SecurityEvent.objects.create(action=SecurityEvent.LOGIN_OK,
                                         actor_label=f"dio.{i:03d}")
        SecurityEvent.objects.create(action=SecurityEvent.LOGIN_FAIL, actor_label="root")

    def body(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(reverse("security_export"), params).content.decode()

    def test_a_non_admin_cannot_download_it(self):
        plain = User.objects.create_user("dio.kota", password="x", must_change_password=False)
        self.client.force_login(plain)
        self.assertNotEqual(self.client.get(reverse("security_export")).status_code, 200)

    def test_it_ignores_pagination_and_returns_every_matching_row(self):
        # 151 events, 100 per page on screen — a 100-row file would be a trap.
        text = self.body()
        self.assertIn("dio.000", text)
        self.assertIn("dio.149", text)
        self.assertIn("1–151 of 151", text)

    def test_it_respects_the_filter_and_says_so_in_the_header(self):
        text = self.body(user="root")
        self.assertIn("root", text)
        self.assertNotIn("dio.000", text)
        # An export that does not state what was excluded is misleading evidence.
        self.assertIn('user contains "root"', text)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security.ExportTests`
Expected: FAIL — `NoReverseMatch: 'security_export'`.

- [ ] **Step 3: Write the export**

Append to `mpr_raj/accounts/views/security.py`:

```python
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

    shown = ("; ".join(filter(None, [
        f'user contains "{kept["user"]}"' if kept.get("user") else "user: all",
        f'action: {kept["action"]}' if kept.get("action") else "action: all",
    ])))
    lines = [
        "NIC Rajasthan — MPR Portal security log",
        f"Generated   {stamp:%Y-%m-%d %H:%M} IST by {request.user.username}",
        f"Filter      {shown}",
        # There is no row cap. If one is ever added it must be stated here —
        # a silent truncation in a security export is the worst possible failure.
        f"Events      {'1–' + str(len(events)) if events else '0'} of {len(events)}",
        "",
        f"{'WHEN':<17}{'EVENT':<18}{'USER':<20}{'TARGET':<20}{'IP':<16}DETAIL",
        "-" * 110,
    ]
    for e in events:
        lines.append(
            f"{timezone.localtime(e.at):%Y-%m-%d %H:%M}  "
            f"{e.get_action_display():<18}{e.actor_label:<20}"
            f"{e.target_label or '-':<20}{e.ip or '-':<16}{e.detail}".rstrip()
        )

    response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="security-log-{stamp:%Y-%m-%d}.txt"')
    return response
```

Add to the module imports:

```python
from django.http import HttpResponse
from django.utils import timezone
```

- [ ] **Step 4: Export, route it, and add the download button**

`views/__init__.py`:

```python
from .security import security_export, security_log, security_unlock  # noqa: F401
```

`urls.py`, beside the other security paths:

```python
    path("security/export.txt", views.security_export, name="security_export"),
```

Now the button has somewhere to point. In `security_log.html`, replace the `page-head` block:

```html
<div class="page-head">
  <div class="t">Security log</div>
  <a href="{% url 'security_export' %}{% if qs %}?{{ qs|slice:'1:' }}{% endif %}"
     class="btn-outline">Download .txt</a>
</div>
```

`qs` is built with a leading `&` for the pager links, so `slice:'1:'` strips it to
make a valid query string. The link carries the active filters, so the file you
download matches the screen you are looking at.

- [ ] **Step 5: Run the security tests**

Run: `cd mpr_raj && uv run python manage.py test accounts.tests.test_security -v 2`
Expected: every class passes, including `SecurityScreenTests` and `UnlockTests` from Tasks 7 and 8 — the template's `security_export` reference now resolves.

- [ ] **Step 6: Run the whole suite**

Run: `cd mpr_raj && uv run python manage.py test`
Expected: `OK`, 78 original plus the new ones.

- [ ] **Step 7: Check it in a browser**

Start the dev server, sign in as an admin, and confirm: the Security log item appears in the sidebar; the table lists events; filtering by a login ID narrows it; Download .txt returns a file whose header names the filter.

- [ ] **Step 8: Lint and commit**

```bash
cd .. && uv run ruff check .
git add mpr_raj/accounts/views/security.py mpr_raj/accounts/views/__init__.py \
        mpr_raj/accounts/urls.py \
        mpr_raj/accounts/templates/accounts/security_log.html \
        mpr_raj/accounts/tests/test_security.py
git commit -m "Add the plain-text security log export"
```

---

## Deferred, and why

- **Wrong-captcha attempts are not logged.** `CaptchaAuthenticationForm.clean()` returns before `authenticate()`, so neither Django nor axes sees them. Repeated captcha failures from one address is a bot signature and may be worth recording later; it needs its own capture point in `clean_captcha`, not a signal.
- Pruning or archiving, if the table ever grows enough to matter.
- A user-facing "recent sign-ins to your account" panel.
- Alerting — needs email, which is not configured.
- A separate MPR-entry change log, if "who edited my entry" is wanted. That is a different model with a different audience; merging it here would bury these rows.
