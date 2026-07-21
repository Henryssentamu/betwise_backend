import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from accounts.models import User, SubscriptionPlan
from matches.models import Match


class Recommendation(models.Model):
    BET_TYPE_CHOICES = [
        ("home_win", "Home win"),
        ("away_win", "Away win"),
        ("draw", "Draw"),
        ("corners", "Corners"),
        ("btts", "Both teams to score"),
        ("over_under", "Over/under goals"),
    ]
    RISK_TIER_CHOICES = [
        ("low", "Low risk"),
        ("medium", "Medium risk"),
        ("high", "High risk"),
    ]

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="recommendations")
    bet_type = models.CharField(max_length=20, choices=BET_TYPE_CHOICES)
    risk_tier = models.CharField(max_length=10, choices=RISK_TIER_CHOICES)

    confidence_score = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Model's confidence in this outcome, 0-100",
    )
    suggested_odds_min = models.FloatField()
    suggested_odds_max = models.FloatField()

    head_to_head_weight = models.FloatField(default=0)
    recent_form_weight = models.FloatField(default=0)
    squad_news_weight = models.FloatField(default=0)
    reasoning_summary = models.TextField(blank=True)

    generated_at = models.DateTimeField(auto_now_add=True)

    OUTCOME_CHOICES = [
        ("pending", "Pending"),
        ("hit", "Hit"),
        ("missed", "Missed"),
    ]
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, default="pending")
    outcome_evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["match", "bet_type"])]
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.match} — {self.get_bet_type_display()} ({self.risk_tier})"


class BettingPartner(models.Model):
    name = models.CharField(max_length=100)
    highlight_note = models.CharField(max_length=150, blank=True)
    website_url = models.URLField()
    rank_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["rank_order"]

    def __str__(self):
        return self.name


class SeasonPlan(models.Model):
    RISK_APPETITE_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="season_plans")
    starts_on = models.DateField()
    ends_on = models.DateField()

    total_budget_ugx = models.DecimalField(max_digits=12, decimal_places=2)
    target_earnings_ugx = models.DecimalField(max_digits=12, decimal_places=2)
    risk_appetite = models.CharField(max_length=10, choices=RISK_APPETITE_CHOICES)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self):
        return f"{self.user} season plan ({self.starts_on} to {self.ends_on})"


class WeeklyTarget(models.Model):
    season_plan = models.ForeignKey(SeasonPlan, on_delete=models.CASCADE, related_name="weekly_targets")
    week_number = models.PositiveSmallIntegerField()
    week_starts_on = models.DateField()

    target_stake_ugx = models.DecimalField(max_digits=10, decimal_places=2)
    target_odds_to_chase = models.FloatField()

    actual_invested_ugx = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    actual_earned_ugx = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        unique_together = ("season_plan", "week_number")
        ordering = ["week_number"]


class UserBetLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bet_logs")
    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.SET_NULL, null=True, blank=True, related_name="bet_logs"
    )
    week = models.ForeignKey(WeeklyTarget, on_delete=models.SET_NULL, null=True, blank=True)

    stake_ugx = models.DecimalField(max_digits=10, decimal_places=2)
    odds_taken = models.FloatField()
    followed_recommendation = models.BooleanField(default=True)

    RESULT_CHOICES = [("pending", "Pending"), ("won", "Won"), ("lost", "Lost")]
    result = models.CharField(max_length=10, choices=RESULT_CHOICES, default="pending")
    payout_ugx = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    logged_at = models.DateTimeField(auto_now_add=True)


class PromoCode(models.Model):
    """
    Admin-generated promotional codes redeemable against any subscription
    plan at checkout.
    """
    DISCOUNT_TYPE_CHOICES = [
        ("percentage", "Percentage off"),
        ("fixed", "Fixed amount off (UGX)"),
    ]

    code = models.CharField(max_length=32, unique=True)
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES)
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Percentage (0-100) if type is percentage, otherwise UGX amount",
    )
    applicable_plans = models.ManyToManyField(
        SubscriptionPlan, blank=True,
        help_text="Leave empty to apply to all plans",
    )

    max_redemptions = models.PositiveIntegerField(
        null=True, blank=True, help_text="Leave blank for unlimited"
    )
    times_redeemed = models.PositiveIntegerField(default=0)

    active_from = models.DateTimeField()
    active_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code

    def is_redeemable(self) -> bool:
        from django.utils import timezone

        if not self.is_active:
            return False
        now = timezone.now()
        if now < self.active_from:
            return False
        if self.active_until and now > self.active_until:
            return False
        if self.max_redemptions is not None and self.times_redeemed >= self.max_redemptions:
            return False
        return True

    def calculate_discounted_price(self, price):
        from decimal import Decimal

        price = Decimal(str(price))
        discount_value = Decimal(str(self.discount_value))
        if self.discount_type == "percentage":
            discount = price * (discount_value / Decimal("100"))
        else:
            discount = discount_value
        discounted = price - discount
        return max(discounted, Decimal("0"))


class PromoCodeRedemption(models.Model):
    """
    One row per use — powers the admin 'redemptions per code' stats.
    """
    promo_code = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="promo_redemptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True)
    original_price_ugx = models.DecimalField(max_digits=10, decimal_places=2)
    discounted_price_ugx = models.DecimalField(max_digits=10, decimal_places=2)
    redeemed_at = models.DateTimeField(auto_now_add=True)


class PesapalTransaction(models.Model):
    """
    Tracks a Pesapal order end to end — created at checkout, updated when
    the IPN callback confirms status.
    """
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pesapal_transactions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    promo_code = models.ForeignKey(
        PromoCode, on_delete=models.SET_NULL, null=True, blank=True
    )

    merchant_reference = models.CharField(max_length=64, unique=True)
    order_tracking_id = models.CharField(max_length=128, blank=True)

    amount_ugx = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    status_description = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.merchant_reference} — {self.status}"
