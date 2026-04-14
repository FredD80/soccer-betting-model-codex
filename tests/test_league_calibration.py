"""Tests for league calibration parameter lookup."""
import pytest
from app.league_calibration import (
    get_league_params,
    LEAGUE_DEFAULTS,
    GENERIC_DEFAULT,
    LeagueParams,
)


class TestLeagueDefaults:
    def test_known_leagues_have_defaults(self):
        known = ["eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "uefa.champions"]
        for league_id in known:
            assert league_id in LEAGUE_DEFAULTS

    def test_rho_is_negative(self):
        for params in LEAGUE_DEFAULTS.values():
            assert params.rho < 0.0, f"rho should be negative for realistic soccer"

    def test_home_advantage_above_one(self):
        for params in LEAGUE_DEFAULTS.values():
            assert params.home_advantage > 1.0

    def test_bundesliga_highest_scoring(self):
        # Bundesliga has the smallest |rho| (less correlation, more goals)
        bun = LEAGUE_DEFAULTS["ger.1"]
        epl = LEAGUE_DEFAULTS["eng.1"]
        assert abs(bun.rho) < abs(epl.rho)


class TestGetLeagueParams:
    def test_falls_back_to_defaults_for_known_league(self, db):
        params = get_league_params(db, "eng.1")
        assert params.rho == LEAGUE_DEFAULTS["eng.1"].rho
        assert params.home_advantage == LEAGUE_DEFAULTS["eng.1"].home_advantage

    def test_falls_back_to_generic_for_unknown_league(self, db):
        params = get_league_params(db, "mls.1")
        assert params.rho == GENERIC_DEFAULT.rho
        assert params.home_advantage == GENERIC_DEFAULT.home_advantage

    def test_db_row_takes_priority(self, db):
        from app.db.models import LeagueCalibration
        row = LeagueCalibration(
            league_espn_id="eng.1",
            rho=-0.20,
            home_advantage=1.15,
            attack_scale=1.0,
            defense_scale=1.0,
        )
        db.add(row)
        db.flush()

        params = get_league_params(db, "eng.1")
        assert params.rho == pytest.approx(-0.20)
        assert params.home_advantage == pytest.approx(1.15)

    def test_returns_league_params_dataclass(self, db):
        params = get_league_params(db, "ita.1")
        assert isinstance(params, LeagueParams)
