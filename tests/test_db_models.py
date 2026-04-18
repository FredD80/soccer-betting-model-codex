from app.db.models import (
    League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction, Result,
    Performance, BacktestRun, BacktestJob, SchedulerLog, PredictionOutcome, ManualPick,
    EloFormPrediction,
)
from datetime import datetime, timezone


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


def test_odds_snapshot_has_spread_fields(db):
    from app.db.models import League, Team, Fixture, OddsSnapshot

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="x1", home_team_id=home.id, away_team_id=away.id,
        league_id=league.id, kickoff_at=datetime.now(timezone.utc),
    )
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(
        fixture_id=fixture.id, bookmaker="betmgm",
        home_odds=2.1, draw_odds=3.5, away_odds=3.2,
        total_goals_line=2.5, over_odds=1.9, under_odds=1.9,
        spread_home_line=-0.5, spread_home_odds=1.95,
        spread_away_line=0.5, spread_away_odds=1.85,
        captured_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    db.flush()
    fetched = db.query(OddsSnapshot).filter_by(id=snap.id).first()
    assert fetched.spread_home_line == -0.5
    assert fetched.spread_home_odds == 1.95
    assert fetched.spread_away_line == 0.5
    assert fetched.spread_away_odds == 1.85


def test_result_has_red_card_minute(db):
    from app.db.models import League, Team, Fixture, Result

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="rc1", home_team_id=home.id, away_team_id=away.id,
        league_id=league.id, kickoff_at=datetime.now(timezone.utc),
    )
    db.add(fixture)
    db.flush()
    result = Result(
        fixture_id=fixture.id,
        home_score=3, away_score=0,
        outcome="home", total_goals=3,
        red_card_minute=25,
        verified_at=datetime.now(timezone.utc),
    )
    db.add(result)
    db.flush()
    fetched = db.query(Result).filter_by(id=result.id).first()
    assert fetched.red_card_minute == 25


def _make_fixture(db, espn_id="f1"):
    from app.db.models import League, Team, Fixture
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id=espn_id, home_team_id=home.id, away_team_id=away.id,
        league_id=league.id, kickoff_at=datetime.now(timezone.utc),
    )
    db.add(fixture)
    db.flush()
    return fixture, home, away


