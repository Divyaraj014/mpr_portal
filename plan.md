# MPR Portal — Project Plan

Monthly Project Report (MPR) portal for **National Informatics Centre (NIC), Rajasthan**.
Replaces the current manual MPR compilation. NIC officers log in, fill their part of
the monthly data, lock it; the data is then compiled and exported.

- **Stack:** Django + PostgreSQL, server-rendered templates (no SPA).
- **Status:** v1 feature-complete. Auth, master data, monthly fill, lock/unlock, the
  monitoring screen and the four exports are working.
- **Last updated:** 2026-07-26

---

## 1. Roles

Every NIC employee gets a login. A user can hold **more than one** role.

| Role | Purpose |
|------|---------|
| **Admin** | Full control: create users, reset passwords, activate/deactivate, assign roles, assign projects/districts, create MPR periods, handle unlock requests. |
| **SIO / Additional SIO** | Read-only monitoring. See what everyone has filled/locked; view all reports. |
| **Project Leader (PL)** | Fill + lock MPR data for the **projects** assigned to them. |
| **District Informatics Officer (DIO)** | Fill + lock MPR data for the **districts** assigned to them. |

A user can be **PL and DIO at once** — they then fill both a project set and a district set.
The dashboard shows only options relevant to the user's roles.

---

## 2. Login & account lifecycle

- **Login ID = email prefix** (e.g. `divyaraj.work` from `divyaraj.work@...`). Unique.
- **Login page has a captcha** — session-based **image captcha** (Pillow-drawn PNG,
  5 characters + noise). Zero external service; works on the internal NIC network.
- Account flow:
  1. Admin creates the account with a **temporary password**
     (`must_change_password=True`, `is_activated=False`).
  2. Admin shares the login ID + temp password with the employee.
  3. On **first successful login**, the user is forced to set a new password.
  4. That flips `is_activated=True` — this is how activation "reflects" to admin.
- Later password resets: user can change their own; admin can force-reset.

---

## 3. Data model (core tables)

### User
Custom user model extending Django's `AbstractUser`, carrying the 7 known fields:
`employee_code, name, phone, ip_phone, email, place_of_posting, designation`,
plus role flags, `must_change_password`, `is_activated`.

### Master data (admin-managed)
- **Project** — owned by one Project Leader. Fields: `name`, unique **`prism_id`**,
  **category** (Central / State), **department** (FK to `Department`), **targeted user**
  (free text), **URL**.
- **Department** — admin-managed list, so the department dropdown stays editable.
- **District** — a district owned by one DIO.
- Admin assigns projects/districts to users.

### MPR period & locking
- **MPRPeriod** — month/year + **due date** + open/closed, created by admin. The due date
  can be set or extended later from **Manage → Reporting months**, without reopening
  anything; the new date shows on everyone's month page immediately.
- For a period, a user fills **one report per owned project and per owned district**.
- **Lock unit = per user, per month.** One button freezes ALL of that user's
  project + district reports for the month → read-only.
- **MPRLock** — the row existing *is* the lock, so approving an unlock just deletes it.
  Carries `unlock_requested` + the user's `unlock_reason`. No history is kept.
- Every "can this person still edit?" question goes through one helper,
  `views._editable(user, period)` = period open **and** not locked by that user. Adding a
  new editing view means calling it, not repeating the condition.

### The MPR sections
Two shapes:

**A. Entry sections (7)** — a list of rows, one `MPREntry` table with a `kind` field.
Each kind uses only some columns; `MPREntry.FIELDS` (and `LABELS`) declares which,
and forms/admin read that map — a new section is one dict entry.

Every row also carries a **`scope`** (`district` or `project`) and, for project rows, the
**`project`** it belongs to. A month is not one long form: it is **one report per thing the
user owns** — one district report, plus one per project they lead — each on its own page.
`views._my_reports(user)` returns that list as `(scope, project)` pairs and is the one place
that says which reports a user owes; nothing can be filed into a pair that isn't in it.

