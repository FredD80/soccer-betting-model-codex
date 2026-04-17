from datetime import datetime, timezone
import json

import numpy as np
import pytest

from app.calibration import (
    brier_score,
    reliability_curve,
    calibrate_probability,
    renormalize_probabilities,
)
from app.db.models import CalibrationRun, ModelVersion


def test_brier_empty():
    assert brier_score([], []) == 0.0


def test_brier_perfect():
    assert brier_score([1, 0, 1], [1, 0, 1]) == 0.0


def test_brier_coin_flip():
    # always predict 0.5 on balanced outcomes → 0.25
    assert brier_score([0.5] * 4, [1, 0, 1, 0]) == pytest.approx(0.25)


def test_reliability_empty():
    assert reliability_curve([], []) == []


def test_reliability_bins():
    np.random.seed(0)
    preds = np.linspace(0.05, 0.95, 100)
    outcomes = (np.random.random(100) < preds).astype(float)
    curve = reliability_curve(preds, outcomes, n_bins=10)
    assert len(curve) <= 10
    # mean_pred strictly rises across bins
    means = [b["mean_pred"] for b in curve]
    assert means == sorted(means)


def test_reliability_bin_bounds():
    curve = reliability_curve([0.05, 0.55, 0.95], [0, 1, 1], n_bins=10)
    assert all(0.0 <= b["bin_low"] < b["bin_high"] <= 1.0 for b in curve)
    assert all(b["n"] >= 1 for b in curve)


def test_renormalize_probabilities():
    probs = renormalize_probabilities({"home": 0.55, "draw": 0.30, "away": 0.25})
    assert sum(probs.values()) == pytest.approx(1.0)
    assert probs["home"] > probs["draw"] > probs["away"]


def test_calibrate_probability_uses_reliability_curve(db):
    mv = ModelVersion(name="moneyline_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    db.add(CalibrationRun(
        model_id=mv.id,
        bet_type="h2h",
        window_days=30,
        brier_score=0.20,
        n_samples=1000,
        reliability_json=json.dumps([
            {"bin_low": 0.0, "bin_high": 0.5, "mean_pred": 0.40, "hit_rate": 0.30, "n": 250},
            {"bin_low": 0.5, "bin_high": 1.0, "mean_pred": 0.80, "hit_rate": 0.62, "n": 250},
        ]),
        computed_at=datetime.now(timezone.utc),
    ))
    db.flush()

    calibrated = calibrate_probability(db, mv.id, "h2h", 0.80)
    assert calibrated == pytest.approx(0.62)


def test_calibrate_probability_returns_raw_when_missing_curve(db):
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    assert calibrate_probability(db, mv.id, "spread", 0.64) == pytest.approx(0.64)
