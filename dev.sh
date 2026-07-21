#!/bin/bash
# Runs the Django dev server together with the Celery worker and beat
# scheduler, so background jobs (match sync, recommendations, form
# recompute) actually fire locally instead of needing three manual
# terminals. Requires Redis running (CELERY_BROKER_URL in .env).
set -e

cleanup() {
    echo "Stopping..."
    kill $(jobs -p) 2>/dev/null
}
trap cleanup EXIT INT TERM

celery -A config worker -l info &
celery -A config beat -l info &
python manage.py runserver

wait
