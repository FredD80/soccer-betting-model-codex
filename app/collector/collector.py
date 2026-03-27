from datetime import datetime, timezone
from app.db.models import League, Team, Fixture, OddsSnapshot
from app.collector.odds_api import OddsAPIClient
from app.collector.espn_api import ESPNClient
from app.config import settings

ESPN_TO_ODDS_API_LEAGUE = {
    "eng.1": "soccer_epl",
    "esp.1": "soccer_spain_la_liga",
    "ger.1": "soccer_germany_bundesliga",
    "ita.1": "soccer_italy_serie_a",
}


class DataCollector:
    def __init__(self, session):
        self.session = session
        self.odds_client = OddsAPIClient(api_key=settings.odds_api_key)
        self.espn_client = ESPNClient()

    def run(self):
        espn_data = self.espn_client.fetch_all_leagues()
        odds_data = self.odds_client.fetch_all_leagues()

        for espn_id, fixtures in espn_data.items():
            league = self.session.query(League).filter_by(espn_id=espn_id).first()
            if not league:
                continue
            for espn_fixture in fixtures:
                fixture = self._upsert_fixture(espn_fixture, league)
                sport_key = ESPN_TO_ODDS_API_LEAGUE[espn_id]
                odds_fixture = self._find_odds_fixture(
                    odds_data.get(sport_key, []),
                    espn_fixture["home_team"],
                    espn_fixture["away_team"],
                )
                if odds_fixture:
                    for bookmaker in odds_fixture["bookmakers"]:
                        self._save_odds_snapshot(fixture.id, bookmaker)

        self.session.commit()

    def _upsert_fixture(self, espn_fixture: dict, league: League) -> Fixture:
        existing = self.session.query(Fixture).filter_by(espn_id=espn_fixture["espn_id"]).first()
        home_team = self._upsert_team(espn_fixture["home_team"], league)
        away_team = self._upsert_team(espn_fixture["away_team"], league)

        if existing:
            existing.status = espn_fixture["status"]
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
            captured_at=datetime.now(timezone.utc),
        )
        self.session.add(snap)

    def _find_odds_fixture(self, odds_fixtures: list, home_team: str, away_team: str) -> dict | None:
        for f in odds_fixtures:
            if f["home_team"] == home_team and f["away_team"] == away_team:
                return f
        return None
