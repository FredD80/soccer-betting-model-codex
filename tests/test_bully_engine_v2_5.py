from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "Bully-Models"

if str(MODELS_DIR) not in sys.path:
    sys.path.insert(0, str(MODELS_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bully_engine_v2_5 as v25
from scripts import bully_backtest_all_models


def test_compute_target_hit_rate_and_cutoff():
    target = v25.compute_target_hit_rate(0.10, 1.55)
    assert target == pytest.approx((1.0 / 1.55) + 0.10)

    history = v25.LeagueEloHistory(
        league_name="Test League",
        elo_gaps=(200.0, 180.0, 160.0, 140.0, 120.0, 100.0),
        hits=(True, True, True, False, False, False),
        window_start="2025-08-01",
        window_end="2026-04-20",
    )

    cutoff = v25.compute_elo_gap_cutoff_for_target_hit_rate(
        history,
        target_hit_rate=0.75,
        min_candidates_above_cutoff=3,
    )

    assert cutoff == pytest.approx(140.0)


def test_engine_falls_back_to_absolute_cutoff_when_history_is_thin():
    history = v25.LeagueEloHistory(
        league_name="Thin League",
        elo_gaps=(150.0,),
        hits=(True,),
        window_start="2025-08-01",
        window_end="2025-08-10",
    )
    engine = v25.BullyV2_5Engine(
        insufficient_history_policy="fallback_absolute",
        min_elo_gap_absolute=130.0,
        min_history_fixtures=5,
        min_favorite_lambda=0.0,
        max_opponent_lambda=10.0,
        min_joint_probability=0.0,
    )

    pred = engine.predict(
        home_elo=1600.0,
        away_elo=1450.0,
        home_form=v25.FormSnapshot(2.2, 0.9, 8, "understat"),
        away_form=v25.FormSnapshot(1.0, 1.8, 8, "understat"),
        league_fit=v25.LeagueFit(1.55, 1.20, v25.DEFAULT_RHO, 0.0, 200),
        league_history=history,
    )

    assert pred.is_bully_spot is True
    assert pred.elo_gap_threshold_used == pytest.approx(130.0)
    assert pred.elo_gap_threshold_source == "insufficient_history_fallback_absolute"
    assert pred.league_history_n_fixtures == 1


def test_all_models_runner_registers_v25():
    model_names = [meta.name for meta in bully_backtest_all_models._model_meta(None)]
    assert "V2.5" in model_names

    engines = bully_backtest_all_models._build_engines(None)
    assert "V2.5" in engines
    assert engines["V2.5"].__class__.__name__ == "BullyV2_5Engine"
    assert engines["V2.5"].__class__.__module__ == "bully_v25"
