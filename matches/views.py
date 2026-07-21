from rest_framework import generics, permissions
from django_filters.rest_framework import DjangoFilterBackend

from .models import League, Team, Match
from .serializers import LeagueSerializer, TeamSerializer, MatchListSerializer, MatchDetailSerializer


class LeagueListView(generics.ListAPIView):
    queryset = League.objects.filter(is_active=True)
    serializer_class = LeagueSerializer
    permission_classes = [permissions.IsAuthenticated]


class TeamListView(generics.ListAPIView):
    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["league"]

    def get_queryset(self):
        return Team.objects.all()


class UpcomingMatchListView(generics.ListAPIView):
    """
    GET /api/matches/upcoming/?league=1
    Powers the weekly match list shown alongside recommendations.
    """
    serializer_class = MatchListSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["league", "status"]

    def get_queryset(self):
        return Match.objects.filter(status__in=["scheduled", "live"]).order_by("kickoff_at")


class MatchDetailView(generics.RetrieveAPIView):
    """
    GET /api/matches/<id>/
    Powers the reasoning detail screen — head-to-head, form, squad news.
    """
    queryset = Match.objects.all()
    serializer_class = MatchDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
