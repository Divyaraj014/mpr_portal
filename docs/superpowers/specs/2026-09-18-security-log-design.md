# Security log — design

Date: 2026-09-18
Status: approved, not yet implemented

## Purpose

A security monitoring log for the MPR portal: who signed in, who failed to, who
changed whose roles, and who was locked out. Read by admins when investigating
suspicious access.

## Scope

**In scope**

- Authentication events: login success, login failure, logout, lockout.
- Role and permission changes (`is_staff`, `is_sio`, `is_gl`, `is_pl`, `is_dio`).
- Account lifecycle: created, disabled, re-enabled, deleted.
- Password events: self-service change and the forced first-login change.
- Lockout enforcement after repeated failures, with recovery.
- An admin-only screen with filters, and a plain-text export.

**Explicitly out of scope**

This is *not* "a log of every activity". MPR entry edits, report downloads,
master-data changes and page views are **not** recorded. Logging everything
buries the handful of events that carry security meaning.

"Who edited my MPR entry" is a separate feature with a different model, a
different audience and a different retention answer. If it is wanted, build it
separately. Merging the two produces a table where the important rows drown.

## Decisions

| Question | Decision |
|---|---|
| Primary purpose | Security monitoring |
| Record or enforce | Record **and** lock out repeat failures |
| Lockout key | Username + IP **combined** (the pair) |
| Recovery | Auto cool-off **plus** an admin override |
| Events | Auth, role/permission, account lifecycle, password |
| Readers | Admins (`is_staff`) only |
| Retention | Keep everything; no pruning |
| Capture approach | View/form layer (approach A), not model signals |

### Why username+IP rather than either alone

Locking on username alone lets anyone who knows a login ID lock that person
out deliberately. The portal has monthly deadlines, so locking the Jaipur DIO
on the 5th is an attack with real consequences.

Locking on IP alone is worse in a different way: NIC district offices sit
behind shared NAT, so one person mistyping a password locks out their whole
office.

Locking the pair means a remote attacker cannot lock a DIO out of their own
office, and one fumbled password does not take down a district.

### Why the view layer rather than model signals

Model signals (`pre_save` diffing) would catch changes made from anywhere,
including `manage.py shell`. But a model signal has no request, so recording
*who* made the change requires thread-local current-user middleware — a
well-known source of subtle bugs that also interacts badly with async.

Changes go through `UserForm`, which already provides `changed_data` and
`initial`. That gives the diff for free, in a place where `request.user` and
the client address are both available.

## Data model

`SecurityEvent` in `accounts/models.py`.

| Field | Type | Notes |
|---|---|---|
| `at` | `DateTimeField(auto_now_add=True)` | |
| `action` | `CharField(max_length=20, choices=ACTIONS)` | |
| `actor` | `FK(User, SET_NULL, null=True, blank=True)` | `related_name="security_events"` |
| `actor_label` | `CharField(max_length=150)` | what the log *says*; see below |
| `target` | `FK(User, SET_NULL, null=True, blank=True)` | `related_name="security_events_about"` |
| `target_label` | `CharField(max_length=150, blank=True)` | |
| `ip` | `GenericIPAddressField(null=True, blank=True)` | |
| `user_agent` | `CharField(max_length=256, blank=True)` | |
| `detail` | `TextField(blank=True)` | e.g. `is_staff: No → Yes` |

`Meta`: `ordering = ["-at"]`, indexes on `-at` and `actor_label`.

Actions: `login_ok`, `login_fail`, `logout`, `locked_out`, `lock_cleared`,
`password_changed`, `role_changed`, `user_created`, `user_disabled`,
`user_enabled`, `user_deleted`.

### Who is actor and who is target

Easy to implement backwards, so stated explicitly: **the actor is whoever
performed the action; the target is whoever it was done to.** They differ only
when an admin acts on someone else.

| Action | `actor` | `target` |
|---|---|---|
| `login_ok`, `login_fail`, `logout`, `locked_out` | the person signing in | empty |
| `password_changed` (self-service) | the user | empty |
| `role_changed`, `user_created`, `user_disabled`, `user_enabled`, `user_deleted` | the admin making the change | the account changed |
| `lock_cleared` | the admin clearing it | the locked-out account |

### Why the denormalised label fields

Two required cases break a plain ForeignKey:

