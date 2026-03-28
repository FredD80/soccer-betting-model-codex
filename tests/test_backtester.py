from datetime import datetime, timezone, timedelta
from app.backtester import Backtester
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Result, BacktestRun
from app.models.base import BaseModel, ModelPrediction


class AlwaysHomeModel(BaseModel):
    name = "always_home"
    version = "1.0"

    def predict(self, fixture, odds, history):
        return [ModelPrediction(bet_type="match_result", outcome="home", confidence=0.7, line=None)]


def seed_historical(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    mv = ModelVersion(name="always_home", version="1.0", active=False, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()

    kickoff = datetime.now(timezone.utc) - timedelta(days=7)
    fixture = Fixture(espn_id="e1", home_team_id=home.id, away_team_id=away.id,
                      league_id=league.id, kickoff_at=kickoff, status="completed")
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(fixture_id=fixture.id, bookmaker="betmgm",
                        home_odds=2.10, draw_odds=3.50, away_odds=3.20,
                        total_goals_line=2.5, over_odds=1.90, under_odds=1.90,
                        captured_at=kickoff - timedelta(hours=2))
    db.add(snap)
    db.flush()
    result = Result(fixture_id=fixture.id, home_score=2, away_score=0, outcome="home",
                    ht_home_score=1, ht_away_score=0, ht_outcome="home",
                    total_goals=2, ht_total_goals=1, verified_at=kickoff + timedelta(hours=2))
    db.add(result)
    db.flush()
    return mv, kickoff


def test_backtest_creates_run_record(db):
    mv, kickoff = seed_historical(db)
    backtester = Backtester(db, model_classes=[AlwaysHomeModel])
    date_from = kickoff - timedelta(days=1)
    date_to = kickoff + timedelta(days=1)
    backtester.run("always_home", "1.0", date_from, date_to)
    run = db.query(BacktestRun).first()
    assert run is not None
    assert run.model_id == mv.id
    assert run.total == 1
    assert run.correct == 1
    assert run.accuracy == 1.0


def test_backtest_does_not_write_to_predictions_table(db):
    from app.db.models import Prediction
    mv, kickoff = seed_historical(db)
    backtester = Backtester(db, model_classes=[AlwaysHomeModel])
    date_from = kickoff - timedelta(days=1)
    date_to = kickoff + timedelta(days=1)
    backtester.run("always_home", "1.0", date_from, date_to)
    assert db.query(Prediction).count() == 0