`project` is set from the report the row was filed in, never chosen in a dropdown, so it is
not in `MPREntry.FIELDS`. A Project Leader with no project assigned owes no report at all.

Common to **DIOs and Project Leaders**:

| Section (`kind`) | Fields |
|---|---|
| Major events planned (`event`) | event category (Inauguration / Launch / Press coverage / Others), event date, project, description, remark |
| Review by Hon'ble Minister / Others (`review`) | description, date of review, important suggestions, remarks |
| Major training (`training`) | topic, from date, to date, no. of participants, target user, remarks |
| Major awards (`award`) | award level (International / National / State / District / Local), award title, award date, description, photo |
| Significant activities planned (`significant`) | brief description |
| New activities planned (`new_activity`) | brief description |

**Project Leader only** (`MPREntry.PL_ONLY_KINDS`):

| Section (`kind`) | Fields |
|---|---|
| Major enhancements (`enhancement`) | title, description, remark |

**B. Project parameter section** — the "Existing" table, same for Central and State
projects. Because projects differ (Transport tracks "challans issued", another tracks
something else), parameters are per project:
- **ProjectParameter** — admin defines each project's recurring rows **once**, in the
  "Monthly parameters" box on the project edit page. Add is a name; `order` is assigned
  (max + 1) so rows land at the bottom. Names are unique per project, case-insensitively.
  Remove is a hard delete behind the standard confirm page, which states how many months
  of figures go with it — that's the only destructive path, so it's the loud one.
- **ParameterValue** — per period, per parameter: **previous month**, **reporting month**,
  **cumulative since inception**. Stored as text (values range from counts to "NA" / "₹ 2.4 Cr").

> Design note: only projects get the parameter treatment. The 7 entry sections stay one
> flexible table — no custom-field sprawl. Split a section out only if it grows real structure.

---

## 4. Workflows

**Admin onboards a user**
Create user → set roles → assign projects/districts → (for projects) define parameters
→ share login ID + temp password.

**Dashboard** (built)
One block per thing the signed-in user can act on, and nothing else. Blocks stack by role,
so an admin who also holds a DIO role gets their own report *and* the month's progress:

| Block | Who | Says |
|---|---|---|
| Subtitle | everyone | The open month and the due date as time left: "Due in 9 days" / "Due today" / "3 days overdue" |
| Your report | PL / DIO | Entries recorded, locked state, one button into the month |
| *N* of *M* locked | admin + SIO | How many have finished, how many haven't started, unlock requests pending, link to Reports |
| Accounts never signed into | admin | Only when there are any |

No month open → one card saying so, pointing where to fix it.

**User fills an MPR** (built)
Log in (captcha) → dashboard shows the open month and a "Fill your report" button → the
**month page**:

- Owes **one** report (a DIO, or a PL with a single project)? It opens straight into that
  report's sections. No chooser, no extra click.
- Owes **several**? The month page is a short list of them — "District report", then each
  project by name with its category and PRISM ID, each showing its entry count. Pick one
  and fill it on its own page.

A report page is its sections as collapsible blocks, each with its rows and an "Add"
button; a project report ends with that project's figures table (previous month carried
forward from last period). Then **Lock month**, back on the month page, which freezes every
report at once. Locked data is read-only; request unlock if needed.

A closed month hides every Add/Edit/Delete control and disables the figures fields.

| Screen | URL | Template |
|---|---|---|
| My months | `/mpr/` | `mpr_list.html` |
| One month (report list, or the single report) | `/mpr/<period>/` | `mpr_month.html` |
| One report | `/mpr/<period>/report/district/`, `/report/project/<project>/` | `mpr_report.html` + `_mpr_sections.html` |
| Add / edit one row | `/mpr/<period>/section/<kind>/[add\|<pk>]/?scope=&project=` | `mpr_entry_form.html` |
| Project figures | `/mpr/<period>/project/<project>/` | `mpr_parameters.html` |
| Lock (confirm, then POST) | `/mpr/<period>/lock/` | `mpr_lock_confirm.html` |
| Request unlock | `/mpr/<period>/unlock-request/` | (POST only) |
| Reports index | `/reports/?period=<pk>` | `reports.html` |
| Filing status | `/reports/status/` | `report_status.html` |
| One category's data | `/reports/data/<key>/` | `report_table.html` |
| Reopen a locked month | `/reports/unlock/<lock>/` | (POST only, admin) |
| Export a month, or one category | `/reports/<period>/export.<fmt>[?only=<key>]` | `export.html` (PDF only) |

