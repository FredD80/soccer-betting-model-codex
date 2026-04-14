import numpy as np
import pytest

from app.calibration import brier_score, reliability_curve


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
