"""
Seasonal planning algorithm.

Takes a user's season-level budget and target earnings and breaks it into
weekly stake and odds targets. Also powers the pace-tracking dashboard by
comparing actual invested/earned against the plan, and flags when a user
needs a course correction.

All "actuals" (money spent, money earned, bets won/lost) are computed live
by aggregating UserBetLog — there is no cached/synced total anywhere, so
there's nothing to keep in sync. Every helper below buckets by
UserBetLog.logged_at (the date the client reported the bet).
"""
import math
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, QuerySet, Sum
from django.utils import timezone

from .models import Recommendation, SeasonPlan, UserBetLog, WeeklyTarget

# Compounding factor per week assumed for the odds target — since stakes are
# meant to be reinvested weekly rather than the whole budget spent upfront.
RISK_ODDS_MULTIPLIER = {
    "low": 1.35,
    "medium": 1.85,
    "high": 2.75,
}

# Bet-frequency advice heuristics — placeholder values, easy to retune.
MIN_STAKE_PER_BET_UGX = Decimal("2000")
MIN_STAKE_FRACTION_OF_WEEKLY = Decimal("0.15")


def week_count(season_plan: SeasonPlan) -> int:
    days = (season_plan.ends_on - season_plan.starts_on).days
    return max(math.ceil(days / 7), 1)


