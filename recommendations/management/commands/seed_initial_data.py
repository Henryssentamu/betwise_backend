"""
Run after the first migrate to populate subscription plans and the betting
partner list, so the app isn't empty on first run. Also registers the
background job schedule (sync_matches, form recompute, recommendation
generation/evaluation) with django-celery-beat, so they run on their own
once a Celery worker + beat process are up — no manual admin step needed:

    python manage.py seed_initial_data
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from accounts.models import SubscriptionPlan
from recommendations.models import BettingPartner


class Command(BaseCommand):
    help = "Seeds subscription plans and betting partners"

    def handle(self, *args, **options):
        plans = [
            {"name": "Casual Monthly", "tier": "casual", "billing_cycle": "monthly",
             "price_ugx": 15000, "features": ["Weekly recommendations", "Low & medium risk tiers"]},
            {"name": "Pro Monthly", "tier": "pro", "billing_cycle": "monthly",
             "price_ugx": 30000, "features": ["All risk tiers", "Full reasoning detail", "Priority support"]},
            {"name": "Pro Seasonal", "tier": "pro", "billing_cycle": "seasonal",
             "price_ugx": 220000, "features": ["All risk tiers", "Full reasoning detail", "Season-long pace tracking"]},
        ]
        for plan_data in plans:
            plan, created = SubscriptionPlan.objects.get_or_create(
                name=plan_data["name"], defaults=plan_data
            )
            self.stdout.write(
                self.style.SUCCESS(f"{'Created' if created else 'Already exists'}: {plan.name}")
            )

        partners = [
            {"name": "Bet365", "highlight_note": "Best overall odds coverage", "website_url": "https://www.bet365.com", "rank_order": 1},
            {"name": "Betking", "highlight_note": "Fast local payouts", "website_url": "https://www.betking.com", "rank_order": 2},
            {"name": "1xBet", "highlight_note": "Widest market variety", "website_url": "https://www.1xbet.com", "rank_order": 3},
        ]
        for partner_data in partners:
            partner, created = BettingPartner.objects.get_or_create(
                name=partner_data["name"], defaults=partner_data
            )
            self.stdout.write(
                self.style.SUCCESS(f"{'Created' if created else 'Already exists'}: {partner.name}")
            )

        periodic_tasks = [
            {"name": "Sync matches", "task": "matches.tasks.sync_matches_task", "every": 5},
            {"name": "Recompute team form", "task": "recommendations.tasks.recompute_all_team_form", "every": 60},
            {"name": "Generate recommendations", "task": "recommendations.tasks.generate_recommendations_batch", "every": 60},
            {"name": "Evaluate finished recommendations", "task": "recommendations.tasks.evaluate_finished_recommendations", "every": 15},
        ]
        for job in periodic_tasks:
            schedule, _ = IntervalSchedule.objects.get_or_create(
                every=job["every"], period=IntervalSchedule.MINUTES
            )
            task, created = PeriodicTask.objects.get_or_create(
                task=job["task"],
                defaults={"name": job["name"], "interval": schedule, "enabled": True},
            )
            self.stdout.write(
                self.style.SUCCESS(f"{'Scheduled' if created else 'Already scheduled'}: {job['name']}")
            )

        self.stdout.write(self.style.SUCCESS("Seeding complete."))