1. **Account deletion is logged.** With `SET_NULL`, deleting `dio.jaipur`
   leaves every row about them pointing at `NULL` — the log would record that
   something happened to someone. Capturing the username as text at write time
   keeps the record readable after the account is gone.
2. **A failed login may name a user that does not exist** — which is precisely
   what guessing looks like. There is no row for a ForeignKey to reference, so
   the attempted string must be stored as text.

The FKs exist for linking while the user exists; the labels are the record.
Labels are truncated to 150 characters on write, because the failed-login field
can contain arbitrary input.

### Why `detail` is text, not JSON

The log is read by humans and exported as text. A pre-rendered sentence avoids
writing the same formatting twice (screen and export). Filtering is by user
only, so JSON's queryability buys nothing here.

### Not doing

No hash chaining, no database-level immutability, no append-only enforcement.
That belongs to a formal audit trail, which was considered and not chosen.
Tamper-resistance here is that no edit or delete UI exists.

## Capture points

A new `accounts/security.py` holds the receivers and a single `record()`
helper. Receivers are connected in `AppConfig.ready()`.

**Via signals — no changes to existing views:**

| Signal | Action |
|---|---|
| `django.contrib.auth.signals.user_logged_in` | `login_ok` |
| `django.contrib.auth.signals.user_login_failed` | `login_fail` |
| `django.contrib.auth.signals.user_logged_out` | `logout` |
| `axes.signals.user_locked_out` | `locked_out` |

`user_login_failed` provides `credentials`; the attempted login ID goes to
`actor_label` with `actor` left null when no such user exists.

**Explicit calls:**

| Location | Action |
|---|---|
| `ForcedPasswordChangeView.form_valid` | `password_changed` |
| `user_form`, creating | `user_created` |
| `user_form`, editing | `role_changed`, `user_disabled`, `user_enabled` |
| `user_delete` | `user_deleted` — recorded **before** the delete, while labels are readable |
| lockout override view | `lock_cleared` |

Role changes come from `form.changed_data` intersected with the role flags,
with old values from `form.initial`. One `role_changed` row per save, detail
listing each change as `field: old → new`.

### The IP field must not be forgeable

The portal sits behind a reverse proxy (`SECURE_PROXY_SSL_HEADER` is set), so
the client address arrives in `X-Forwarded-For`. The naive implementation —
taking the first value — is **spoofable**: a client can send its own header and
forge the IP. A security log with a forgeable field is worse than one without,
because it is evidence people will believe.

Use axes's `get_client_ip_address()` rather than hand-rolling the parse.

**Deployment requirement:** nginx must *overwrite* `X-Forwarded-For`, not
append to a client-supplied value. This is a configuration requirement, not
just a code one, and belongs in the README.

### A logging failure must not break sign-in

`record()` catches its own exceptions and falls back to the file logger. The
accepted trade: someone able to reliably cause database errors could suppress
logging. For internal security monitoring, keeping people able to sign in wins.
Under a formal audit requirement the answer would be the opposite.

### Known seams

- Role changes made through `/admin/` bypass `user_form` and are not recorded
  here. `django.contrib.admin.LogEntry` already captures them, and `/admin/` is
  staff-only.
- Changes made via `manage.py shell` are not recorded anywhere. This follows
  from choosing the view layer over model signals.

## Lockout

`django-axes` 8.3.1 (supports Django 6.0 and Python 3.12) provides enforcement
only; the viewing, filtering and export are ours.

- Lock on the username+IP pair.
- Failure limit 5, cool-off 30 minutes.
- Admin override clears a lock immediately and writes `lock_cleared` naming the
  admin who did it.

Both thresholds read from `.env` so they can be tuned without a deploy:

| Env var | Default |
|---|---|
| `AXES_FAILURE_LIMIT` | `5` |
| `AXES_COOLOFF_MINUTES` | `30` |

The cool-off is expressed in minutes in `.env` and converted to a `timedelta`
in settings, because `django-environ` has no duration type.

Expected axes settings, **to be verified against the installed 8.3.1 before
use** — axes renamed these across major versions and the published docs mix old
and new spellings:

- `AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]` — the nested list is
  what makes it the *combination* rather than either key independently. The
  older spelling for this was `AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP`.
- Installation also requires an `INSTALLED_APPS` entry, an
  `AUTHENTICATION_BACKENDS` entry (`axes.backends.AxesStandaloneBackend` first),
  and `axes.middleware.AxesMiddleware` — all three, or enforcement silently
  does nothing.

