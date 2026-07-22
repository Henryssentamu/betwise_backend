"""
Recommendation scoring engine.

Combines three weighted signals into a single confidence score (0-100) for
each candidate outcome of a match, then maps that confidence to a risk tier
and a suggested odds range. Signal weights are stored back on the
Recommendation row so the "why this pick" screen can show its own math.

This is intentionally rule-based rather than a black-box model for the MVP —
it's auditable, and the weights below are the first thing to tune once
backtesting (see the QA target of 5-10% error margin) shows where it's off.
"""
from dataclasses import dataclass
from decimal import Decimal

from matches.models import Match, HeadToHead
from .models import Recommendation

# Signal weights — must sum to 1.0. Head-to-head history matters, but recent
# form is weighted highest since it reflects current squad strength better
# than a multi-season head-to-head record.
WEIGHT_HEAD_TO_HEAD = 0.30
WEIGHT_RECENT_FORM = 0.50
WEIGHT_SQUAD_NEWS = 0.20

RISK_TIER_THRESHOLDS = {
    # confidence >= 70 -> low risk (high probability picks)
    # 50 <= confidence < 70 -> medium risk
    # confidence < 50 -> high risk (only surfaced if odds justify the payout)
    "low": 70,
    "medium": 50,
}


@dataclass
class SignalBreakdown:
    head_to_head_score: float  # 0-100, favouring home team as it increases
    recent_form_score: float  # 0-100, favouring home team as it increases
    squad_news_score: float  # 0-100, favouring home team as it increases


def _head_to_head_score(home_team, away_team) -> float:
    """
    Returns a 0-100 score where 50 is neutral, >50 favours the home team.
    """
    h2h = HeadToHead.objects.filter(
        team_a__in=[home_team, away_team], team_b__in=[home_team, away_team]
    ).first()
    if not h2h or h2h.matches_considered == 0:
        return 50.0

    home_wins = h2h.team_a_wins if h2h.team_a_id == home_team.id else h2h.team_b_wins
    away_wins = h2h.team_b_wins if h2h.team_a_id == home_team.id else h2h.team_a_wins
    total = home_wins + away_wins + h2h.draws
    if total == 0:
        return 50.0

    # Wins swing the score, draws pull toward neutral.
    raw = (home_wins - away_wins) / total  # -1..1
    return 50 + (raw * 50)


def _recent_form_score(home_team, away_team) -> float:
    """
    Uses the precomputed rolling form_score on each Team (updated after
    every finished match — see recompute_team_form in tasks.py).
    Assumes form_score is roughly in the range -10..10; clamps defensively.
    """
    home_form = max(min(home_team.current_form_score, 10), -10)
    away_form = max(min(away_team.current_form_score, 10), -10)
    diff = home_form - away_form  # -20..20
    return 50 + (diff / 20 * 50)


def _squad_news_score(home_team, away_team) -> float:
    """
    Penalises a side for major/confirmed-out injuries among recently
    reported news items. More severe and more numerous absences pull the
    score away from that team.
    """
    severity_penalty = {"minor": 1, "major": 4, "confirmed_out": 7}

    def penalty_for(team):
        recent_news = team.news_items.all()[:10]
        return sum(severity_penalty.get(n.severity, 0) for n in recent_news)

    home_penalty = penalty_for(home_team)
    away_penalty = penalty_for(away_team)

    # More penalty against home team lowers home's score, and vice versa.
    diff = away_penalty - home_penalty  # positive favours home
    capped_diff = max(min(diff, 20), -20)
    return 50 + (capped_diff / 20 * 50)


def _risk_tier_for_confidence(confidence: float) -> str:
    if confidence >= RISK_TIER_THRESHOLDS["low"]:
        return "low"
    if confidence >= RISK_TIER_THRESHOLDS["medium"]:
        return "medium"
    return "high"


def _suggested_odds_range(risk_tier: str) -> tuple:
    # Lower odds for safer picks, higher odds range for high-risk picks —
    # mirrors how these tiers were pitched to the board (low risk / lower
    # reward, high risk / high reward).
    return {
        "low": (1.20, 1.60),
        "medium": (1.60, 2.40),
        "high": (2.40, 4.50),
    }[risk_tier]


