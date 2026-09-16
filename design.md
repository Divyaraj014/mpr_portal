# MPR Portal — Design System

Source of truth for the visual layer. The actual tokens live in the `:root` block of
[`accounts/templates/accounts/base.html`](mpr_raj/accounts/templates/accounts/base.html) —
this doc explains the intent so the two don't drift. If you change a value, change it in
`base.html`; this file only records the *why*.

- **Audience:** internal NIC Rajasthan officers (admin, SIO, PL, DIO). Trust-first, not marketing.
- **Style:** minimal, calm, government-appropriate. One accent (NIC navy), generous whitespace.

---

## 1. Type

One family: **Inter** (SIL Open Font License 1.1), self-hosted from `static/accounts/fonts/`
and set once as `--font` in `app.css`. It is built for screens at 12–14px, has tabular
figures for the number columns (`.tnum`), and carries the rupee sign. Hierarchy comes from
size and weight (400 body, 500 labels, 600 headings and figures), never a second family.
Inter is variable in optical size, so large headings tighten on their own — no manual
letter-spacing. Body base is `14px / 1.5`.

| Role | Size / weight | Class |
|------|---------------|-------|
| Page title | 24px / 600 | `h1.pg`, `.page-head .t` |
| Stat tile value | 28px / 600, tabular | `.tile .v` |
| Card title | 18px / 600 | `.t-title` |
| Body, table cells | 14px / 400–600 | `.t-key`, `.t-val`, … |
| Notes, fine print | 13px / 12px | `.t-note`, `.t-fine` |

The PDF export embeds the same Inter files (see `export.html`).

**Licensing.** Every font shipped must have its licence file next to it in
`static/accounts/fonts/`: `OFL-Inter.txt` (Inter) and `LICENSE-MaterialSymbols.txt`
(Apache 2.0, the icons). Both allow government use, self-hosting, and PDF embedding at no
cost. Don't add a commercial font (Helvetica, Segoe UI, Calibri, Gotham, …) as a file. If
a Hindi UI is added, use **Noto Sans Devanagari** (also OFL) alongside Inter.

---

## 2. Color

One accent. Neutrals are warm-grey. No second accent anywhere.

| Token | Hex | Use |
|-------|-----|-----|
| `--navy` | `#1B4B8A` | primary accent — buttons, links, active nav, focus ring |
| `--navy-d` | `#16406F` | button hover |
| `--navy-tint` | `#E7EEF8` | active nav bg, card hover bg |
| `--ink` | `#1F1F1F` | primary text |
| `--slate` `--muted` `--faint` | `#444746` `#5F6368` `#9AA0A6` | secondary → placeholder text |
| `--border` | `#E1E3E1` | hairlines, input borders |
| `--bg` | `#F0F4F9` | content well + auth page background |
| `--surface` | `#FFFFFF` | cards, sidebar, topbar |
| `--green` / `--red` | `#146C43` / `#B3261E` | status badges only (Active / Disabled) |

Status green/red are **semantic state**, not decoration — they appear only in the
`.status` pill badges.

---

## 3. Shape

One radius rule, documented at the top of the `<style>` block:

- **Pill (`999px`)** — anything interactive: buttons, ghost buttons, nav items, status badges, avatar/logo circles.
- **16px** — containers: cards, tables, tiles.
- **12px** — inputs.
- **24px** — the big surfaces: auth box, the content well's top corner.

Don't introduce a 4th radius without a reason.

---

## 4. Layout

- **App shell** (`app.html`): white sidebar (256px) + white topbar framing a grey rounded
  content well (`.content`, `--bg`, `border-radius: 24px 0 0 0`). Content max-width 1040px, centered.
- **Auth pages** (`login`, `password_change`): centered white card (max 400px) on the grey bg.
- **Sidebar nav:** 40px pills; icons and labels share `--slate`. Active item = navy-tint pill,
  navy label, and a *filled* icon (Material Symbols FILL axis). Staff links sit under an
  "Administration" heading, which becomes a thin rule on the collapsed 72px icon rail. The
  collapse button is the menu icon in the top bar; every nav icon is centred 36px from the
  left in both states.
- **Mobile (`≤720px`):** sidebar collapses to a horizontal row, tiles stack to one column,
  content well corners round on top.

---

## 5. Motion

Minimal by intent (trust-first, `MOTION_INTENSITY` low). Only:

- `.15s` color/border/shadow transitions on interactive elements.
- Buttons `scale(.98)` on `:active` (tactile press feedback).
- All transitions disabled under `prefers-reduced-motion: reduce`.

No scroll animation, no entrance effects, no parallax. This is a data-entry tool.

---

## 6. Assets & known constraints

- **Logo:** `accounts/static/accounts/nic-logo.png`, shown on login, password, and sidebar.
  Prefer a transparent PNG (or SVG). Referenced via `{% static %}`.
- **Fonts are self-hosted** (`fonts.css`), because the internal NIC network can't reach the
  Google CDN. `fonts.css` lists the URLs to re-download them from.
- **Static in production:** `DEBUG=True` serves app static files directly. For `DEBUG=False`,
  run `collectstatic` behind a static file server.

---

## 7. Rules of thumb

- New page? Extend `app.html` (in-shell) or `base.html` (standalone). Reuse `.card`, `.table`,
  `.tile`, `.status`, `.btn` — don't invent parallel styles.
- Prefer whitespace and hairlines (`--border`) over shadows and boxes for grouping.
- Every list needs an empty state (see the `{% empty %}` block in `user_list.html`).
- One accent, one type pairing, one radius system. Consistency is the aesthetic.
