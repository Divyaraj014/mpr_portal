# MPR Portal — Design System

Source of truth for the visual layer. The actual tokens live in the `:root` block of
[`accounts/templates/accounts/base.html`](mpr_raj/accounts/templates/accounts/base.html) —
this doc explains the intent so the two don't drift. If you change a value, change it in
`base.html`; this file only records the *why*.

- **Audience:** internal NIC Rajasthan officers (admin, SIO, PL, DIO). Trust-first, not marketing.
- **Style:** minimal, calm, government-appropriate. One accent (NIC navy), generous whitespace.

---

## 1. Type

Two families, loaded once via Google Fonts in `base.html`.

| Role | Font | Where |
|------|------|-------|
| Headings, stat numbers | **EB Garamond** (serif, 500/600) | page titles (`h1.pg`, `.page-head .t`), tile values, form card titles |
| Everything else | **Figtree** (sans, 400–700) | body, labels, buttons, nav, tables, badges |

Serif is deliberate here (brand brief), used **only** for display headings and numbers —
never for body or UI chrome. Body base is `14px / 1.5`. `system-ui` is the fallback if the
font CDN is unreachable (relevant on an internal NIC network — see §6).

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

- **App shell** (`app.html`): white sidebar (248px) + white topbar framing a grey rounded
  content well (`.content`, `--bg`, `border-radius: 24px 0 0 0`). Content max-width 1040px, centered.
- **Auth pages** (`login`, `password_change`): centered white card (max 400px) on the grey bg.
- **Sidebar nav:** active item = navy-tint pill. Only the current section is highlighted.
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
- **Fonts load from the Google CDN.** On an air-gapped internal NIC network this request
  fails and the UI falls back to `system-ui` — still legible, but not the intended type.
  To guarantee the fonts, self-host the woff2 files and swap the `<link>` for `@font-face`.
- **Static in production:** `DEBUG=True` serves app static files directly. For `DEBUG=False`,
  run `collectstatic` behind a static file server.

---

## 7. Rules of thumb

- New page? Extend `app.html` (in-shell) or `base.html` (standalone). Reuse `.card`, `.table`,
  `.tile`, `.status`, `.btn` — don't invent parallel styles.
- Prefer whitespace and hairlines (`--border`) over shadows and boxes for grouping.
- Every list needs an empty state (see the `{% empty %}` block in `user_list.html`).
- One accent, one type pairing, one radius system. Consistency is the aesthetic.