**Locking and unlocking** (built)
The month page ends with "Lock month", which opens a confirm page first: it says what is
being submitted and that **changing anything later means requesting an unlock and waiting
for an admin**. GET states the cost, POST locks — no JS dialog to dismiss or bypass.
Once locked, every Add/Edit/Delete disappears, the
figures fields are disabled, and a banner offers "Request unlock" with a reason box. The
request shows up on Reports, where an admin clicks **Reopen** (deletes the lock row).

**SIO / Addl-SIO monitors** (built)
**Filing status** (`/reports/status/`, admin + SIO) — one row per PL/DIO showing
status (Not started / In progress / Locked / Unlock requested), a count per section, and
how many project figures were entered. Three tiles summarise users, locks and pending
requests; pending requests are also listed in full underneath with their reasons. Only
admins see the Reopen button; SIO is read-only.

**Compile & export** (built)
Reports is the compilation module, admin + SIO only. `/reports/` is an index: pick a month,
then open one of ten reports. **Filing status** sits on top (who has filled and locked, the
unlock requests waiting on you), then **one report per category** — the 7 sections plus
Project parameters — each listed with its row count so you can see where the month's data
is before opening anything. Every report page downloads on its own in all four formats;
the index downloads the whole month in one file.

---

## 5. Exports (v1)

`accounts/exports.py`. `tables(period, only=None)` gathers the whole month **once** — one
block per entry section (all users, `Filed by` and `Project` first) plus a **Project
parameters** block — as `{key, title, headers, rows}` with every cell already a string.
`only` narrows it to one category.

That same block feeds **both** the on-screen report and the download, so a report and its
export can't drift apart: `report_table.html` renders `headers`/`rows` as a grid and never
learns what a training or an award is. The writers only format; none of them touches the
ORM. A new format is one function plus one `WRITERS` entry; a new section is still one dict
entry and it appears everywhere.

| Format | Library | Shape |
|--------|---------|-------|
| Excel (.xlsx) | openpyxl | One sheet per block, bold frozen header, sized columns |
| PDF | `export.html` → WeasyPrint | A4 landscape, page numbers, standalone CSS |
| Word (.docx) | python-docx | Heading + Table Grid per block |
| CSV | stdlib `csv` | One file, blocks stacked; `utf-8-sig` so Excel keeps ₹ |

Empty sections still get their block, so the file shape is the same every month.

> WeasyPrint needs Pango/Cairo from the OS. On macOS the Homebrew copies exist but aren't
> on dyld's path — run with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`. If they can't
> load, the PDF link returns a 503 naming the missing libraries instead of a blank 500.

---

## 6. Scope

**In v1**
- Three account types, multi-role users, role-aware dashboards.
- Login ID = email prefix, captcha, first-login activation, password reset.
- Admin user/role/project/district management.
- Monthly MPR periods with due dates; fill; whole-month lock; unlock requests.
- 9 sections (7 narrative + 2 structured project sections with per-project parameters).
- Export to xlsx, PDF, docx, CSV.

**Deliberately NOT in v1** (clean add-ons later)
- Email/SMS notifications.
- Audit logs / change history.
- Per-parameter validation rules beyond basic types.
- Bulk user import.

---

## 7. Suggested build order

1. ✅ Project skeleton + custom User model + PostgreSQL + auth.
2. ✅ Login page with captcha + first-login password change + activation flag.
3. ✅ Admin: user CRUD, role assignment, password reset (lean on Django admin).
4. ✅ Master data: Project (+ department / targeted user / URL), District, assignment,
   ProjectParameter setup (on the project edit page).
