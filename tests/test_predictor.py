# tests/test_predictor.py
from datetime import datetime, timedelta, timezone
from app.predictor import PredictionEngine
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction
from app.models.base import BaseModel, ModelPrediction


class AlwaysHomeModel(BaseModel):
    name = "always_home"
    version = "1.0"

    def predict(self, fixture, odds, history):
        return [
            ModelPrediction(bet_type="match_result", outcome="home", confidence=0.70, line=None),
            ModelPrediction(bet_type="total_goals", outcome="over", confidence=0.60, line=2.5),
        ]


def make_fixture_with_odds(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    kickoff = datetime.now(timezone.utc) + timedelta(hours=1)
    fixture = Fixture(espn_id="e1", home_team_id=home.id, away_team_id=away.id,
                      league_id=league.id, kickoff_at=kickoff, status="scheduled")
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(fixture_id=fixture.id, bookmaker="betmgm",
                        home_odds=2.10, draw_odds=3.50, away_odds=3.20,
                        total_goals_line=2.5, over_odds=1.90, under_odds=1.90,
                        captured_at=datetime.now(timezone.utc))
    db.add(snap)
    db.flush()
    return fixture, snap


def test_engine_stores_predictions_for_active_models(db):
    fixture, snap = make_fixture_with_odds(db)
    mv = ModelVersion(name="always_home", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()

    engine = PredictionEngine(db, model_classes=[AlwaysHomeModel], lead_hours=2)
    engine.run()

    preds = db.query(Prediction).all()
    assert len(preds) == 2
    bet_types = {p.bet_type for p in preds}
    assert "match_result" in bet_types
    assert "total_goals" in bet_types


def test_engine_tags_prediction_with_model_id(db):
    fixture, snap = make_fixture_with_odds(db)
    mv = ModelVersion(name="always_home", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()

    engine = PredictionEngine(db, model_classes=[AlwaysHomeModel], lead_hours=2)
    engine.run()

    pred = db.query(Prediction).filter_by(bet_type="match_result").first()
    assert pred.model_id == mv.id
    assert pred.predicted_outcome == "home"
    assert pred.confidence == 0.70


def test_engine_skips_fixtures_without_odds(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    kickoff = datetime.now(timezone.utc) + timedelta(hours=1)
    fixture = Fixture(espn_id="e1", home_team_id=home.id, away_team_id=away.id,
                      league_id=league.id, kickoff_at=kickoff, status="scheduled")
    db.add(fixture)
    db.flush()
    mv = ModelVersion(name="always_home", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()

    engine = PredictionEngine(db, model_classes=[AlwaysHomeModel], lead_hours=2)
    engine.run()

    assert db.query(Prediction).count() == 0
