from django.contrib import admin
from .models import User, SubscriptionPlan, Subscription


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("auth_user", "phone_number", "is_age_verified", "default_risk_appetite", "created_at")
    list_filter = ("is_age_verified", "default_risk_appetite", "country")
    search_fields = ("auth_user__username", "auth_user__email", "phone_number")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "tier", "billing_cycle", "price_ugx", "is_active")
    list_filter = ("tier", "billing_cycle", "is_active")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "starts_at", "ends_at", "auto_renew")
    list_filter = ("status", "plan")
    search_fields = ("user__auth_user__username",)
