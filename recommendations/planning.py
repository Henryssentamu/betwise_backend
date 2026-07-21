"""
Seasonal planning algorithm.

Takes a user's season-level budget and target earnings and breaks it into
weekly stake and odds targets. Also powers the pace-tracking dashboard by
comparing actual invested/earned against the plan, and flags when a user
needs a course correction.
"""
import math
from datetime import timedelta
from decimal import Decimal

from .models import SeasonPlan, WeeklyTarget

# Compounding factor per week assumed for the odds target — since stakes are
# meant to be reinvested weekly rather than the whole budget spent upfront.
RISK_ODDS_MULTIPLIER = {
    "low": 1.35,
    "medium": 1.85,
    "high": 2.75,
}


def _week_count(season_plan: SeasonPlan) -> int:
    days = (season_plan.ends_on - season_plan.starts_on).days
    return max(math.ceil(days / 7), 1)


def generate_weekly_targets(season_plan: SeasonPlan) -> list:
    """
    Splits the season budget evenly across weeks (simple, transparent —
    users can see exactly how the number was derived), and sets each week's
    odds target so that hitting it on the flat weekly stake reaches the
    season's target earnings by the final week.
    """
    weeks = _week_count(season_plan)
    total_budget = Decimal(str(season_plan.total_budget_ugx))
    target_earnings = Decimal(str(season_plan.target_earnings_ugx))
    weekly_stake = (total_budget / weeks).quantize(Decimal("0.01"))

    odds_multiplier = RISK_ODDS_MULTIPLIER[season_plan.risk_appetite]

    # Required average odds per week to reach target earnings if every
    # weekly stake wins once at that odds level across the season.
    if weekly_stake > 0:
        required_total_return = total_budget + target_earnings
        required_avg_odds = float(required_total_return / total_budget)
    else:
        required_avg_odds = odds_multiplier

    # Blend the mathematically required odds with the risk-tier's typical
    # odds range so the target stays realistic rather than demanding
    # a home_win of 1.15 with an odds target of 6.0.
    target_odds = round((required_avg_odds + odds_multiplier) / 2, 2)

    targets = []
    for week_number in range(1, weeks + 1):
        week_start = season_plan.starts_on + timedelta(weeks=week_number - 1)
        target, _ = WeeklyTarget.objects.update_or_create(
            season_plan=season_plan,
            week_number=week_number,
            defaults={
                "week_starts_on": week_start,
                "target_stake_ugx": weekly_stake,
                "target_odds_to_chase": target_odds,
            },
        )
        targets.append(target)
    return targets


def current_week_number(season_plan: SeasonPlan, today) -> int:
    days_elapsed = (today - season_plan.starts_on).days
    return max((days_elapsed // 7) + 1, 1)


def pace_summary(season_plan: SeasonPlan, today) -> dict:
    """
    Powers the portfolio pace dashboard: invested/earned totals so far,
    and whether the user is ahead, on, or behind pace relative to a
    straight-line target for "today" within the season.
    """
    weeks_elapsed = min(
        current_week_number(season_plan, today), _week_count(season_plan)
    )
    targets_so_far = season_plan.weekly_targets.filter(week_number__lte=weeks_elapsed)

    total_invested = sum((Decimal(str(t.actual_invested_ugx)) for t in targets_so_far), Decimal("0"))
    total_earned = sum((Decimal(str(t.actual_earned_ugx)) for t in targets_so_far), Decimal("0"))
    net = total_earned - total_invested

    total_weeks = _week_count(season_plan)
    expected_progress_ratio = weeks_elapsed / total_weeks
    expected_net_by_now = Decimal(str(season_plan.target_earnings_ugx)) * Decimal(str(expected_progress_ratio))

    if net >= expected_net_by_now:
        pace_status = "ahead"
    elif net >= expected_net_by_now * Decimal("0.7"):
        pace_status = "on_track"
    else:
        pace_status = "behind"

    return {
        "weeks_elapsed": weeks_elapsed,
        "total_weeks": total_weeks,
        "total_invested_ugx": total_invested,
        "total_earned_ugx": total_earned,
        "net_ugx": net,
        "expected_net_by_now_ugx": expected_net_by_now,
        "pace_status": pace_status,
    }


def suggest_course_correction(season_plan: SeasonPlan, today) -> str | None:
    """
    Returns a human-readable nudge when a user is meaningfully off pace,
    or None if no correction is needed. Called by the pace dashboard
    endpoint and can also back a push notification later.
    """
    summary = pace_summary(season_plan, today)
    if summary["pace_status"] != "behind":
        return None

    weeks_remaining = summary["total_weeks"] - summary["weeks_elapsed"]
    if weeks_remaining <= 0:
        return (
            "The season has ended below target. Consider reviewing risk "
            "appetite before starting a new season plan."
        )

    shortfall = summary["expected_net_by_now_ugx"] - summary["net_ugx"]
    catch_up_per_week = (shortfall / weeks_remaining).quantize(Decimal("0.01"))

    return (
        f"You're behind pace by roughly {shortfall:,.0f} UGX. To catch up by "
        f"season end, aim for about {catch_up_per_week:,.0f} UGX more net "
        f"return per week over the remaining {weeks_remaining} weeks, or "
        f"consider adjusting your risk tier for the rest of the season."
    )
