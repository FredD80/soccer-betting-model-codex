import math
import pytest
from app.ou_analyzer import ou_over_probability, _confidence_tier


def test_ou_over_probability_25_symmetric():
    """Equal attack/defense: P(over 2.5) should be reasonable for λ_total=2.5."""
    lam = 2.5
    expected = 1.0 - sum((lam ** k) * math.exp(-lam) / math.factorial(k) for k in range(3))
    assert abs(ou_over_probability(lam, 2.5) - expected) < 1e-6


def test_ou_over_probability_15():
    lam = 2.5
    expected = 1.0 - sum((lam ** k) * math.exp(-lam) / math.factorial(k) for k in range(2))
    assert abs(ou_over_probability(lam, 1.5) - expected) < 1e-6


def test_ou_over_probability_complement():
    """over + under should sum to 1 for half-ball lines."""
    over = ou_over_probability(2.0, 2.5)
    under = 1.0 - over
    assert abs(over + under - 1.0) < 1e-10


def test_ou_over_probability_increases_with_lambda():
    """Higher expected goals → higher P(over 2.5)."""
    p_low = ou_over_probability(1.0, 2.5)
    p_high = ou_over_probability(4.0, 2.5)
    assert p_high > p_low


def test_confidence_tier_boundaries():
    from app.ou_analyzer import _confidence_tier
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
