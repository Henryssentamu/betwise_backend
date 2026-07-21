import uuid
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator


class User(models.Model):
    """
    Extends Django's built-in auth via a one-to-one profile.
    Keeps auth (django.contrib.auth.User) separate from betting-specific fields.
    """
    auth_user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=64, default="Uganda")

    date_of_birth = models.DateField(null=True, blank=True)
    national_id_number = models.CharField(max_length=64, blank=True)
    is_age_verified = models.BooleanField(default=False)
    age_verified_at = models.DateTimeField(null=True, blank=True)

    RISK_APPETITE_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]
    default_risk_appetite = models.CharField(
        max_length=10, choices=RISK_APPETITE_CHOICES, default="medium"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.auth_user.get_username()


class SubscriptionPlan(models.Model):
    """
    Catalogue of plans admin can configure — e.g. Casual Monthly, Pro Seasonal.
    """
    PLAN_TIER_CHOICES = [
        ("casual", "Casual"),
        ("pro", "Pro"),
    ]
    BILLING_CYCLE_CHOICES = [
        ("monthly", "Monthly"),
        ("seasonal", "Seasonal"),
    ]

    name = models.CharField(max_length=100)
    tier = models.CharField(max_length=10, choices=PLAN_TIER_CHOICES)
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLE_CHOICES)
    price_ugx = models.DecimalField(max_digits=10, decimal_places=2)
    features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.get_billing_cycle_display()})"


class Subscription(models.Model):
    """
    A user's active or past subscription record.
    """
    STATUS_CHOICES = [
        ("active", "Active"),
        ("past_due", "Past due"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="active")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.user} — {self.plan} ({self.status})"
