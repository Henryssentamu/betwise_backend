from rest_framework import serializers
from matches.serializers import MatchListSerializer
from .models import (
    Recommendation, BettingPartner, SeasonPlan, WeeklyTarget,
    UserBetLog, PromoCode,
)


class RecommendationSerializer(serializers.ModelSerializer):
    match = MatchListSerializer(read_only=True)

    class Meta:
        model = Recommendation
        fields = [
            "id", "match", "bet_type", "risk_tier", "confidence_score",
            "suggested_odds_min", "suggested_odds_max", "reasoning_summary",
            "outcome", "generated_at",
        ]


class BettingPartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = BettingPartner
        fields = ["id", "name", "highlight_note", "website_url", "rank_order"]


class WeeklyTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklyTarget
        fields = [
            "id", "week_number", "week_starts_on", "target_stake_ugx",
            "target_odds_to_chase", "actual_invested_ugx", "actual_earned_ugx",
        ]


class SeasonPlanCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeasonPlan
        fields = ["id", "starts_on", "ends_on", "total_budget_ugx", "target_earnings_ugx", "risk_appetite"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs["ends_on"] <= attrs["starts_on"]:
            raise serializers.ValidationError("Season end date must be after the start date.")
        if attrs["total_budget_ugx"] <= 0:
            raise serializers.ValidationError("Budget must be greater than zero.")
        return attrs


class SeasonPlanDetailSerializer(serializers.ModelSerializer):
    weekly_targets = WeeklyTargetSerializer(many=True, read_only=True)

    class Meta:
        model = SeasonPlan
        fields = [
            "id", "starts_on", "ends_on", "total_budget_ugx",
            "target_earnings_ugx", "risk_appetite", "is_active",
            "weekly_targets", "created_at",
        ]


class UserBetLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserBetLog
        fields = [
            "id", "recommendation", "week", "stake_ugx", "odds_taken",
            "followed_recommendation", "result", "payout_ugx", "logged_at",
        ]
        read_only_fields = ["id", "logged_at"]


class PromoCodeValidateSerializer(serializers.Serializer):
    code = serializers.CharField()
    plan_id = serializers.IntegerField()

    def validate(self, attrs):
        try:
            promo = PromoCode.objects.get(code__iexact=attrs["code"])
        except PromoCode.DoesNotExist:
            raise serializers.ValidationError("Invalid promo code.")

        if not promo.is_redeemable():
            raise serializers.ValidationError("This promo code is no longer valid.")

        if promo.applicable_plans.exists() and not promo.applicable_plans.filter(
            id=attrs["plan_id"]
        ).exists():
            raise serializers.ValidationError("This promo code doesn't apply to the selected plan.")

        attrs["promo_code"] = promo
        return attrs


class CheckoutSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()
    promo_code = serializers.CharField(required=False, allow_blank=True)
