from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, SubscriptionPlan
from .serializers import (
    SignupSerializer,
    UserProfileSerializer,
    SubscriptionPlanSerializer,
)


class SignupView(APIView):
    """
    POST /api/auth/signup/
    Creates the auth user + profile, then returns JWT tokens immediately
    so the user lands straight in the app post-signup.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()

        refresh = RefreshToken.for_user(profile.auth_user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "profile": UserProfileSerializer(profile).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MeView(generics.RetrieveUpdateAPIView):
    """
    GET/PATCH /api/auth/me/
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.profile


class SubscriptionPlanListView(generics.ListAPIView):
    """
    GET /api/auth/plans/  — public, so the pricing screen can be shown
    before login.
    """
    queryset = SubscriptionPlan.objects.filter(is_active=True)
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.AllowAny]
