from django.db import models


class League(models.Model):
    name = models.CharField(max_length=100, unique=True)
    country = models.CharField(max_length=64)
    external_source = models.CharField(
        max_length=64, help_text="e.g. football-data.org competition code"
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Team(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=20, blank=True)
    external_id = models.CharField(max_length=64, unique=True)
    logo_url = models.URLField(blank=True)

    current_form_score = models.FloatField(
        default=0, help_text="Rolling form rating, recalculated after each match"
    )

    class Meta:
        unique_together = ("league", "name")

    def __str__(self):
        return self.name


class Match(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("live", "Live"),
        ("finished", "Finished"),
        ("postponed", "Postponed"),
    ]

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="matches")
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="home_matches")
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="away_matches")
    external_id = models.CharField(max_length=64, unique=True)

    kickoff_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="scheduled")

    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)

    RESULT_CHOICES = [("home_win", "Home win"), ("away_win", "Away win"), ("draw", "Draw")]
    result = models.CharField(max_length=10, choices=RESULT_CHOICES, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["kickoff_at", "status"])]
        ordering = ["kickoff_at"]

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} — {self.kickoff_at:%Y-%m-%d}"


class HeadToHead(models.Model):
    """
    Precomputed head-to-head summary between two teams, refreshed after each
    meeting so the recommendation engine doesn't recompute from scratch every time.
    """
    team_a = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="h2h_as_a")
    team_b = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="h2h_as_b")
    matches_considered = models.PositiveSmallIntegerField(default=10)
    team_a_wins = models.PositiveSmallIntegerField(default=0)
    team_b_wins = models.PositiveSmallIntegerField(default=0)
    draws = models.PositiveSmallIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("team_a", "team_b")


class TeamNews(models.Model):
    """
    Injury and squad-availability signals pulled from the news scraper source.
    """
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="news_items")
    player_name = models.CharField(max_length=100, blank=True)

    SEVERITY_CHOICES = [
        ("minor", "Minor — likely available"),
        ("major", "Major — likely unavailable"),
        ("confirmed_out", "Confirmed out"),
    ]
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    note = models.CharField(max_length=255)
    source_url = models.URLField(blank=True)
    reported_at = models.DateTimeField()

    class Meta:
        ordering = ["-reported_at"]
