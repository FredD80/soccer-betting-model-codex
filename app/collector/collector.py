import logging
from datetime import datetime, timedelta, timezone
from app.db.models import League, Team, Fixture, OddsSnapshot
from app.collector.odds_api import OddsAPIClient
from app.collector.espn_api import ESPNClient

logger = logging.getLogger(__name__)
UPCOMING_FIXTURE_WINDOW_DAYS = 30
TEAM_TOTAL_CAPTURE_WINDOW_DAYS = 7

ESPN_TO_ODDS_API_LEAGUE = {
    "eng.1": "soccer_epl",
    "esp.1": "soccer_spain_la_liga",
    "ger.1": "soccer_germany_bundesliga",
    "ita.1": "soccer_italy_serie_a",
    "fra.1": "soccer_france_ligue_one",
    "por.1": "soccer_portugal_primeira_liga",
    "usa.1": "soccer_usa_mls",
    "uefa.champions": "soccer_uefa_champs_league",
}


class DataCollector:
    def __init__(self, session, odds_client=None, espn_client=None):
        self.session = session
        if odds_client is None or espn_client is None:
            from app.config import settings
        self.odds_client = odds_client or OddsAPIClient(api_key=settings.odds_api_key)
        self.espn_client = espn_client or ESPNClient()

    def run(self):
        now = datetime.now(timezone.utc)
        espn_data = self.espn_client.fetch_all_leagues(
            start_date=now,
            end_date=now + timedelta(days=UPCOMING_FIXTURE_WINDOW_DAYS),
        )
        odds_data = self.odds_client.fetch_all_leagues()

        for espn_id, fixtures in espn_data.items():
            league = self.session.query(League).filter_by(espn_id=espn_id).first()
            if not league:
                continue
            for espn_fixture in fixtures:
                fixture = self._upsert_fixture(espn_fixture, league)
                sport_key = ESPN_TO_ODDS_API_LEAGUE.get(espn_id)
                if not sport_key:
                    continue
                odds_fixture = self._find_odds_fixture(
                    odds_data.get(sport_key, []),
                    espn_fixture["home_team"],
                    espn_fixture["away_team"],
                )
                if odds_fixture:
                    team_totals_by_bookmaker = self._team_totals_by_bookmaker(
                        odds_fixture=odds_fixture,
                        sport_key=sport_key,
                        kickoff_at=fixture.kickoff_at,
                        now=now,
                    )
                    for bookmaker in odds_fixture["bookmakers"]:
                        bookmaker = dict(bookmaker)
                        bookmaker["team_totals_1_5"] = team_totals_by_bookmaker.get(bookmaker["key"])
                        self._save_odds_snapshot(fixture.id, bookmaker)
                else:
                    logger.warning(
                        "No odds match found for %s vs %s (league: %s)",
                        espn_fixture["home_team"],
                        espn_fixture["away_team"],
                        espn_id,
                    )

        self.session.commit()

    def _upsert_fixture(self, espn_fixture: dict, league: League) -> Fixture:
        existing = self.session.query(Fixture).filter_by(espn_id=espn_fixture["espn_id"]).first()
        home_team = self._upsert_team(espn_fixture["home_team"], league)
        away_team = self._upsert_team(espn_fixture["away_team"], league)

        if existing:
            existing.status = espn_fixture["status"]
            existing.kickoff_at = datetime.fromisoformat(espn_fixture["kickoff_at"].replace("Z", "+00:00"))
            return existing

        fixture = Fixture(
            espn_id=espn_fixture["espn_id"],
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            league_id=league.id,
            kickoff_at=datetime.fromisoformat(espn_fixture["kickoff_at"].replace("Z", "+00:00")),
            status=espn_fixture["status"],
        )
        self.session.add(fixture)
        self.session.flush()
        return fixture

    def _upsert_team(self, name: str, league: League) -> Team:
        team = self.session.query(Team).filter_by(name=name, league_id=league.id).first()
        if not team:
            team = Team(name=name, league_id=league.id)
            self.session.add(team)
            self.session.flush()
        return team

    def _save_odds_snapshot(self, fixture_id: int, bookmaker: dict):
        h2h = bookmaker.get("h2h") or {}
        totals = bookmaker.get("totals") or {}
        ht_h2h = bookmaker.get("ht_h2h") or {}
        ht_totals = bookmaker.get("ht_totals") or {}
        spreads = bookmaker.get("spreads") or {}
        team_totals = bookmaker.get("team_totals_1_5") or {}
        home_team_totals = team_totals.get("home") or {}
        away_team_totals = team_totals.get("away") or {}

        snap = OddsSnapshot(
            fixture_id=fixture_id,
            bookmaker=bookmaker["key"],
            home_odds=h2h.get("home"),
            draw_odds=h2h.get("draw"),
            away_odds=h2h.get("away"),
            ht_home_odds=ht_h2h.get("home"),
            ht_draw_odds=ht_h2h.get("draw"),
            ht_away_odds=ht_h2h.get("away"),
            total_goals_line=totals.get("line"),
            over_odds=totals.get("over"),
            under_odds=totals.get("under"),
            ht_goals_line=ht_totals.get("line"),
            ht_over_odds=ht_totals.get("over"),
            ht_under_odds=ht_totals.get("under"),
            spread_home_line=spreads.get("home_line"),
            spread_home_odds=spreads.get("home_odds"),
            spread_away_line=spreads.get("away_line"),
            spread_away_odds=spreads.get("away_odds"),
            home_team_total_1_5_over_odds=home_team_totals.get("over"),
            home_team_total_1_5_under_odds=home_team_totals.get("under"),
            away_team_total_1_5_over_odds=away_team_totals.get("over"),
            away_team_total_1_5_under_odds=away_team_totals.get("under"),
            captured_at=datetime.now(timezone.utc),
        )
        self.session.add(snap)

    def _team_totals_by_bookmaker(
        self,
        *,
        odds_fixture: dict,
        sport_key: str,
        kickoff_at: datetime,
        now: datetime,
    ) -> dict[str, dict]:
        odds_api_id = odds_fixture.get("odds_api_id")
        if not odds_api_id:
            return {}
        if kickoff_at > now + timedelta(days=TEAM_TOTAL_CAPTURE_WINDOW_DAYS):
            return {}

        try:
            event_odds = self.odds_client.fetch_event_team_totals(sport_key, odds_api_id)
        except Exception as exc:
            logger.warning("Failed team-total fetch for odds event %s: %s", odds_api_id, exc)
            return {}

        return {
            bookmaker["key"]: bookmaker.get("team_totals_1_5")
            for bookmaker in event_odds.get("bookmakers", [])
            if bookmaker.get("team_totals_1_5")
        }

    def _find_odds_fixture(self, odds_fixtures: list, home_team: str, away_team: str) -> dict | None:
        """
        Match an Odds-API fixture to a pair of ESPN team names via the
        shared team_matcher. Both sides must resolve to the same Team row
        before we accept the match.
        """
        from app.team_matcher import resolve_team
        from app.db.models import Team
        espn_home = (
            self.session.query(Team).filter_by(name=home_team).first()
        )
        espn_away = (
            self.session.query(Team).filter_by(name=away_team).first()
        )
        if not espn_home or not espn_away:
            return None
        for f in odds_fixtures:
            odds_home = resolve_team(
                self.session, espn_home.league_id, f["home_team"], "odds_api"
            )
            odds_away = resolve_team(
                self.session, espn_away.league_id, f["away_team"], "odds_api"
            )
            if odds_home and odds_away and \
               odds_home.id == espn_home.id and odds_away.id == espn_away.id:
                return f
        return None
