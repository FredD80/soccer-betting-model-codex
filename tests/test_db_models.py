from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction, Result, Performance, BacktestRun, SchedulerLog
from datetime import datetime


def test_league_table_exists(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    assert league.id is not None


def test_model_version_table_exists(db):
    mv = ModelVersion(name="test_model", version="1.0", description="test", active=False)
    db.add(mv)
    db.flush()
    assert mv.id is not None


def test_odds_snapshot_stores_all_bet_types(db):
    league = League(name="La Liga", country="Spain", espn_id="esp.1", odds_api_key="soccer_spain_la_liga")
    db.add(league)
    db.flush()
    home_team = Team(name="Barcelona", league_id=league.id)
    away_team = Team(name="Real Madrid", league_id=league.id)
    db.add_all([home_team, away_team])
    db.flush()
    fixture = Fixture(home_team_id=home_team.id, away_team_id=away_team.id,
                      league_id=league.id, kickoff_at=datetime(2026, 4, 1, 20, 0))
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(
        fixture_id=fixture.id, bookmaker="betmgm",
        home_odds=2.10, draw_odds=3.50, away_odds=3.20,
        total_goals_line=2.5, over_odds=1.90, under_odds=1.90,
        ht_goals_line=1.5, ht_over_odds=2.00, ht_under_odds=1.80,
        captured_at=datetime.utcnow()
    )
    db.add(snap)
    db.flush()
    assert snap.id is not None
    assert snap.total_goals_line == 2.5
    assert snap.ht_goals_line == 1.5
