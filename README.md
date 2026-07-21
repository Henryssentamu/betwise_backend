# Betting Investment Advisory Platform — Backend

Django + MySQL API. Everything below has been tested end to end (signup,
login, age verification, season planning, the recommendation engine, promo
codes) against a live server. MySQL and Pesapal specifically could not be
tested in the build sandbox (no MySQL server, no live Pesapal credentials)
— those two integration points are the first things to verify on your
machine.

## 1. Prerequisites

- Python 3.11+
- MySQL 8+ running locally (or accessible remotely)
- A Pesapal merchant account (sandbox is fine to start — https://developer.pesapal.com)
- A Football-Data.org API key (free tier: https://www.football-data.org/client/register)

## 2. Setup

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# now edit .env: DB credentials, Pesapal keys, Football-Data key
```

Create the MySQL database (name must match `DB_NAME` in `.env`):

```sql
CREATE DATABASE betwise CHARACTER SET utf8mb4;
CREATE USER 'betwise_user'@'localhost' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON betwise.* TO 'betwise_user'@'localhost';
```

## 3. Run migrations and seed data

```bash
python manage.py migrate
python manage.py seed_initial_data      # subscription plans, betting partners, background job schedule
python manage.py createsuperuser        # your admin login
```

`seed_initial_data` also registers the background jobs (match sync, form
recompute, recommendation generation/evaluation) with django-celery-beat,
so once Celery is running (step 7) they fire on their own — no manual
admin step needed.

## 4. Register the Pesapal IPN (one time, per environment)

Your `PESAPAL_IPN_URL` in `.env` must be a publicly reachable URL (use
ngrok or similar for local testing, since Pesapal needs to reach it).

```bash
python manage.py register_pesapal_ipn
# copy the printed ipn_id into .env as PESAPAL_IPN_ID, then restart
```

## 5. Pull in real match data (optional first run)

`sync_matches` now also runs automatically every 5 minutes via Celery beat
once you've completed step 7, so this manual run is just to get data
immediately instead of waiting for the first scheduled tick:

```bash
python manage.py sync_matches
```

This respects the free-tier rate limit (10 req/min) by pacing requests —
if a league gets rate limited it's skipped and retried on the next run
rather than crashing.

## 6. Run the server

```bash
python manage.py runserver
```

API is now live at `http://localhost:8000/api/`. Admin at `/admin/`.

**Note:** `runserver` on its own only serves the API — it does **not**
start Celery, so match syncing and recommendation generation won't run.
For those you need step 7 as well.

## 7. Background jobs

Match syncing, form recalculation, recommendation generation, and outcome
evaluation are Celery tasks (`matches/tasks.py`, `recommendations/tasks.py`),
already registered as periodic tasks by `seed_initial_data` — nothing to
configure in Django admin, ever. You just need the worker + beat
*processes* running alongside the web server. Requires Redis
(`CELERY_BROKER_URL` in `.env`; install locally with
`sudo apt install -y redis-server && sudo systemctl enable --now redis-server`).

### Local development

Running `celery worker` and `celery beat` by hand means juggling three
terminals (server, worker, beat). Instead, use:

```bash
./dev.sh
```

This starts `runserver`, `celery worker`, and `celery beat` together in
one process group and stops all three together on Ctrl+C. This is the
command you should actually run day to day locally — not plain
`runserver`.

The schedule can still be tweaked anytime under **Periodic Tasks** in
Django admin (e.g. to change intervals) without a deploy.

### Production

`./dev.sh` is dev-only (it dies when your terminal closes, and has no
crash recovery). In production you want each process supervised so it
survives crashes and server reboots without anyone SSHing in to restart
it by hand. Example `systemd` units are provided in
[`deploy/systemd/`](deploy/systemd/):

- `betwise-web.service` — Gunicorn (`config.wsgi:application`)
- `betwise-celery-worker.service` — Celery worker
- `betwise-celery-beat.service` — Celery beat scheduler

To install them on a systemd-based server (Ubuntu/Debian):

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
# edit each file: set the real deploy path (WorkingDirectory, EnvironmentFile,
# ExecStart) and the system user that should run the process
sudo systemctl daemon-reload
sudo systemctl enable --now redis-server betwise-web betwise-celery-worker betwise-celery-beat
```

`enable --now` both starts them immediately and registers them to start
automatically on every boot. Because `Restart=always` is set, systemd
also restarts any of the three if they crash — so once this is set up,
nobody needs to manually start the server, the worker, or the beat
scheduler again, on a reboot or otherwise.

Check status/logs the same way as any systemd service:

```bash
sudo systemctl status betwise-celery-worker
sudo journalctl -u betwise-celery-beat -f
```

If you deploy behind a container platform instead (Docker/Kubernetes),
the same three processes just become three services/containers sharing
the same image and `.env`, each running one of the `ExecStart` commands
above — the principle (three independent long-running processes, not
one-off commands) is identical.

## Key endpoints

| Endpoint | Method | Notes |
|---|---|---|
| `/api/auth/signup/` | POST | Age-gated (18+), returns JWT immediately |
| `/api/auth/login/` | POST | JWT login |
| `/api/auth/me/` | GET/PATCH | Profile |
| `/api/auth/plans/` | GET | Public, no auth needed |
| `/api/matches/upcoming/` | GET | Fixture list |
| `/api/matches/<id>/` | GET | Full reasoning detail |
| `/api/recommendations/` | GET | Requires active subscription |
| `/api/season-plans/` | POST | Creates plan + weekly targets |
| `/api/season-plans/active/pace/` | GET | Pace dashboard + course correction |
| `/api/promo-codes/validate/` | POST | Live discount preview at checkout |
| `/api/checkout/` | POST | Creates Pesapal order, returns redirect_url |
| `/api/payments/pesapal/ipn/` | GET | Pesapal calls this — do not call manually |
| `/api/admin/dashboard-stats/` | GET | Staff only — the 4 KPI cards |

## What's deliberately not built yet

- Corners / BTTS / over-under recommendation evaluation (model only
  scores 1X2 outcomes for now — see `evaluate_recommendation_outcome` in
  `engine.py`)
- Affiliate link tracking on betting partners (editorial list only, per
  the MVP decision)
- Push notifications for course-correction nudges (the message is
  generated by `suggest_course_correction()` — wiring it to a notification
  service is the next step)
