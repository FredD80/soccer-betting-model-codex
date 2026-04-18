from datetime import datetime, timezone, timedelta
from app.tracker import ResultsTracker
from app.db.models import (
    League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction, Result, Performance,
    MoneylinePrediction, SpreadPrediction, OUAnalysis, PredictionOutcome, ManualPick,
    EloFormPrediction,
    WeeklyModelPick,
)


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


def make_live_fixture(db, espn_id="live1"):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Liverpool", league_id=league.id)
    away = Team(name="Brighton", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    kickoff = datetime.now(timezone.utc) - timedelta(hours=4)
    fixture = Fixture(
        espn_id=espn_id,
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="completed",
    )
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(
        fixture_id=fixture.id,
        bookmaker="pinnacle",
        home_odds=1.80,
        draw_odds=3.70,
        away_odds=4.50,
        total_goals_line=2.0,
        over_odds=1.95,
        under_odds=1.85,
        spread_home_line=-1.0,
        spread_home_odds=2.05,
        spread_away_line=1.0,
        spread_away_odds=1.80,
        captured_at=kickoff - timedelta(hours=2),
    )
    db.add(snap)
    db.flush()
    ml_model = ModelVersion(name="moneyline_v1", version="1.0", active=True)
    spread_model = ModelVersion(name="spread_v1", version="1.0", active=True)
    ou_model = ModelVersion(name="ou_v1", version="1.0", active=True)
    bully_model = ModelVersion(name="elo_bully_v1", version="1.0", active=True)
    db.add_all([ml_model, spread_model, ou_model, bully_model])
    db.flush()
    db.add(MoneylinePrediction(
        model_id=ml_model.id,
        fixture_id=fixture.id,
        outcome="home",
        probability=0.59,
        final_probability=0.57,
        edge_pct=0.01,
        kelly_fraction=0.01,
        confidence_tier="HIGH",
        odds_snapshot_id=snap.id,
        created_at=kickoff - timedelta(hours=1),
    ))
    db.add(SpreadPrediction(
        model_id=spread_model.id,
        fixture_id=fixture.id,
        team_side="home",
        goal_line=-1.0,
        cover_probability=0.51,
        push_probability=0.19,
        ev_score=0.02,
        final_probability=0.53,
        edge_pct=0.02,
        kelly_fraction=0.02,
        confidence_tier="HIGH",
        odds_snapshot_id=snap.id,
        created_at=kickoff - timedelta(hours=1),
    ))
    db.add(OUAnalysis(
        model_id=ou_model.id,
        fixture_id=fixture.id,
        line=2.0,
        direction="over",
        probability=0.55,
        ev_score=0.03,
        final_probability=0.56,
        edge_pct=0.03,
        kelly_fraction=0.02,
        confidence_tier="ELITE",
        odds_snapshot_id=snap.id,
        created_at=kickoff - timedelta(hours=1),
    ))
    db.add(EloFormPrediction(
        model_id=bully_model.id,
        fixture_id=fixture.id,
        favorite_side="home",
        elo_gap=165.0,
        is_bully_spot=True,
        home_elo=1620.0,
        away_elo=1395.0,
        home_xg_diff_avg=0.9,
        away_xg_diff_avg=-0.4,
        home_xg_trend=0.08,
        away_xg_trend=-0.05,
        home_xg_matches_used=5,
        away_xg_matches_used=5,
        trend_adjustment=0.03,
        home_probability=0.64,
        draw_probability=0.20,
        away_probability=0.16,
        created_at=kickoff - timedelta(hours=1),
    ))
    db.flush()
    return fixture, snap, ml_model, spread_model, ou_model, bully_model


def test_settle_live_predictions_creates_outcome_rows(db):
    fixture, snap, ml_model, spread_model, ou_model, bully_model = make_live_fixture(db)
    db.add(Result(
        fixture_id=fixture.id,
        home_score=2,
        away_score=1,
        outcome="home",
        total_goals=3,
        verified_at=datetime.now(timezone.utc),
    ))
    db.flush()

    tracker = ResultsTracker(db)
    settled = tracker.settle_live_predictions(fixture.id)

    assert settled == 4
    rows = db.query(PredictionOutcome).filter_by(fixture_id=fixture.id).all()
    assert len(rows) == 4

    moneyline_rows = [row for row in rows if row.market_type == "moneyline"]
    assert len(moneyline_rows) == 2
    by_model = {row.model_id: row for row in rows}
    assert by_model[ml_model.id].result_status == "win"
    assert round(by_model[ml_model.id].profit_units, 4) == round(snap.home_odds - 1.0, 4)
    assert by_model[bully_model.id].selection == "home"
    assert by_model[bully_model.id].prediction_row_id < 0
    assert by_model[bully_model.id].result_status == "win"
    assert round(by_model[bully_model.id].profit_units, 4) == round(snap.home_odds - 1.0, 4)
    assert by_model[spread_model.id].result_status == "push"
    assert by_model[spread_model.id].profit_units == 0.0
    assert by_model[ou_model.id].result_status == "win"

    ml_perf = db.query(Performance).filter_by(model_id=ml_model.id, bet_type="moneyline").first()
    bully_perf = db.query(Performance).filter_by(model_id=bully_model.id, bet_type="moneyline").first()
    spread_perf = db.query(Performance).filter_by(model_id=spread_model.id, bet_type="spread").first()
    ou_perf = db.query(Performance).filter_by(model_id=ou_model.id, bet_type="ou").first()
    assert ml_perf.total_predictions == 1
    assert ml_perf.correct == 1
    assert bully_perf.total_predictions == 1
    assert bully_perf.correct == 1
    assert spread_perf.roi == 0.0
    assert ou_perf.correct == 1


def test_settle_live_predictions_is_idempotent(db):
    fixture, _, _, _, _, _ = make_live_fixture(db, espn_id="live2")
    db.add(Result(
        fixture_id=fixture.id,
        home_score=1,
        away_score=0,
        outcome="home",
        total_goals=1,
        verified_at=datetime.now(timezone.utc),
    ))
    db.flush()

    tracker = ResultsTracker(db)
    tracker.settle_live_predictions(fixture.id)
    tracker.settle_live_predictions(fixture.id)

    rows = db.query(PredictionOutcome).filter_by(fixture_id=fixture.id).all()
    assert len(rows) == 4


def test_settle_manual_picks_updates_status_and_profit(db):
    fixture, snap, _, _, _, _ = make_live_fixture(db, espn_id="manual1")
    db.add_all([
        ManualPick(
            fixture_id=fixture.id,
            market_type="moneyline",
            selection="home",
            decimal_odds=1.8,
            american_odds=-125,
            stake_units=2.0,
            result_status="open",
        ),
        ManualPick(
            fixture_id=fixture.id,
            market_type="spread",
            selection="home",
            line=-1.0,
            decimal_odds=2.05,
            american_odds=105,
            stake_units=1.5,
            result_status="open",
        ),
        ManualPick(
            fixture_id=fixture.id,
            market_type="ou",
            selection="under",
            line=2.0,
            decimal_odds=1.85,
            american_odds=-118,
            stake_units=1.0,
            result_status="open",
        ),
    ])
    db.add(Result(
        fixture_id=fixture.id,
        home_score=2,
        away_score=1,
        outcome="home",
        total_goals=3,
        verified_at=datetime.now(timezone.utc),
    ))
    db.flush()

    tracker = ResultsTracker(db)
    settled = tracker.settle_manual_picks(fixture.id)

    assert settled == 3
    picks = db.query(ManualPick).filter_by(fixture_id=fixture.id).all()
    by_market = {pick.market_type: pick for pick in picks}
    assert by_market["moneyline"].result_status == "win"
    assert round(by_market["moneyline"].profit_units, 4) == round((1.8 - 1.0) * 2.0, 4)
    assert by_market["spread"].result_status == "push"
    assert by_market["spread"].profit_units == 0.0
    assert by_market["ou"].result_status == "loss"
    assert by_market["ou"].profit_units == -1.0


def test_settle_weekly_model_picks_updates_status_and_profit(db):
    fixture, snap, ml_model, _, _, _ = make_live_fixture(db, espn_id="weekly-model-1")
    db.add(WeeklyModelPick(
        season_key="2025-26",
        week_start=fixture.kickoff_at.date() - timedelta(days=fixture.kickoff_at.date().weekday()),
        model_view="main",
        model_label="Alpha",
        rank=1,
        fixture_id=fixture.id,
        model_id=ml_model.id,
        market_type="moneyline",
        selection="home",
        decimal_odds=snap.home_odds,
        american_odds=-125,
        result_status="open",
        created_at=fixture.kickoff_at - timedelta(hours=1),
    ))
    db.add(Result(
        fixture_id=fixture.id,
        home_score=2,
        away_score=0,
        outcome="home",
        total_goals=2,
        verified_at=datetime.now(timezone.utc),
    ))
    db.flush()

    tracker = ResultsTracker(db)
    settled = tracker.settle_weekly_model_picks(fixture.id)

    assert settled == 1
    row = db.query(WeeklyModelPick).filter_by(fixture_id=fixture.id).first()
    assert row.result_status == "win"
    assert round(row.profit_units, 4) == round(snap.home_odds - 1.0, 4)