def test_form_cache_model(db):
    from app.db.models import FormCache
    _, team, _ = _make_fixture(db)
    fc = FormCache(
        team_id=team.id,
        is_home=True,
        goals_scored_avg=1.8,
        goals_conceded_avg=0.9,
        spread_cover_rate=0.6,
        ou_hit_rate_15=0.9,
        ou_hit_rate_25=0.55,
        ou_hit_rate_35=0.2,
        matches_count=5,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(fc)
    db.flush()
    fetched = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert fetched.goals_scored_avg == 1.8
    assert fetched.matches_count == 5


def test_spread_prediction_model(db):
    from app.db.models import SpreadPrediction, ModelVersion
    fixture, _, _ = _make_fixture(db, espn_id="sp1")
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    sp = SpreadPrediction(
        model_id=mv.id,
        fixture_id=fixture.id,
        team_side="home",
        goal_line=-0.5,
        cover_probability=0.62,
        push_probability=0.0,
        ev_score=0.08,
        confidence_tier="HIGH",
        created_at=datetime.now(timezone.utc),
    )
    db.add(sp)
    db.flush()
    fetched = db.query(SpreadPrediction).filter_by(id=sp.id).first()
    assert fetched.goal_line == -0.5
    assert fetched.confidence_tier == "HIGH"


def test_ou_analysis_model(db):
    from app.db.models import OUAnalysis, ModelVersion
    fixture, _, _ = _make_fixture(db, espn_id="ou1")
    mv = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    ou = OUAnalysis(
        model_id=mv.id,
        fixture_id=fixture.id,
        line=2.5,
        direction="over",
        probability=0.58,
        ev_score=0.06,
        confidence_tier="HIGH",
        created_at=datetime.now(timezone.utc),
    )
    db.add(ou)
    db.flush()
    fetched = db.query(OUAnalysis).filter_by(id=ou.id).first()
    assert fetched.line == 2.5
    assert fetched.direction == "over"


def test_prediction_outcome_model(db):
    fixture, _, _ = _make_fixture(db, espn_id="po1")
    mv = ModelVersion(name="moneyline_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    outcome = PredictionOutcome(
        fixture_id=fixture.id,
        model_id=mv.id,
        market_type="moneyline",
        prediction_row_id=123,
        selection="home",
        decimal_odds=2.1,
        american_odds=110,
        model_probability=0.51,
        final_probability=0.49,
        edge_pct=0.03,
        kelly_fraction=0.01,
        confidence_tier="HIGH",
        result_status="win",
        profit_units=1.1,
        graded_at=datetime.now(timezone.utc),
    )
    db.add(outcome)
    db.flush()
    fetched = db.query(PredictionOutcome).filter_by(id=outcome.id).first()
    assert fetched.market_type == "moneyline"
    assert fetched.result_status == "win"


def test_backtest_run_model_supports_bully_metrics(db):
    mv = ModelVersion(name="elo_bully_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    row = BacktestRun(
        model_id=mv.id,
        bet_type="bully",
        date_from=datetime.now(timezone.utc),
        date_to=datetime.now(timezone.utc),
        total=12,
        correct=8,
        accuracy=8 / 12,
        roi=0.14,
        two_plus_hit_rate=0.58,
        clean_sheet_hit_rate=0.33,
        two_plus_given_win_rate=0.75,
        clean_sheet_given_win_rate=0.5,
        run_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()

    fetched = db.query(BacktestRun).filter_by(id=row.id).first()
    assert fetched.bet_type == "bully"
    assert fetched.backtest_job_id is None
    assert fetched.two_plus_hit_rate == 0.58
    assert fetched.clean_sheet_hit_rate == 0.33
    assert fetched.two_plus_given_win_rate == 0.75
    assert fetched.clean_sheet_given_win_rate == 0.5


def test_backtest_job_model(db):
    row = BacktestJob(
        task_id="celery-123",
        status="queued",
        requested_markets="spread,bully",
        date_from=datetime.now(timezone.utc),
        date_to=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()

    fetched = db.query(BacktestJob).filter_by(id=row.id).first()
    assert fetched.task_id == "celery-123"
    assert fetched.status == "queued"
    assert fetched.requested_markets == "spread,bully"


def test_manual_pick_model(db):
    fixture, _, _ = _make_fixture(db, espn_id="mp1")
    pick = ManualPick(
        fixture_id=fixture.id,
        market_type="ou",
        selection="over",
        line=2.5,
        decimal_odds=1.95,
        american_odds=-105,
        stake_units=2.0,
        bookmaker="draftkings",
        notes="late add",
        result_status="open",
    )
    db.add(pick)
    db.flush()
    fetched = db.query(ManualPick).filter_by(id=pick.id).first()
    assert fetched.market_type == "ou"
    assert fetched.stake_units == 2.0


def test_elo_form_prediction_model(db):
    fixture, _, _ = _make_fixture(db, espn_id="elo1")
    mv = ModelVersion(name="elo_form_v1", version="1.0", active=False)
    db.add(mv)
    db.flush()
    row = EloFormPrediction(
        model_id=mv.id,
        fixture_id=fixture.id,
        favorite_side="home",
        elo_gap=128.0,
        is_bully_spot=True,
        home_elo=1588.0,
        away_elo=1460.0,
        home_form_for_avg=1.94,
        home_form_against_avg=0.82,
        away_form_for_avg=0.77,
        away_form_against_avg=1.71,
        home_xg_diff_avg=0.62,
        away_xg_diff_avg=-0.31,
        home_xg_trend=-0.14,
        away_xg_trend=0.09,
        home_xg_matches_used=5,
        away_xg_matches_used=5,
        trend_adjustment=-0.04,
        home_probability=0.49,
        draw_probability=0.24,
        away_probability=0.27,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    fetched = db.query(EloFormPrediction).filter_by(id=row.id).first()
    assert fetched.home_elo == 1588.0
    assert fetched.is_bully_spot is True
    assert fetched.home_form_for_avg == 1.94
    assert fetched.away_form_against_avg == 1.71
    assert fetched.away_xg_trend == 0.09
    assert fetched.home_probability + fetched.draw_probability + fetched.away_probability == 1.0