5. ✅ MPRPeriod + due dates; month page; entry add/edit/delete per section.
6. ✅ Project parameter values (figures table, previous month carried forward).
7. ✅ Lock / unlock-request flow.
8. ✅ Role-aware dashboards (PL/DIO fill views; SIO + admin monitoring via Reports).
9. ✅ Export layer (xlsx, PDF, docx, CSV) off one serializer.

---

## 8. UI conventions

One design language, defined once in `accounts/templates/accounts/base.html`. Extend it;
don't start a second one.

- **Type:** Figtree for UI, EB Garamond for page titles and figures. **Color:** NIC navy
  `#1B4B8A` on a `#F0F4F9` well. **Shape:** pill = interactive, 16px = cards and tables,
  12px = inputs.
- Buttons: `.btn` (navy, one primary action per screen), `.btn-outline` (secondary, e.g.
  the per-section Add), `.btn-ghost` (tertiary / row actions).
- Interaction uses native elements first: `<details>` for the section accordions, the
  account menu and the sidebar's **Manage** group (Users / Projects / Districts / Reporting
  months, opened by default while you're on one of them), `<input type=date>` for dates.
  JS only closes menus.
- Stacked page blocks (`.card`, `.table`, `.tiles`) get their 16px gap from one
  adjacent-sibling rule in `base.html`. Pages don't set their own `margin-top` — that's how
  the rhythm drifted apart in the first place.
- One `MPREntry` row renderer serves all 7 sections: `headline` plus `cells()` (label,
  value) driven by `MPREntry.FIELDS`. New section = one dict entry, no new template.
  `MPREntry.label()` / `.value()` are the shared primitives underneath — the exports use
  the same two, so a heading only ever needs fixing in one place.
- Dense monitoring tables get short column labels (`MPREntry.SHORT_LABELS`), right-aligned
  tabular numbers, and horizontal scroll rather than a squeezed layout. Name and status
  columns come first so the actionable part is visible without scrolling.
- **Every `.trow` is its own CSS grid**, so a track list has to be deterministic: fixed
  **pixel** widths plus an explicit `min-width`. `auto` and `max-content` resolve per row;
  `ch` resolves against each element's own font-size, and the header is 12px against the
  rows' 14px, so both drift the columns further out of line with each column. Report tables
  size their tracks from the data (`views._column_layout`, the same clamp `_xlsx` uses),
  and the monitoring grid's track list comes from the section count rather than a
  hard-coded `repeat(7, …)`.
- Download controls sit **above** long tables, not below them. A report with a screenful of
  rows shouldn't hide its own export behind a scroll.
- A list row that leads somewhere **is** the link (`a.rowlink`), rather than parking an
  "Open" word at the far right: the label you read is the target you hit, it's one tab
  stop, and it gets a visible focus ring. Rows with nothing in them recede instead of
  disappearing, so the shape of the month stays constant while the full ones stand out.

## 9. Open items

- Export layout is one block per section with everyone's rows together, `Filed by` as the
  first column. Confirm whether the SIO office instead wants it split per district / per
  project — that's a regrouping inside `exports.tables()`, the writers don't change.
- Confirm designations → default role mapping (auto-suggest roles at user creation?).
- Data retention: how many past periods stay editable/visible.
- Creating a period, closing one, and departments are still Django admin (`/admin/`) jobs —
  only the due date moved into the custom UI. Move the rest if that becomes awkward.
- Parameters can be added and removed, not renamed or reordered, from the project page.
  Renaming is a live edit of a heading past months already reported under; reordering
  needs a drag handle. Both are additions to the same box when asked for.
- Projects are now split one report per project, but a DIO holding two districts still
  files **one** district report covering both. Same fix as projects when it's wanted:
  a `district` FK on `MPREntry` and one more entry in `_my_reports()`.