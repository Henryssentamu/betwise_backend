from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User, SubscriptionPlan, Subscription

AuthUser = get_user_model()

MINIMUM_AGE_YEARS = 18


def _calculate_age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


class SignupSerializer(serializers.Serializer):
    """
    Handles account creation + age verification in one step. Date of birth
    is required at signup per the legal requirement that only 18+ users
    can access recommendations.
    """
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    country = serializers.CharField(max_length=64)
    phone_number = serializers.CharField(max_length=20)
    date_of_birth = serializers.DateField()
    default_risk_appetite = serializers.ChoiceField(
        choices=User.RISK_APPETITE_CHOICES, default="medium"
    )

    def validate_username(self, value):
        if AuthUser.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        if AuthUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_date_of_birth(self, value):
        if _calculate_age(value) < MINIMUM_AGE_YEARS:
            raise serializers.ValidationError(
                f"You must be at least {MINIMUM_AGE_YEARS} years old to register."
            )
        return value

    def create(self, validated_data):
        from django.utils import timezone

        auth_user = AuthUser.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )
        profile = User.objects.create(
            auth_user=auth_user,
            country=validated_data["country"],
            phone_number=validated_data["phone_number"],
            date_of_birth=validated_data["date_of_birth"],
            default_risk_appetite=validated_data["default_risk_appetite"],
            # Age already validated above, so verification is granted immediately.
            # Swap to False + a manual review step if you want ID documents checked
            # by a human before granting access.
            is_age_verified=True,
            age_verified_at=timezone.now(),
        )
        return profile


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="auth_user.username", read_only=True)
    email = serializers.EmailField(source="auth_user.email", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "phone_number", "country", "date_of_birth",
            "is_age_verified", "default_risk_appetite", "created_at",
        ]
        read_only_fields = ["id", "is_age_verified", "created_at"]


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ["id", "name", "tier", "billing_cycle", "price_ugx", "features", "is_active"]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)

    class Meta:
        model = Subscription
        fields = ["id", "plan", "status", "starts_at", "ends_at", "auto_renew", "created_at"]
