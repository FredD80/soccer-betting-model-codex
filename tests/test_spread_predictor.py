import pytest
from app.dixon_coles import build_score_matrix, cover_probability_dc
from app.edge_tiers import edge_tier as _confidence_tier


def test_cover_probability_home_minus_half():
    """Home -0.5: home must win. Strong home team should have high win prob."""
    matrix = build_score_matrix(2.5, 0.8, rho=-0.13)
    win_p, push_p = cover_probability_dc(matrix, -0.5)
    assert 0.6 < win_p < 0.99
    assert push_p == 0.0  # no push on -0.5


def test_cover_probability_away_plus_half():
    """Away +0.5: away covers on draw or away win. Home -0.5 + Away +0.5 == 1.0."""
    matrix = build_score_matrix(2.5, 0.8, rho=-0.13)
    win_p_home, _ = cover_probability_dc(matrix, -0.5)
    win_p_away, _ = cover_probability_dc(matrix, 0.5)
    assert abs(win_p_home + win_p_away - 1.0) < 0.001


def test_cover_probability_integer_line_push():
    """Home -1.0: push occurs when home wins by exactly 1."""
    matrix = build_score_matrix(1.5, 1.5, rho=-0.13)
    win_p, push_p = cover_probability_dc(matrix, -1.0)
    lose_p = 1.0 - win_p - push_p
    assert push_p > 0.0
    assert abs(win_p + push_p + lose_p - 1.0) < 0.001


def test_cover_probability_minus_1_and_minus_15_same_win_prob():
    """-1.0 has a push on 1-goal margin; -1.5 treats that margin as a loss."""
    matrix = build_score_matrix(2.0, 1.0, rho=-0.13)
    win_p_1, push_p_1 = cover_probability_dc(matrix, -1.0)
    win_p_15, push_p_15 = cover_probability_dc(matrix, -1.5)
    # Win condition (home wins by 2+) is the same; -1.0 just has push on margin=1
    assert abs(win_p_1 - win_p_15) < 0.001
    assert push_p_1 > 0.0
    assert push_p_15 == 0.0


def test_cover_probability_symmetric_equal_teams():
    """Equal teams: P(home covers -0.5) + P(away covers +0.5) == 1.0."""
    matrix = build_score_matrix(1.5, 1.5, rho=-0.13)
    win_h, _ = cover_probability_dc(matrix, -0.5)
    win_a, _ = cover_probability_dc(matrix, 0.5)
    assert abs(win_h + win_a - 1.0) < 0.001


def test_confidence_tier_elite():
    assert _confidence_tier(0.12) == "ELITE"


def test_confidence_tier_high():
    assert _confidence_tier(0.07) == "HIGH"


def test_confidence_tier_medium():
    assert _confidence_tier(0.03) == "MEDIUM"


def test_confidence_tier_skip_low():
    assert _confidence_tier(0.01) == "SKIP"


def test_confidence_tier_skip_none():
    assert _confidence_tier(None) == "SKIP"


def test_spread_predictor_generates_predictions(db):
    from datetime import datetime, timezone, timedelta
    from app.db.models import (
        League, Team, Fixture, FormCache, ModelVersion, SpreadPrediction
    )
    from app.spread_predictor import SpreadPredictor

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="sp_test",
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="scheduled",
    )
    db.add(fixture)
    db.flush()
    db.add(FormCache(team_id=home.id, is_home=True,
                     goals_scored_avg=1.8, goals_conceded_avg=0.9,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    db.add(FormCache(team_id=away.id, is_home=False,
                     goals_scored_avg=1.2, goals_conceded_avg=1.5,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    SpreadPredictor(db, lead_hours=2).run(mv.id)

    preds = db.query(SpreadPrediction).filter_by(fixture_id=fixture.id).all()
    assert len(preds) == 6  # one per goal line
    lines = {p.goal_line for p in preds}
    assert lines == {-1.5, -1.0, -0.5, 0.5, 1.0, 1.5}


def test_spread_predictor_skips_fixture_without_form_cache(db):
    from datetime import datetime, timezone, timedelta
    from app.db.models import League, Team, Fixture, ModelVersion, SpreadPrediction
    from app.spread_predictor import SpreadPredictor

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="TeamA", league_id=league.id)
    away = Team(name="TeamB", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="no_form",
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="scheduled",
    )
    db.add(fixture)
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    SpreadPredictor(db, lead_hours=2).run(mv.id)
    preds = db.query(SpreadPrediction).filter_by(fixture_id=fixture.id).all()
    assert len(preds) == 0
