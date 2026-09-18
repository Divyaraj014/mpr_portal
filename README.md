# MPR Raj

Monthly Progress Report portal for NIC Rajasthan. Officers file their month's
activity against a reporting period; the SIO office and Group Leaders compile it
and export district- and project-wise reports.

## Requirements

- Python 3.12
- PostgreSQL
- [uv](https://docs.astral.sh/uv/)
- WeasyPrint's native libraries for PDF export — on macOS, `brew install pango gdk-pixbuf libffi`

## Setup

```bash
uv sync
cp mpr_raj/.env.example mpr_raj/.env   # then fill in SECRET_KEY and DATABASE_URL
```

Generate a secret key:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Then migrate, seed the district list, and create the first admin:

```bash
cd mpr_raj
uv run python manage.py migrate
uv run python manage.py seed_districts
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

## Layout

```
mpr_raj/              repo root — pyproject.toml, uv.lock, data/
└── mpr_raj/          Django root — manage.py, .env
    ├── mpr_raj/      settings, root urlconf, wsgi/asgi
    └── accounts/     the application
        ├── models.py      users, districts, projects, periods, entries, locks
        ├── views/         home · master · monthly · reporting
        ├── forms.py       entry and master-data forms
        ├── exports.py     XLSX / DOCX / PDF report writers
        ├── captcha.py     login captcha
        ├── middleware.py  forced password change
        ├── templates/     and static/
        └── tests/
```

`accounts` holds the whole domain, not just authentication. It is one app on
purpose — the models are tightly coupled and splitting them would buy migration
surgery and nothing else.

## Roles

A user may hold several at once.

| Role | Flag | Can do |
|---|---|---|
| Admin | `is_staff` | everything, including approving unlock requests |
| SIO / Addl. SIO | `is_sio` | view compilation screens |
| Group Leader | `is_gl` | view compilation screens |
| Project Leader | `is_pl` | file project-scoped entries |
| DIO | `is_dio` | file district-scoped entries |

Login ID is the email prefix; new accounts must change their password on first
sign-in.

## Tests

```bash
cd mpr_raj && uv run python manage.py test
```

## Lint

```bash
uv run ruff check .
```

No auto-formatter. The code is fill-wrapped by hand — packed to the 110-column
limit, then wrapped — which reads better for the long literal lists here (the 41
Rajasthan districts are 8 scannable lines, not 43). `ruff format` is Black-style
and cannot produce that, so `ruff check` lints but nothing rewrites layout.

## Running it on a LAN

For letting colleagues reach the portal from other machines on the office
network. This is the `runserver` path — fine for testing and demos, not for
real use; see Deployment below for that.

On the server, in `mpr_raj/.env`:

```
DEBUG=True
HTTPS=False
ALLOWED_HOSTS=localhost,127.0.0.1,<this machine's LAN IP>
```

`ip addr show | grep "inet "` gives you the address. Then:

```bash
cd mpr_raj
uv run python manage.py runserver 0.0.0.0:8000
```

`0.0.0.0` is the part that matters — the default binds to localhost only, so
the port is open but nothing outside the machine can reach it.

Fedora blocks the port by default. To open it for this session:

```bash
sudo firewall-cmd --add-port=8000/tcp
```

Add `--permanent` and re-run `sudo firewall-cmd --reload` to keep it across
reboots. Only do that on a network you trust — there is no TLS here, so
passwords cross the LAN in clear text.

Colleagues then use `http://<LAN IP>:8000/`.

### Why DEBUG=True for this

With `DEBUG=False`, `runserver` stops serving static files and every page
arrives unstyled. `DEBUG=True` avoids that, at the cost of showing a full
traceback — including settings — to anyone who triggers an error. That trade is
fine on a trusted network for testing and wrong anywhere else.

To run with `DEBUG=False` instead, set `HTTPS=False` as well (or Django
redirects everything to a port nothing is serving), run `collectstatic`, and
serve `staticfiles/` with a real web server rather than `runserver`.

### If it still will not connect

- `DisallowedHost` in the log — the address you typed is not in `ALLOWED_HOSTS`.
- Connects from the server but not from other machines — firewall, or you left
  off `0.0.0.0`.
- Redirects to `https://` and fails — `DEBUG=False` with `HTTPS` unset.
- Sign-in fails five times and then keeps failing — that is the lockout working.
  It clears after 30 minutes, or an admin can clear it from the security log.

## Deployment

gunicorn behind nginx, on Fedora. Config files live in `deploy/` and assume the
project is at `/srv/mpr_portal` — change the paths in both files together if it
is somewhere else.

### 1. Put the project somewhere nginx can reach

```bash
sudo useradd --system --home /srv/mpr_portal mpr
sudo git clone https://github.com/Divyaraj014/mpr_portal.git /srv/mpr_portal
cd /srv/mpr_portal && sudo -u mpr uv sync
```

A clone under `/home` will not work: nginx runs as its own user and cannot
traverse another user's home directory. That failure looks like a 403 on every
static file while the pages themselves load.

### 2. Configure

`mpr_raj/.env`:

```
DEBUG=False
HTTPS=False
SECRET_KEY=<generate a fresh one>
DATABASE_URL=postgres://...
ALLOWED_HOSTS=mpr.local,192.168.1.42
AXES_IPWARE_PROXY_COUNT=1
```

`AXES_IPWARE_PROXY_COUNT=1` is safe **only** because `deploy/nginx-mpr-portal.conf`
overwrites `X-Forwarded-For`. The two go together — see below.

```bash
cd /srv/mpr_portal/mpr_raj
sudo -u mpr uv run python manage.py migrate
sudo -u mpr uv run python manage.py collectstatic --noinput
sudo -u mpr uv run python manage.py check --deploy
```

`check --deploy` will report the cookie and SSL warnings, because `HTTPS=False`.
That is expected while there is no TLS, and those warnings are the reason to
add it.

### 3. Install the services

```bash
sudo cp deploy/mpr-portal.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mpr-portal

sudo dnf install nginx
sudo cp deploy/nginx-mpr-portal.conf /etc/nginx/conf.d/mpr-portal.conf
sudo nginx -t && sudo systemctl enable --now nginx
```

### 4. SELinux and the firewall

Fedora enforces SELinux, and both of these fail **silently from nginx's point of
view** — you get a 502 or a 403 with nothing obviously wrong in the config.

```bash
# Let nginx open a connection to gunicorn. Without this: 502 on every page.
sudo setsebool -P httpd_can_network_connect 1

# Let nginx read the static and media trees outside /var/www. Without this: 403
# on every stylesheet while the HTML itself loads, so the site appears unstyled.
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/mpr_portal/mpr_raj/(staticfiles|media)(/.*)?"
sudo restorecon -Rv /srv/mpr_portal/mpr_raj

sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

`semanage` comes from `policycoreutils-python-utils` if it is missing.

When something breaks, `sudo ausearch -m avc -ts recent` shows what SELinux
denied — far faster than guessing.

### 5. Check it

```bash
systemctl status mpr-portal nginx
journalctl -u mpr-portal -f     # gunicorn's real errors; nginx only shows 502
curl -I http://192.168.1.42/
```

Django's own log rotates into `mpr_raj/logs/mpr.log`; gunicorn's goes to the
journal.

### Updating

```bash
cd /srv/mpr_portal && sudo -u mpr git pull && sudo -u mpr uv sync
cd mpr_raj
sudo -u mpr uv run python manage.py migrate
sudo -u mpr uv run python manage.py collectstatic --noinput
sudo systemctl restart mpr-portal
```

nginx only needs reloading if its own config changed.

### Client addresses in the security log

Out of the box the security log records `REMOTE_ADDR`. A client cannot forge
that, but behind a proxy it is the *proxy's* address, so every row reads the
same and the IP column is worthless.

To record real client addresses, both of these must be true:

1. nginx **overwrites** the header rather than appending to whatever the client
   sent — `proxy_set_header X-Forwarded-For $remote_addr;`. The config in
   `deploy/` does this.
2. `AXES_IPWARE_PROXY_COUNT` in `.env` is set to the number of proxies actually
   in front of Django — `1` for the single nginx above.

Do one without the other and the logged IP becomes forgeable: a client can send
its own `X-Forwarded-For` and choose what the security log says about it. An
address you cannot trust is worse than none, because it is evidence people
believe.

The trap is `$proxy_add_x_forwarded_for`, which appears in most nginx examples
you will find. It *appends* to the client-supplied header rather than replacing
it, so with a proxy count of 1 the address Django reads is the one the client
sent. Use `$remote_addr`.

If you add a second proxy — a load balancer in front of nginx — the count has to
change with it. Leave it at `0` any time you are unsure; a blank column is
better than a confident wrong one.