def generate_weekly_targets(season_plan: SeasonPlan) -> list:
    """
    Splits the season budget evenly across weeks (simple, transparent —
    users can see exactly how the number was derived), and sets each week's
    odds target so that hitting it on the flat weekly stake reaches the
    season's target earnings by the final week.
    """
    weeks = week_count(season_plan)
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
    for wk_number in range(1, weeks + 1):
        week_start = season_plan.starts_on + timedelta(weeks=wk_number - 1)
        target, _ = WeeklyTarget.objects.update_or_create(
            season_plan=season_plan,
            week_number=wk_number,
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


# ---------------------------------------------------------------------------
# Live aggregation over UserBetLog
# ---------------------------------------------------------------------------

def _day_bounds(start_date, end_date):
    """
    Converts a [start_date, end_date) calendar-date range into aware
    datetime bounds in the active timezone, e.g. for `field__gte`/`field__lt`
    filters on a DateTimeField. Deliberately avoids `__date` lookups /
    TruncDate — those need MySQL's CONVERT_TZ(), which requires timezone
    tables that aren't guaranteed to be loaded on the server (frequently
    missing on managed MySQL too), so results would silently come back
    empty instead of erroring.
    """
    start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
    end_dt = timezone.make_aware(datetime.combine(end_date, time.min))
    return start_dt, end_dt


def _bet_logs_in_range(season_plan: SeasonPlan, start_date, end_date) -> QuerySet:
    """UserBetLog rows for this plan's owner, logged in [start_date, end_date)."""
    start_dt, end_dt = _day_bounds(start_date, end_date)
    return UserBetLog.objects.filter(
        user=season_plan.user,
        logged_at__gte=start_dt,
        logged_at__lt=end_dt,
    )


def qualifying_recommendations_for_range(season_plan: SeasonPlan, start_date, end_date) -> QuerySet:
    """Recommendations matching this plan's risk_appetite, kicking off in [start_date, end_date)."""
    start_dt, end_dt = _day_bounds(start_date, end_date)
    return Recommendation.objects.filter(
        risk_tier=season_plan.risk_appetite,
        match__kickoff_at__gte=start_dt,
        match__kickoff_at__lt=end_dt,
    )


def qualifying_match_days(season_plan: SeasonPlan, start_date, end_date) -> list:
    """
    One entry per distinct day in range with >=1 qualifying recommendation,
    ordered chronologically: [{"date": date, "match_count": int, "avg_confidence": float}].
    Grouped in Python (not DB-side TruncDate) for the same reason described
    in _day_bounds — data volumes here are small (one user's season).
    """
    rows = qualifying_recommendations_for_range(season_plan, start_date, end_date).values_list(
        "match__kickoff_at", "confidence_score"
    )
    buckets: dict = {}
    for kickoff_at, confidence in rows:
        local_date = timezone.localtime(kickoff_at).date()
        buckets.setdefault(local_date, []).append(confidence)

    return [
        {"date": d, "match_count": len(scores), "avg_confidence": round(sum(scores) / len(scores), 1)}
        for d, scores in sorted(buckets.items())
    ]


def budget_balance(season_plan: SeasonPlan, start_date, end_date, target_stake_ugx: Decimal) -> dict:
    agg = _bet_logs_in_range(season_plan, start_date, end_date).aggregate(
        spent=Sum("stake_ugx"), earned=Sum("payout_ugx"),
    )
    spent = agg["spent"] or Decimal("0")
    earned = agg["earned"] or Decimal("0")
    return {
        "target_stake_ugx": target_stake_ugx,
        "spent_ugx": spent,
        "earned_ugx": earned,
        "net_ugx": earned - spent,
        "remaining_budget_ugx": target_stake_ugx - spent,
    }


def odds_and_count_summary(season_plan: SeasonPlan, start_date, end_date, target_odds_to_chase: float) -> dict:
    agg = _bet_logs_in_range(season_plan, start_date, end_date).aggregate(
        won=Count("id", filter=Q(result="won")),
        lost=Count("id", filter=Q(result="lost")),
        pending=Count("id", filter=Q(result="pending")),
        avg_odds_on_wins=Avg("odds_taken", filter=Q(result="won")),
    )
    avg_odds = agg["avg_odds_on_wins"]
    return {
        "target_odds_to_chase": target_odds_to_chase,
        "bets_won": agg["won"],
        "bets_lost": agg["lost"],
        "bets_pending": agg["pending"],
        "avg_odds_achieved_on_wins": round(avg_odds, 2) if avg_odds is not None else None,
        # positive: avg odds on wins so far is below the required multiplier
        "odds_gap": round(target_odds_to_chase - avg_odds, 2) if avg_odds is not None else None,
    }


def daily_breakdown_for_week(season_plan: SeasonPlan, weekly_target: WeeklyTarget) -> list:
    """
    One entry per qualifying match-day in this week; days with no qualifying
    matches are simply absent — no target, no expectation.
    """
    week_start = weekly_target.week_starts_on
    week_end = week_start + timedelta(days=7)
    days = qualifying_match_days(season_plan, week_start, week_end)
    if not days:
        return []
    per_day_stake = (weekly_target.target_stake_ugx / len(days)).quantize(Decimal("0.01"))

    breakdown = []
    for day in days:
        day_start = day["date"]
        day_end = day_start + timedelta(days=1)
        balance = budget_balance(season_plan, day_start, day_end, per_day_stake)
        odds = odds_and_count_summary(season_plan, day_start, day_end, weekly_target.target_odds_to_chase)
        breakdown.append({
            "date": day_start,
            "qualifying_match_count": day["match_count"],
            **balance,
            **odds,
        })
    return breakdown


def week_summary(season_plan: SeasonPlan, weekly_target: WeeklyTarget) -> dict:
    week_start = weekly_target.week_starts_on
    week_end = week_start + timedelta(days=7)
    balance = budget_balance(season_plan, week_start, week_end, weekly_target.target_stake_ugx)
    odds = odds_and_count_summary(season_plan, week_start, week_end, weekly_target.target_odds_to_chase)
    return {
        "week_number": weekly_target.week_number,
        "week_starts_on": week_start,
        **balance,
        **odds,
    }


def month_number_for_week(wk_number: int) -> int:
    """Season-relative 'month' = 4 consecutive weeks, since weeks are already
    season-relative and don't align to calendar month boundaries."""
    return ((wk_number - 1) // 4) + 1


def monthly_summary(season_plan: SeasonPlan) -> list:
    weekly_targets = list(season_plan.weekly_targets.order_by("week_number"))
    months = {}
    for wt in weekly_targets:
        months.setdefault(month_number_for_week(wt.week_number), []).append(wt)

    summaries = []
    for month_number, weeks in sorted(months.items()):
        month_target_stake = sum((w.target_stake_ugx for w in weeks), Decimal("0"))
        start = weeks[0].week_starts_on
        end = weeks[-1].week_starts_on + timedelta(days=7)
        balance = budget_balance(season_plan, start, end, month_target_stake)

        # Stake-weighted average odds target across the month's weeks.
        weighted = sum((Decimal(str(w.target_odds_to_chase)) * w.target_stake_ugx for w in weeks), Decimal("0"))
        month_target_odds = float(weighted / month_target_stake) if month_target_stake else 0.0
        odds = odds_and_count_summary(season_plan, start, end, month_target_odds)

        summaries.append({
            "month_number": month_number,
            "starts_on": start,
            "ends_on": end - timedelta(days=1),
            "week_numbers": [w.week_number for w in weeks],
            **balance,
            **odds,
        })
    return summaries


def minimum_stake_per_bet(weekly_target: WeeklyTarget) -> Decimal:
    fraction_based = (weekly_target.target_stake_ugx * MIN_STAKE_FRACTION_OF_WEEKLY).quantize(Decimal("0.01"))
    return max(MIN_STAKE_PER_BET_UGX, fraction_based)


def weekly_bet_frequency_advice(season_plan: SeasonPlan, weekly_target: WeeklyTarget) -> dict:
    """
    Advises how many times to bet this week, and on which days, based on
    match availability and a sensible minimum stake per bet.
    """
    week_start = weekly_target.week_starts_on
    week_end = week_start + timedelta(days=7)
    days = qualifying_match_days(season_plan, week_start, week_end)
    min_stake = minimum_stake_per_bet(weekly_target)

    if not days or weekly_target.target_stake_ugx <= 0:
        return {
            "available_match_days": 0,
            "min_stake_per_bet_ugx": min_stake,
            "recommended_bet_count": 0,
            "recommended_days": [],
            "message": "No qualifying matches this week — no bets recommended.",
        }

    max_affordable = int(weekly_target.target_stake_ugx // min_stake)
    recommended_count = max(1, min(len(days), max_affordable))

    ranked_days = sorted(days, key=lambda d: (-d["avg_confidence"], d["date"]))
    recommended_days = sorted(ranked_days[:recommended_count], key=lambda d: d["date"])
    stake_per_bet = (weekly_target.target_stake_ugx / recommended_count).quantize(Decimal("0.01"))

    return {
        "available_match_days": len(days),
        "min_stake_per_bet_ugx": min_stake,
        "recommended_bet_count": recommended_count,
        "recommended_stake_per_bet_ugx": stake_per_bet,
        "recommended_days": [d["date"] for d in recommended_days],
        "message": (
            f"With {weekly_target.target_stake_ugx:,.0f} UGX to stake across "
            f"{len(days)} day(s) with qualifying matches this week, aim for about "
            f"{recommended_count} bet(s) of roughly {stake_per_bet:,.0f} UGX each, "
            f"prioritising the day(s) with the highest-confidence picks."
        ),
    }


# ---------------------------------------------------------------------------
# Pace dashboard
# ---------------------------------------------------------------------------

def pace_summary(season_plan: SeasonPlan, today) -> dict:
    """
    Powers the portfolio pace dashboard: invested/earned totals so far,
    odds achieved vs target, and whether the user is ahead, on, or behind
    pace relative to a straight-line target for "today" within the season.
    """
    weeks_elapsed = min(current_week_number(season_plan, today), week_count(season_plan))
    total_weeks = week_count(season_plan)

    range_end = min(today, season_plan.ends_on) + timedelta(days=1)
    balance = budget_balance(season_plan, season_plan.starts_on, range_end, season_plan.total_budget_ugx)
    net = balance["net_ugx"]

    expected_progress_ratio = weeks_elapsed / total_weeks
    expected_net_by_now = Decimal(str(season_plan.target_earnings_ugx)) * Decimal(str(expected_progress_ratio))

    if net >= expected_net_by_now:
        pace_status = "ahead"
    elif net >= expected_net_by_now * Decimal("0.7"):
        pace_status = "on_track"
    else:
        pace_status = "behind"

    odds = odds_and_count_summary(
        season_plan, season_plan.starts_on, range_end,
        target_odds_to_chase=RISK_ODDS_MULTIPLIER[season_plan.risk_appetite],
    )

    return {
        "weeks_elapsed": weeks_elapsed,
        "total_weeks": total_weeks,
        "total_invested_ugx": balance["spent_ugx"],
        "total_earned_ugx": balance["earned_ugx"],
        "net_ugx": net,
        "expected_net_by_now_ugx": expected_net_by_now,
        "pace_status": pace_status,
        "season_bets_won": odds["bets_won"],
        "season_bets_lost": odds["bets_lost"],
        "season_bets_pending": odds["bets_pending"],
        "season_avg_odds_achieved_on_wins": odds["avg_odds_achieved_on_wins"],
        "season_target_odds_to_chase": odds["target_odds_to_chase"],
        "season_odds_gap": odds["odds_gap"],
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

    current_wt = season_plan.weekly_targets.filter(
        week_number=min(current_week_number(season_plan, today), summary["total_weeks"])
    ).first()
    current_stake = current_wt.target_stake_ugx if current_wt else Decimal("0")
    current_odds = current_wt.target_odds_to_chase if current_wt else RISK_ODDS_MULTIPLIER[season_plan.risk_appetite]

    stake_message = ""
    if current_odds > 1:
        extra_stake = (catch_up_per_week / Decimal(str(current_odds - 1))).quantize(Decimal("0.01"))
        stake_message = (
            f" One option: increase your weekly stake from about {current_stake:,.0f} to "
            f"{current_stake + extra_stake:,.0f} UGX (roughly +{extra_stake:,.0f} UGX/week) "
            f"at your current {season_plan.risk_appetite} risk tier."
        )

    risk_message = ""
    if season_plan.risk_appetite != "high":
        next_tier = "medium" if season_plan.risk_appetite == "low" else "high"
        risk_message = (
            f" Alternatively, consider a {next_tier}-risk plan next season to chase higher "
            f"odds with the same stake — this also raises variance."
        )

    return (
        f"You're behind pace by roughly {shortfall:,.0f} UGX. To catch up by "
        f"season end, aim for about {catch_up_per_week:,.0f} UGX more net "
        f"return per week over the remaining {weeks_remaining} weeks."
        f"{stake_message}{risk_message}"
    )