## Screen

`/security/`, view `security_log`, `@admin_required`. Fifth item in the
existing Administration group in `app.html`, which is already gated on
`user.is_staff`. Template `security_log.html` extending `app.html`, reusing the
existing `.table` / `.thead` / `.trow` markup with a new `.tbl-security` width
rule in `app.css`.

Columns: When · Action · User · Target · IP · Detail. Newest first.

### Filters

- **User** — a *text input* matching `actor_label`.
- **Action** — a select over the action choices.

The user filter must not be a dropdown of users. A failed login against a
username that does not exist has no `User` to appear in a select, so the
guessing attempts would be invisible to the very filter meant to find them. A
text input handles both real and phantom usernames with one control.

This requires a small extension to `_filters.html` to render a text input: an
optional `"type": "text"` in the filter dict, defaulting to select so
`user_list` and `project_list` are unaffected.

### Pagination

`django.core.paginator.Paginator`, 100 per page.

This screen departs from the other list pages, which deliberately have no
pagination. A security log differs in kind: retention is keep-everything and
every sign-in adds a row, so the table grows without bound. Active filters ride
along in the page links so a filtered view stays linkable across pages.

**No column sorting.** Newest-first is almost always what is wanted, and
sorting plus filters plus pagination is three interacting pieces of URL state
for little benefit.

### Lockout override

A panel above the table, rendered **only when something is currently locked**,
listing locked username+IP pairs with lockout time and a `Clear` button. POST,
CSRF-protected. Writes `lock_cleared`. Renders nothing when nothing is locked.

## Export

`/security/export.txt`, `@admin_required`, `text/plain; charset=utf-8`,
filename `security-log-YYYY-MM-DD.txt`.

**Respects the filters, ignores the pagination.** Exporting only the visible
100 rows would be a trap: filtering to a user and downloading would produce a
fragment that looks complete.

Every file opens with a header block:

```
NIC Rajasthan — MPR Portal security log
Generated   2026-09-18 14:32 IST by admin.one
Filter      user contains "dio.jaipur"; action: all
Events      1–63 of 63
```

An exported log that does not state what was excluded is misleading evidence.
A reader months later must be able to tell whether they hold everything or a
slice.

**There is no row cap.** The export returns every row matching the filter. If a
cap is ever added it must be stated in the header block — a silent truncation
in a security export is the worst available failure.

Body: one line per event, aligned on the short fixed-width fields, with
`detail` last and free-form since its length varies most.

Written as a small dedicated function, not folded into `exports.py` — `tables()`
there is shaped around "one reporting month, four writers", which a filtered
event stream is not.

**Known ceiling:** the response is built in memory. Adequate for years at this
volume. If it becomes slow, `StreamingHttpResponse` is a one-line swap; mark it
with a `ponytail:` comment rather than building streaming now.

## Testing

New file `accounts/tests/test_security.py`, matching the existing split-by-
concern test layout.

The four that matter most, each being a case where a plausible implementation
is silently wrong:

1. A failed login for a **username that does not exist** records the attempted
   string. The most important row type, and the one a FK-only model drops.
2. Deleting a user leaves their events **readable**, not a row of nulls.
3. A non-admin is refused **both** `/security/` and the export URL.
4. A spoofed `X-Forwarded-For` does **not** change the logged IP.

Then: login/logout/password rows; role change captures old → new; lockout fires
after the limit and actually blocks; admin clear writes `lock_cleared` and
restores access; export respects filters and ignores pagination.

### Risk: axes may break the existing suite

The existing 78 tests include real posts to the login view, among them
`test_wrong_captcha_blocks_login`, which fails deliberately. Once axes counts
failures, tests sharing a username could lock one another out, producing
failures that look random and depend on test ordering.

Mitigation: `AXES_ENABLED = False` for tests, re-enabled explicitly in the
lockout tests. Verify separately whether a captcha rejection even reaches
`authenticate()` — if `CaptchaAuthenticationForm` fails before that point, axes
never observes it, which is itself worth knowing.

## Future, deliberately deferred

- Pruning or archiving, if the table ever grows enough to matter.
- Letting users see their own recent sign-ins (considered, not chosen).
- Extending readership to SIO / Group Leaders.
- Alerting on suspicious patterns — needs email, which is not configured.
- A separate MPR-entry change log, if "who edited my entry" is wanted.
