"""
Scheduled jobs. Registered with django-celery-beat automatically by
`seed_initial_data` rather than hardcoding a schedule here, so the ops team
can still tweak timing later via the admin (Periodic Tasks) without a
deploy:

  - recompute_all_team_form        every 1 hour
  - generate_recommendations_batch every 1 hour (after sync_matches runs)
  - evaluate_finished_recommendations every 15 minutes
"""
from celery import shared_task
from django.db import transaction
from django.db.models import Q

from matches.models import Team, Match
from .engine import (
    generate_recommendation_for_match,
    evaluate_recommendation_outcome,
    sync_bet_logs_for_recommendation,
)
from .models import Recommendation


FORM_WINDOW = 5  # number of recent finished matches considered for form


@shared_task
def recompute_team_form(team_id: int) -> None:
    """
    Simple form score: +3 for a win, +1 for a draw, -1 for a loss across the
    team's last FORM_WINDOW finished matches, normalised to roughly -10..10.
    """
    team = Team.objects.get(id=team_id)
    recent = (
        Match.objects.filter(status="finished")
        .filter(Q(home_team=team) | Q(away_team=team))
        .order_by("-kickoff_at")[:FORM_WINDOW]
    )

    points = 0
    for match in recent:
        is_home = match.home_team_id == team.id
        if match.result == "draw":
            points += 1
        elif (match.result == "home_win" and is_home) or (match.result == "away_win" and not is_home):
            points += 3
        else:
            points -= 1

    # Max possible is FORM_WINDOW * 3 -> scale to -10..10
    max_points = FORM_WINDOW * 3
    scaled = (points / max_points) * 10 if max_points else 0
    team.current_form_score = round(scaled, 2)
    team.save(update_fields=["current_form_score"])


@shared_task
def recompute_all_team_form() -> None:
    for team_id in Team.objects.values_list("id", flat=True):
        recompute_team_form.delay(team_id)


@shared_task
def generate_recommendations_batch() -> None:
    """
    Generates one recommendation per upcoming match that doesn't already
    have one, so re-running this task is idempotent.
    """
    upcoming = Match.objects.filter(status="scheduled").exclude(
        id__in=Recommendation.objects.values_list("match_id", flat=True)
    )
    for match in upcoming:
        generate_recommendation_for_match(match)


@shared_task
def evaluate_finished_recommendations() -> None:
    pending = Recommendation.objects.filter(
        outcome="pending", match__status="finished"
    ).select_related("match")
    for recommendation in pending:
        with transaction.atomic():
            evaluate_recommendation_outcome(recommendation)
            sync_bet_logs_for_recommendation(recommendation)
