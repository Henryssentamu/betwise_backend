from django.contrib import admin
from .models import (
    Recommendation, BettingPartner, SeasonPlan, WeeklyTarget,
    UserBetLog, PromoCode, PromoCodeRedemption, PesapalTransaction,
)


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("match", "bet_type", "risk_tier", "confidence_score", "outcome", "generated_at")
    list_filter = ("risk_tier", "bet_type", "outcome")
    search_fields = ("match__home_team__name", "match__away_team__name")


@admin.register(BettingPartner)
class BettingPartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "rank_order", "is_active")
    ordering = ("rank_order",)


class WeeklyTargetInline(admin.TabularInline):
    model = WeeklyTarget
    extra = 0
    # actual_invested_ugx/actual_earned_ugx are no longer used — actuals are
    # now computed live from UserBetLog (see recommendations/planning.py) —
    # readonly here so staff aren't misled into thinking editing them does anything.
    readonly_fields = ("week_number", "week_starts_on", "actual_invested_ugx", "actual_earned_ugx")


@admin.register(SeasonPlan)
class SeasonPlanAdmin(admin.ModelAdmin):
    list_display = ("user", "starts_on", "ends_on", "total_budget_ugx", "target_earnings_ugx", "risk_appetite", "is_active")
    list_filter = ("risk_appetite", "is_active")
    inlines = [WeeklyTargetInline]


@admin.register(UserBetLog)
class UserBetLogAdmin(admin.ModelAdmin):
    list_display = ("user", "stake_ugx", "odds_taken", "result", "followed_recommendation", "logged_at")
    list_filter = ("result", "followed_recommendation")


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    """
    Admin-facing promo code management — create, edit, and see redemption
    counts at a glance, per the requested feature.
    """
    list_display = (
        "code", "discount_type", "discount_value",
        "times_redeemed", "max_redemptions", "is_active", "active_from", "active_until",
    )
    list_filter = ("discount_type", "is_active")
    search_fields = ("code",)
    readonly_fields = ("times_redeemed",)
    filter_horizontal = ("applicable_plans",)


@admin.register(PromoCodeRedemption)
class PromoCodeRedemptionAdmin(admin.ModelAdmin):
    list_display = ("promo_code", "user", "plan", "original_price_ugx", "discounted_price_ugx", "redeemed_at")
    list_filter = ("promo_code",)


@admin.register(PesapalTransaction)
class PesapalTransactionAdmin(admin.ModelAdmin):
    list_display = ("merchant_reference", "user", "plan", "amount_ugx", "status", "created_at")
    list_filter = ("status", "plan")
    search_fields = ("merchant_reference", "order_tracking_id", "user__auth_user__username")
    readonly_fields = ("id", "created_at", "updated_at")
