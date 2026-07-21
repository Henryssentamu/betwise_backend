from rest_framework import serializers
from .models import League, Team, Match, HeadToHead, TeamNews


class LeagueSerializer(serializers.ModelSerializer):
    class Meta:
        model = League
        fields = ["id", "name", "country", "is_active"]


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name", "short_name", "logo_url", "current_form_score"]


class TeamNewsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamNews
        fields = ["id", "player_name", "severity", "note", "reported_at"]


class HeadToHeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = HeadToHead
        fields = ["matches_considered", "team_a_wins", "team_b_wins", "draws", "last_updated"]


class MatchListSerializer(serializers.ModelSerializer):
    """Lightweight — used for match lists / fixtures screens."""
    home_team = TeamSerializer(read_only=True)
    away_team = TeamSerializer(read_only=True)
    league = LeagueSerializer(read_only=True)

    class Meta:
        model = Match
        fields = [
            "id", "league", "home_team", "away_team",
            "kickoff_at", "status", "home_score", "away_score", "result",
        ]


class MatchDetailSerializer(serializers.ModelSerializer):
    """
    Full detail — powers the 'why this pick' reasoning screen, so it bundles
    head-to-head and squad news for both teams alongside the fixture.
    """
    home_team = TeamSerializer(read_only=True)
    away_team = TeamSerializer(read_only=True)
    league = LeagueSerializer(read_only=True)
    head_to_head = serializers.SerializerMethodField()
    home_team_news = serializers.SerializerMethodField()
    away_team_news = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = [
            "id", "league", "home_team", "away_team", "kickoff_at", "status",
            "home_score", "away_score", "result",
            "head_to_head", "home_team_news", "away_team_news",
        ]

    def get_head_to_head(self, obj):
        h2h = HeadToHead.objects.filter(
            team_a__in=[obj.home_team, obj.away_team],
            team_b__in=[obj.home_team, obj.away_team],
        ).first()
        return HeadToHeadSerializer(h2h).data if h2h else None

    def get_home_team_news(self, obj):
        news = obj.home_team.news_items.all()[:5]
        return TeamNewsSerializer(news, many=True).data

    def get_away_team_news(self, obj):
        news = obj.away_team.news_items.all()[:5]
        return TeamNewsSerializer(news, many=True).data
