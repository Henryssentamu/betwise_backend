from django.urls import path
from .views import LeagueListView, TeamListView, UpcomingMatchListView, MatchDetailView

urlpatterns = [
    path("leagues/", LeagueListView.as_view(), name="league-list"),
    path("teams/", TeamListView.as_view(), name="team-list"),
    path("upcoming/", UpcomingMatchListView.as_view(), name="match-upcoming"),
    path("<int:pk>/", MatchDetailView.as_view(), name="match-detail"),
]
