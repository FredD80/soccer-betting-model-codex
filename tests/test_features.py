from datetime import datetime, timezone
import numpy as np
import pytest

from app.db.models import League, Team, Fixture, FormCache
from app.features import FEATURE_NAMES, N_FEATURES, build_feature_vector


@pytest.fixture
def fx(db):
    lg = League(name="EPL", country="ENG", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(lg); db.flush()
    h = Team(name="H", league_id=lg.id); a = Team(name="A", league_id=lg.id)
    db.add_all([h, a]); db.flush()
    f = Fixture(
        home_team_id=h.id, away_team_id=a.id, league_id=lg.id,
        kickoff_at=datetime.now(timezone.utc), status="scheduled",
    )
    db.add(f); db.flush()
    return f


def test_feature_names_unique_and_counted():
    assert len(FEATURE_NAMES) == N_FEATURES
    assert len(set(FEATURE_NAMES)) == N_FEATURES


def test_vector_all_nan_when_no_data(db, fx):
    vec = build_feature_vector(db, fx)
    assert vec.shape == (N_FEATURES,)
    # is_top_league is 1 here (eng.1) — last feature
    assert vec[-1] == 1.0
    # Everything else should be nan
    assert np.isnan(vec[:-1]).all()


def test_vector_populates_form(db, fx):
    db.add_all([
        FormCache(team_id=fx.home_team_id, is_home=True,
                  goals_scored_avg=1.8, goals_conceded_avg=1.0,
                  spread_cover_rate=0.6, ou_hit_rate_25=0.5,
                  xg_scored_avg=1.7, xg_conceded_avg=1.1, matches_count=5),
        FormCache(team_id=fx.away_team_id, is_home=False,
                  goals_scored_avg=1.2, goals_conceded_avg=1.4,
                  spread_cover_rate=0.4, ou_hit_rate_25=0.45,
                  xg_scored_avg=1.1, xg_conceded_avg=1.5, matches_count=5),
    ])
    db.flush()
    vec = build_feature_vector(db, fx)
    assert vec[0] == 1.8  # home_goals_scored_avg
    assert vec[2] == 1.2  # away_goals_scored_avg
    # goals_scored_diff
    assert vec[FEATURE_NAMES.index("goals_scored_diff")] == pytest.approx(0.6)
