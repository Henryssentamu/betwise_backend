from django.contrib import admin
from .models import League, Team, Match, HeadToHead, TeamNews


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "external_source", "is_active")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "league", "current_form_score")
    list_filter = ("league",)
    search_fields = ("name",)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("__str__", "league", "status", "result", "kickoff_at")
    list_filter = ("league", "status")
    date_hierarchy = "kickoff_at"


@admin.register(HeadToHead)
class HeadToHeadAdmin(admin.ModelAdmin):
    list_display = ("team_a", "team_b", "team_a_wins", "team_b_wins", "draws", "last_updated")


@admin.register(TeamNews)
class TeamNewsAdmin(admin.ModelAdmin):
    list_display = ("team", "player_name", "severity", "reported_at")
    list_filter = ("severity",)
