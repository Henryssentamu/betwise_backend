import uuid
from datetime import date

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import SubscriptionPlan, Subscription
from .models import (
    Recommendation, BettingPartner, SeasonPlan, WeeklyTarget,
    UserBetLog, PromoCode, PromoCodeRedemption, PesapalTransaction,
)
from .serializers import (
    RecommendationSerializer, BettingPartnerSerializer,
    SeasonPlanCreateSerializer, SeasonPlanDetailSerializer,
    UserBetLogSerializer, PromoCodeValidateSerializer, CheckoutSerializer,
)
from .planning import generate_weekly_targets, pace_summary, suggest_course_correction
from .pesapal import PesapalClient, PESAPAL_STATUS_MAP


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

class RecommendationListView(generics.ListAPIView):
    """
    GET /api/recommendations/?risk_tier=low&match__league=1
    Requires an active subscription — enforced in get_queryset so a lapsed
    subscriber sees an empty list rather than a 403 (kinder UX, matches the
    "freemium tier" product decision).
    """
    serializer_class = RecommendationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["risk_tier", "bet_type"]

    def get_queryset(self):
        profile = self.request.user.profile
        has_active_sub = Subscription.objects.filter(
            user=profile, status="active"
        ).exists()
        if not has_active_sub:
            return Recommendation.objects.none()
        return Recommendation.objects.filter(
            match__status="scheduled"
        ).select_related("match", "match__home_team", "match__away_team", "match__league")


class BettingPartnerListView(generics.ListAPIView):
    queryset = BettingPartner.objects.filter(is_active=True)
    serializer_class = BettingPartnerSerializer
    permission_classes = [permissions.IsAuthenticated]


# ---------------------------------------------------------------------------
# Season planning
# ---------------------------------------------------------------------------

class SeasonPlanCreateView(generics.CreateAPIView):
    """
    POST /api/season-plans/
    Creates the plan and immediately generates its weekly targets.
    """
    serializer_class = SeasonPlanCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        profile = self.request.user.profile
        SeasonPlan.objects.filter(user=profile, is_active=True).update(is_active=False)
        season_plan = serializer.save(user=profile)
        generate_weekly_targets(season_plan)
        self._season_plan = season_plan

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data = SeasonPlanDetailSerializer(self._season_plan).data
        return response


class ActiveSeasonPlanView(generics.RetrieveAPIView):
    """
    GET /api/season-plans/active/
    Powers the season overview home screen.
    """
    serializer_class = SeasonPlanDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        plan = SeasonPlan.objects.filter(
            user=self.request.user.profile, is_active=True
        ).first()
        if not plan:
            raise ValidationError("No active season plan. Create one to get started.")
        return plan


class SeasonPacedashboardView(APIView):
    """
    GET /api/season-plans/active/pace/
    Powers the portfolio pace dashboard: invested/earned/pace-vs-goal cards
    plus the course-correction narrative.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        plan = SeasonPlan.objects.filter(user=request.user.profile, is_active=True).first()
        if not plan:
            return Response({"detail": "No active season plan."}, status=status.HTTP_404_NOT_FOUND)

        today = date.today()
        summary = pace_summary(plan, today)
        correction = suggest_course_correction(plan, today)
        summary["course_correction_message"] = correction
        return Response(summary)


class UserBetLogCreateView(generics.CreateAPIView):
    serializer_class = UserBetLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user.profile)


# ---------------------------------------------------------------------------
# Promo codes + checkout (Pesapal)
# ---------------------------------------------------------------------------

class PromoCodeValidateView(APIView):
    """
    POST /api/promo-codes/validate/  {"code": "LAUNCH50", "plan_id": 2}
    Called live as the user types a promo code at checkout, before hitting
    Pesapal, so they see the discounted price immediately.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PromoCodeValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        promo = serializer.validated_data["promo_code"]
        plan = SubscriptionPlan.objects.get(id=serializer.validated_data["plan_id"])

        discounted_price = promo.calculate_discounted_price(plan.price_ugx)
        return Response({
            "valid": True,
            "original_price_ugx": plan.price_ugx,
            "discounted_price_ugx": discounted_price,
            "discount_type": promo.discount_type,
            "discount_value": promo.discount_value,
        })


