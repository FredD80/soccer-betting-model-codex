from datetime import datetime, timezone, timedelta
from app.tracker import ResultsTracker
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction, Result, Performance


def make_completed_fixture(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    kickoff = datetime.now(timezone.utc) - timedelta(hours=3)
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
    mv = ModelVersion(name="my_model", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()
    pred = Prediction(model_id=mv.id, fixture_id=fixture.id, bet_type="match_result",
                      predicted_outcome="home", confidence=0.70, line=None,
                      odds_snapshot_id=snap.id, created_at=kickoff - timedelta(hours=1))
    db.add(pred)
    db.flush()
    return fixture, snap, mv, pred


def test_save_result_stores_outcome(db):
    fixture, _, _, _ = make_completed_fixture(db)
    tracker = ResultsTracker(db)
    tracker.save_result(fixture.id, home_score=2, away_score=1,
                        ht_home_score=1, ht_away_score=0)
    result = db.query(Result).first()
    assert result.outcome == "home"
    assert result.ht_outcome == "home"
    assert result.total_goals == 3
    assert result.ht_total_goals == 1


def test_evaluate_correct_match_result_prediction(db):
    fixture, snap, mv, pred = make_completed_fixture(db)
    result = Result(fixture_id=fixture.id, home_score=2, away_score=1, outcome="home",
                    ht_home_score=1, ht_away_score=0, ht_outcome="home",
                    total_goals=3, ht_total_goals=1, verified_at=datetime.now(timezone.utc))
    db.add(result)
    db.flush()
    tracker = ResultsTracker(db)
    tracker.evaluate_predictions(fixture.id)
    perf = db.query(Performance).filter_by(model_id=mv.id, bet_type="match_result").first()
    assert perf.total_predictions == 1
    assert perf.correct == 1
    assert perf.accuracy == 1.0
    assert round(perf.roi, 4) == round(snap.home_odds - 1, 4)


def test_evaluate_incorrect_prediction_gives_negative_roi(db):
    fixture, snap, mv, pred = make_completed_fixture(db)
    result = Result(fixture_id=fixture.id, home_score=0, away_score=2, outcome="away",
                    ht_home_score=0, ht_away_score=1, ht_outcome="away",
                    total_goals=2, ht_total_goals=1, verified_at=datetime.now(timezone.utc))
    db.add(result)
    db.flush()
    tracker = ResultsTracker(db)
    tracker.evaluate_predictions(fixture.id)
    perf = db.query(Performance).filter_by(model_id=mv.id, bet_type="match_result").first()
    assert perf.correct == 0
    assert perf.roi == -1.0