def generate_recommendation_for_match(match: Match) -> Recommendation:
    """
    Computes a single win/draw/away recommendation for a match. Call this
    from a Celery task once a match enters the "scheduled" window for the
    upcoming week (see tasks.py).
    """
    home_team = match.home_team
    away_team = match.away_team

    h2h_score = _head_to_head_score(home_team, away_team)
    form_score = _recent_form_score(home_team, away_team)
    news_score = _squad_news_score(home_team, away_team)

    # Weighted combination, still on a 0-100 "favours home" scale.
    combined_home_score = (
        h2h_score * WEIGHT_HEAD_TO_HEAD
        + form_score * WEIGHT_RECENT_FORM
        + news_score * WEIGHT_SQUAD_NEWS
    )

    # Decide the pick: how far the combined score sits from neutral (50)
    # determines both which outcome we back and our confidence in it.
    distance_from_neutral = abs(combined_home_score - 50)
    confidence = min(50 + distance_from_neutral, 95)  # cap at 95, never claim certainty

    if distance_from_neutral < 6:
        bet_type = "draw"
    elif combined_home_score > 50:
        bet_type = "home_win"
    else:
        bet_type = "away_win"

    risk_tier = _risk_tier_for_confidence(confidence)
    odds_min, odds_max = _suggested_odds_range(risk_tier)

    reasoning_parts = []
    if abs(h2h_score - 50) > 5:
        favoured = home_team.name if h2h_score > 50 else away_team.name
        reasoning_parts.append(f"Head-to-head record favours {favoured}.")
    if abs(form_score - 50) > 5:
        favoured = home_team.name if form_score > 50 else away_team.name
        reasoning_parts.append(f"{favoured} is in stronger recent form.")
    if abs(news_score - 50) > 5:
        hurt = away_team.name if news_score > 50 else home_team.name
        reasoning_parts.append(f"{hurt} is missing key players through injury.")
    if not reasoning_parts:
        reasoning_parts.append("Both sides are closely matched on all tracked signals.")

    recommendation = Recommendation.objects.create(
        match=match,
        bet_type=bet_type,
        risk_tier=risk_tier,
        confidence_score=round(confidence, 1),
        suggested_odds_min=odds_min,
        suggested_odds_max=odds_max,
        head_to_head_weight=WEIGHT_HEAD_TO_HEAD,
        recent_form_weight=WEIGHT_RECENT_FORM,
        squad_news_weight=WEIGHT_SQUAD_NEWS,
        reasoning_summary=" ".join(reasoning_parts),
    )
    return recommendation


def evaluate_recommendation_outcome(recommendation: Recommendation) -> None:
    """
    Call once the underlying match is finished — marks the recommendation
    hit/missed for the admin accuracy metric.
    """
    from django.utils import timezone

    match = recommendation.match
    if match.status != "finished" or not match.result:
        return

    predicted_result_map = {"home_win": "home_win", "away_win": "away_win", "draw": "draw"}
    predicted = predicted_result_map.get(recommendation.bet_type)

    if predicted is None:
        # Non-1X2 bet types (corners, btts, over_under) need their own
        # evaluation logic once those markets are modeled with real stats.
        return

    recommendation.outcome = "hit" if predicted == match.result else "missed"
    recommendation.outcome_evaluated_at = timezone.now()
    recommendation.save(update_fields=["outcome", "outcome_evaluated_at"])


def sync_bet_logs_for_recommendation(recommendation: Recommendation) -> None:
    """
    Resolves self-reported bet logs that followed this recommendation and
    are still pending, now that its outcome is known. Bets not linked to a
    recommendation, or logged with followed_recommendation=False, are left
    alone — the system has no ground truth for a bet it didn't recommend.
    """
    if recommendation.outcome not in ("hit", "missed"):
        return

    won = recommendation.outcome == "hit"
    for log in recommendation.bet_logs.filter(followed_recommendation=True, result="pending"):
        log.result = "won" if won else "lost"
        log.payout_ugx = (
            (log.stake_ugx * Decimal(str(log.odds_taken))).quantize(Decimal("0.01"))
            if won else Decimal("0.00")
        )
        log.save(update_fields=["result", "payout_ugx"])
