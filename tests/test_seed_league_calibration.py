"""Tests for the league_calibration seed script."""
import pytest
from app.db.models import LeagueCalibration
from app.league_calibration import LEAGUE_DEFAULTS
from scripts.seed_league_calibration import seed


def test_seed_inserts_all_defaults(db):
    inserted = seed(db)
    assert inserted == len(LEAGUE_DEFAULTS)

    rows = db.query(LeagueCalibration).all()
    assert len(rows) == len(LEAGUE_DEFAULTS)
    assert {r.league_espn_id for r in rows} == set(LEAGUE_DEFAULTS.keys())


def test_seed_is_idempotent(db):
    assert seed(db) == len(LEAGUE_DEFAULTS)
    assert seed(db) == 0  # second run inserts nothing


def test_seed_preserves_values(db):
    seed(db)
    row = db.query(LeagueCalibration).filter_by(league_espn_id="eng.1").one()
    expected = LEAGUE_DEFAULTS["eng.1"]
    assert row.rho == pytest.approx(expected.rho)
    assert row.home_advantage == pytest.approx(expected.home_advantage)
    assert row.attack_scale == pytest.approx(expected.attack_scale)
    assert row.defense_scale == pytest.approx(expected.defense_scale)
    assert row.fitted_at is None
