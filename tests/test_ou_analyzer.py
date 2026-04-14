import pytest
from app.dixon_coles import build_score_matrix, ou_probability_dc
from app.ou_analyzer import _confidence_tier


def test_ou_over_probability_25():
    """P(over 2.5) from DC matrix should be in a sane range for λ_total≈2.5."""
    matrix = build_score_matrix(1.3, 1.2, rho=-0.13)  # total ≈ 2.5
    over_p = ou_probability_dc(matrix, 2.5)
    assert 0.3 < over_p < 0.7


def test_ou_over_probability_15():
    """P(over 1.5) should always be higher than P(over 2.5)."""
    matrix = build_score_matrix(1.3, 1.2, rho=-0.13)
    over_15 = ou_probability_dc(matrix, 1.5)
    over_25 = ou_probability_dc(matrix, 2.5)
    assert over_15 > over_25


def test_ou_over_probability_complement():
    """over + under should sum to 1 for half-ball lines (no push)."""
    matrix = build_score_matrix(1.5, 1.2, rho=-0.13)
    over = ou_probability_dc(matrix, 2.5)
    assert abs(over + (1.0 - over) - 1.0) < 1e-10


def test_ou_over_probability_increases_with_higher_lambda():
    """Higher expected goals → higher P(over 2.5)."""
    low_matrix = build_score_matrix(0.5, 0.5, rho=-0.13)
    high_matrix = build_score_matrix(2.5, 2.0, rho=-0.13)
    p_low = ou_probability_dc(low_matrix, 2.5)
    p_high = ou_probability_dc(high_matrix, 2.5)
    assert p_high > p_low


def test_confidence_tier_boundaries():
    assert _confidence_tier(0.10) == "ELITE"
    assert _confidence_tier(0.05) == "HIGH"
    assert _confidence_tier(0.02) == "MEDIUM"
    assert _confidence_tier(0.019) == "SKIP"
    assert _confidence_tier(None) == "SKIP"


def test_ou_analyzer_generates_analysis(db):
    from datetime import datetime, timezone, timedelta
    from app.db.models import (
        League, Team, Fixture, FormCache, ModelVersion, OUAnalysis
    )
    from app.ou_analyzer import OUAnalyzer

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="ou_test",
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
    mv = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    OUAnalyzer(db, lead_hours=2).run(mv.id)

    analyses = db.query(OUAnalysis).filter_by(fixture_id=fixture.id).all()
    assert len(analyses) == 3  # 1.5, 2.5, 3.5 lines
    lines = {a.line for a in analyses}
    assert lines == {1.5, 2.5, 3.5}
    for a in analyses:
        assert a.direction in ("over", "under")
        assert 0.0 <= a.probability <= 1.0
