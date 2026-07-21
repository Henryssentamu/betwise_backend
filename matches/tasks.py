"""
Scheduled sync job. Registered as a periodic task automatically by
`seed_initial_data` (see recommendations/management/commands/seed_initial_data.py)
so fixtures and results keep updating without anyone running
`python manage.py sync_matches` by hand.
"""
from celery import shared_task
from django.core.management import call_command


@shared_task
def sync_matches_task() -> None:
    call_command("sync_matches")
