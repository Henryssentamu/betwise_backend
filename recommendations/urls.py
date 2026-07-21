from django.urls import path
from .views import (
    RecommendationListView, BettingPartnerListView,
    SeasonPlanCreateView, ActiveSeasonPlanView, SeasonPacedashboardView,
    UserBetLogCreateView, PromoCodeValidateView, CheckoutView,
    PesapalIPNView, AdminDashboardStatsView,
)

urlpatterns = [
    path("recommendations/", RecommendationListView.as_view(), name="recommendation-list"),
    path("betting-partners/", BettingPartnerListView.as_view(), name="betting-partner-list"),

    path("season-plans/", SeasonPlanCreateView.as_view(), name="season-plan-create"),
    path("season-plans/active/", ActiveSeasonPlanView.as_view(), name="season-plan-active"),
    path("season-plans/active/pace/", SeasonPacedashboardView.as_view(), name="season-plan-pace"),

    path("bet-logs/", UserBetLogCreateView.as_view(), name="bet-log-create"),

    path("promo-codes/validate/", PromoCodeValidateView.as_view(), name="promo-code-validate"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("payments/pesapal/ipn/", PesapalIPNView.as_view(), name="pesapal-ipn"),

    path("admin/dashboard-stats/", AdminDashboardStatsView.as_view(), name="admin-dashboard-stats"),
]