class CheckoutView(APIView):
    """
    POST /api/checkout/  {"plan_id": 2, "promo_code": "LAUNCH50"}
    Creates a PesapalTransaction and returns the redirect_url for the
    frontend to send the user to Pesapal's hosted payment page.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            plan = SubscriptionPlan.objects.get(id=data["plan_id"], is_active=True)
        except SubscriptionPlan.DoesNotExist:
            return Response({"detail": "Invalid plan."}, status=status.HTTP_400_BAD_REQUEST)

        amount = plan.price_ugx
        promo = None
        promo_code_str = data.get("promo_code", "").strip()
        if promo_code_str:
            try:
                promo = PromoCode.objects.get(code__iexact=promo_code_str)
            except PromoCode.DoesNotExist:
                return Response({"detail": "Invalid promo code."}, status=status.HTTP_400_BAD_REQUEST)
            if not promo.is_redeemable():
                return Response({"detail": "Promo code is no longer valid."}, status=status.HTTP_400_BAD_REQUEST)
            amount = promo.calculate_discounted_price(amount)

        profile = request.user.profile
        merchant_reference = f"BW-{uuid.uuid4().hex[:12].upper()}"

        transaction = PesapalTransaction.objects.create(
            user=profile,
            plan=plan,
            promo_code=promo,
            merchant_reference=merchant_reference,
            amount_ugx=amount,
            status="pending",
        )

        try:
            client = PesapalClient()
            result = client.submit_order(
                merchant_reference=merchant_reference,
                amount=float(amount),
                description=f"{plan.name} subscription",
                callback_url=settings.PESAPAL_CALLBACK_URL,
                ipn_id=settings.PESAPAL_IPN_ID,
                email=profile.auth_user.email,
                phone_number=profile.phone_number,
                first_name=profile.auth_user.first_name or profile.auth_user.username,
                last_name=profile.auth_user.last_name,
            )
        except Exception as exc:
            transaction.status = "failed"
            transaction.status_description = str(exc)
            transaction.save(update_fields=["status", "status_description"])
            return Response(
                {"detail": "Could not initiate payment. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        transaction.order_tracking_id = result.get("order_tracking_id", "")
        transaction.save(update_fields=["order_tracking_id"])

        return Response({
            "merchant_reference": merchant_reference,
            "redirect_url": result.get("redirect_url"),
        })


class PesapalIPNView(APIView):
    """
    GET /api/payments/pesapal/ipn/?OrderTrackingId=...&OrderMerchantReference=...
    Pesapal calls this when a transaction's status changes. We look up the
    transaction, confirm status directly with Pesapal (never trust the
    querystring alone), then activate the subscription if completed.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        order_tracking_id = request.query_params.get("OrderTrackingId")
        merchant_reference = request.query_params.get("OrderMerchantReference")

        if not order_tracking_id or not merchant_reference:
            return Response({"detail": "Missing parameters."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            transaction = PesapalTransaction.objects.get(merchant_reference=merchant_reference)
        except PesapalTransaction.DoesNotExist:
            return Response({"detail": "Unknown transaction."}, status=status.HTTP_404_NOT_FOUND)

        client = PesapalClient()
        status_data = client.get_transaction_status(order_tracking_id)
        pesapal_status = status_data.get("payment_status_description", "").upper()
        mapped_status = PESAPAL_STATUS_MAP.get(pesapal_status, "pending")

        transaction.status = mapped_status
        transaction.status_description = pesapal_status
        transaction.order_tracking_id = order_tracking_id
        transaction.save(update_fields=["status", "status_description", "order_tracking_id"])

        if mapped_status == "completed":
            self._activate_subscription(transaction)

        return Response({"status": mapped_status})

    def _activate_subscription(self, transaction: PesapalTransaction):
        from dateutil.relativedelta import relativedelta

        if Subscription.objects.filter(
            user=transaction.user, plan=transaction.plan, status="active"
        ).exists():
            return  # already activated (IPN can fire more than once)

        starts_at = timezone.now()
        ends_at = (
            starts_at + relativedelta(months=1)
            if transaction.plan.billing_cycle == "monthly"
            else starts_at + relativedelta(months=9)  # season ~ 9 months
        )
        Subscription.objects.create(
            user=transaction.user,
            plan=transaction.plan,
            status="active",
            starts_at=starts_at,
            ends_at=ends_at,
        )

        if transaction.promo_code:
            promo = transaction.promo_code
            PromoCodeRedemption.objects.create(
                promo_code=promo,
                user=transaction.user,
                plan=transaction.plan,
                original_price_ugx=transaction.plan.price_ugx,
                discounted_price_ugx=transaction.amount_ugx,
            )
            promo.times_redeemed += 1
            promo.save(update_fields=["times_redeemed"])


# ---------------------------------------------------------------------------
# Admin dashboard stats
# ---------------------------------------------------------------------------

class AdminDashboardStatsView(APIView):
    """
    GET /api/admin/dashboard-stats/
    Powers the four KPI cards on the admin dashboard: active users, MRR,
    recommendation accuracy, users on pace. Restricted to staff.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        active_subs = Subscription.objects.filter(status="active")
        active_users = active_subs.values("user").distinct().count()

        mrr = sum(
            (s.plan.price_ugx for s in active_subs.select_related("plan")
             if s.plan.billing_cycle == "monthly"),
            0,
        )

        evaluated = Recommendation.objects.filter(outcome__in=["hit", "missed"])
        total_evaluated = evaluated.count()
        hits = evaluated.filter(outcome="hit").count()
        accuracy = round((hits / total_evaluated) * 100, 1) if total_evaluated else None

        today = date.today()
        users_on_pace = 0
        total_active_plans = 0
        for plan in SeasonPlan.objects.filter(is_active=True):
            total_active_plans += 1
            summary = pace_summary(plan, today)
            if summary["pace_status"] in ("ahead", "on_track"):
                users_on_pace += 1
        pace_percentage = (
            round((users_on_pace / total_active_plans) * 100, 1) if total_active_plans else None
        )

        return Response({
            "active_users": active_users,
            "mrr_ugx": mrr,
            "recommendation_accuracy_pct": accuracy,
            "users_on_pace_pct": pace_percentage,
        })
