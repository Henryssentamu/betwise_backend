"""
Pulls fixtures, results, and team data from Football-Data.org for each
active league and upserts them into the database.

Run manually:
    python manage.py sync_matches

In production this is scheduled via django-celery-beat (see recommendations
app's celery tasks) to run every few minutes, respecting the free-tier
rate limit of 10 requests/minute.
"""
import time
from datetime import datetime, timezone as dt_timezone

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from matches.models import League, Team, Match

# Football-Data.org competition codes for the five leagues we track.
COMPETITION_CODES = {
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
}


class Command(BaseCommand):
    help = "Sync leagues, teams, and matches from Football-Data.org"

    def add_arguments(self, parser):
        parser.add_argument(
            "--league",
            type=str,
            help="Sync only this league name (must match COMPETITION_CODES key)",
        )

    def handle(self, *args, **options):
        headers = {"X-Auth-Token": settings.FOOTBALL_DATA_API_KEY}
        base_url = settings.FOOTBALL_DATA_BASE_URL

        target_leagues = COMPETITION_CODES
        if options.get("league"):
            name = options["league"]
            if name not in COMPETITION_CODES:
                self.stderr.write(self.style.ERROR(f"Unknown league: {name}"))
                return
            target_leagues = {name: COMPETITION_CODES[name]}

        for league_name, code in target_leagues.items():
            self.stdout.write(f"Syncing {league_name} ({code})...")
            try:
                self._sync_league(base_url, headers, league_name, code)
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    self.stderr.write(
                        self.style.WARNING(
                            f"Rate limited on {league_name}. Skipping — will retry next run."
                        )
                    )
                else:
                    self.stderr.write(self.style.ERROR(f"HTTP error for {league_name}: {exc}"))
            except requests.exceptions.RequestException as exc:
                self.stderr.write(self.style.ERROR(f"Network error for {league_name}: {exc}"))

            # Free tier allows 10 req/min — stay comfortably under that
            # across leagues + team + match calls.
            time.sleep(6)

        self.stdout.write(self.style.SUCCESS("Sync complete."))

    def _sync_league(self, base_url, headers, league_name, code):
        league, _ = League.objects.get_or_create(
            name=league_name,
            defaults={"country": "", "external_source": code},
        )

        # 1. Teams
        teams_resp = requests.get(
            f"{base_url}/competitions/{code}/teams", headers=headers, timeout=15
        )
        teams_resp.raise_for_status()
        teams_payload = teams_resp.json()

        if not league.country and teams_payload.get("competition", {}).get("area"):
            league.country = teams_payload["competition"]["area"].get("name", "")
            league.save(update_fields=["country"])

        team_lookup = {}
        for team_data in teams_payload.get("teams", []):
            team, _ = Team.objects.update_or_create(
                external_id=str(team_data["id"]),
                defaults={
                    "league": league,
                    "name": team_data["name"],
                    "short_name": team_data.get("shortName", "") or "",
                    "logo_url": team_data.get("crest", "") or "",
                },
            )
            team_lookup[team_data["id"]] = team

        time.sleep(6)

        # 2. Matches (fixtures + recent results)
        matches_resp = requests.get(
            f"{base_url}/competitions/{code}/matches", headers=headers, timeout=15
        )
        matches_resp.raise_for_status()
        matches_payload = matches_resp.json()

        for m in matches_payload.get("matches", []):
            home_id = m["homeTeam"]["id"]
            away_id = m["awayTeam"]["id"]
            home_team = team_lookup.get(home_id) or Team.objects.filter(
                external_id=str(home_id)
            ).first()
            away_team = team_lookup.get(away_id) or Team.objects.filter(
                external_id=str(away_id)
            ).first()
            if not home_team or not away_team:
                continue

            status_map = {
                "SCHEDULED": "scheduled",
                "TIMED": "scheduled",
                "IN_PLAY": "live",
                "PAUSED": "live",
                "FINISHED": "finished",
                "POSTPONED": "postponed",
                "SUSPENDED": "postponed",
                "CANCELLED": "postponed",
            }
            status = status_map.get(m["status"], "scheduled")

            full_time = m.get("score", {}).get("fullTime", {})
            home_score = full_time.get("home")
            away_score = full_time.get("away")

            result = ""
            if status == "finished" and home_score is not None:
                if home_score > away_score:
                    result = "home_win"
                elif away_score > home_score:
                    result = "away_win"
                else:
                    result = "draw"

            kickoff = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))

            Match.objects.update_or_create(
                external_id=str(m["id"]),
                defaults={
                    "league": league,
                    "home_team": home_team,
                    "away_team": away_team,
                    "kickoff_at": kickoff,
                    "status": status,
                    "home_score": home_score,
                    "away_score": away_score,
                    "result": result,
                },
            )
