"""
Brier score + reliability-curve helpers.

Phase 3 records a baseline; Phase 5 will alert on drift.
"""
import numpy as np


def brier_score(preds, outcomes) -> float:
    preds = np.asarray(preds, dtype=np.float64)
    outcomes = np.asarray(outcomes, dtype=np.float64)
    if preds.size == 0:
        return 0.0
    return float(np.mean((preds - outcomes) ** 2))


def reliability_curve(preds, outcomes, n_bins: int = 10) -> list[dict]:
    """
    Bin predictions into n_bins equal-width buckets on [0, 1].
    Return one dict per non-empty bucket with:
        bin_low, bin_high, mean_pred, hit_rate, n
    Empty bins are omitted.
    """
    preds = np.asarray(preds, dtype=np.float64)
    outcomes = np.asarray(outcomes, dtype=np.float64)
    if preds.size == 0:
        return []
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (preds >= lo) & (preds < hi) if i < n_bins - 1 else (preds >= lo) & (preds <= hi)
        if not mask.any():
            continue
        out.append({
            "bin_low": float(lo),
            "bin_high": float(hi),
            "mean_pred": float(preds[mask].mean()),
            "hit_rate": float(outcomes[mask].mean()),
            "n": int(mask.sum()),
        })
    return out
