from unittest.mock import MagicMock, patch
from datetime import datetime
from app.collector.collector import DataCollector
from app.db.models import League, Team, Fixture, OddsSnapshot


def make_league(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    return league


def test_collect_upserts_teams(db):
    league = make_league(db)
    espn_fixtures = [{"espn_id": "e1", "kickoff_at": "2026-04-01T15:00Z",
                      "home_team": "Arsenal", "away_team": "Chelsea",
                      "status": "scheduled", "home_score": None, "away_score": None,
                      "ht_home_score": None, "ht_away_score": None}]
    collector = DataCollector(db)
    collector._upsert_fixture(espn_fixtures[0], league)
    teams = db.query(Team).all()
    assert {t.name for t in teams} == {"Arsenal", "Chelsea"}


def test_collect_upserts_fixture(db):
    league = make_league(db)
    espn_fixture = {"espn_id": "e1", "kickoff_at": "2026-04-01T15:00Z",
                    "home_team": "Arsenal", "away_team": "Chelsea",
                    "status": "scheduled", "home_score": None, "away_score": None,
                    "ht_home_score": None, "ht_away_score": None}
    collector = DataCollector(db)
    fixture = collector._upsert_fixture(espn_fixture, league)
    assert fixture.espn_id == "e1"
    # Run again — should not create a duplicate
    fixture2 = collector._upsert_fixture(espn_fixture, league)
    assert db.query(Fixture).count() == 1


def test_save_odds_snapshot_creates_row(db):
    league = make_league(db)
    home_team = Team(name="Arsenal", league_id=league.id)
    away_team = Team(name="Chelsea", league_id=league.id)
    db.add_all([home_team, away_team])
    db.flush()
    fixture = Fixture(home_team_id=home_team.id, away_team_id=away_team.id,
                      league_id=league.id, kickoff_at=datetime(2026, 4, 1, 15, 0),
                      espn_id="e1", status="scheduled")
    db.add(fixture)
    db.flush()

    bookmaker_data = {
        "key": "betmgm", "title": "BetMGM",
        "h2h": {"home": 2.10, "draw": 3.50, "away": 3.20},
        "totals": {"line": 2.5, "over": 1.90, "under": 1.90},
        "ht_h2h": None, "ht_totals": None,
    }
    collector = DataCollector(db)
    collector._save_odds_snapshot(fixture.id, bookmaker_data)
    snap = db.query(OddsSnapshot).first()
    assert snap.bookmaker == "betmgm"
    assert snap.home_odds == 2.10
    assert snap.total_goals_line == 2.5
    assert snap.ht_goals_line is None
