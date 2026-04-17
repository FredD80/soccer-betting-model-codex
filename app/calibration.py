"""
Brier score, reliability-curve helpers, and lightweight post-hoc calibration.

Calibration uses the latest stored reliability curve for a given
``(model_id, bet_type)`` and interpolates from ``mean_pred`` to ``hit_rate``.
That gives us a cheap probability-mapping layer without introducing a new
artifact format.
"""
import json

import numpy as np

from app.db.models import CalibrationRun


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


def clip_probability(prob: float, eps: float = 1e-6) -> float:
    return float(min(max(prob, eps), 1.0 - eps))


def renormalize_probabilities(probabilities: dict[str, float]) -> dict[str, float]:
    clipped = {key: max(0.0, float(value)) for key, value in probabilities.items()}
    total = sum(clipped.values())
    if total <= 0:
        uniform = 1.0 / len(clipped) if clipped else 0.0
        return {key: uniform for key in clipped}
    return {key: value / total for key, value in clipped.items()}


def _interpolate_reliability(prob: float, curve: list[dict]) -> float:
    points = sorted(
        (
            float(bucket["mean_pred"]),
            float(bucket["hit_rate"]),
        )
        for bucket in curve
        if bucket.get("n", 0) > 0
        and bucket.get("mean_pred") is not None
        and bucket.get("hit_rate") is not None
    )
    if not points:
        return prob
    if len(points) == 1:
        return clip_probability(points[0][1])

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    if prob <= xs[0]:
        return clip_probability(ys[0])
    if prob >= xs[-1]:
        return clip_probability(ys[-1])

    for idx in range(1, len(xs)):
        if prob <= xs[idx]:
            x0, y0 = xs[idx - 1], ys[idx - 1]
            x1, y1 = xs[idx], ys[idx]
            span = x1 - x0
            if span <= 0:
                return clip_probability(y1)
            t = (prob - x0) / span
            return clip_probability(y0 + t * (y1 - y0))
    return clip_probability(prob)


def calibrate_probability(
    session,
    model_id: int,
    bet_type: str,
    prob: float,
    min_samples: int = 100,
    full_strength_samples: int = 500,
) -> float:
    """
    Map a probability through the most recent reliability curve for the model.

    We shrink the calibrated mapping back toward the original probability when
    sample size is small so a thin curve does not overfit the live output.
    """
    raw = clip_probability(prob)
    row = (
        session.query(CalibrationRun)
        .filter_by(model_id=model_id, bet_type=bet_type)
        .filter(CalibrationRun.n_samples.isnot(None))
        .order_by(CalibrationRun.computed_at.desc())
        .first()
    )
    if row is None or (row.n_samples or 0) < min_samples or not row.reliability_json:
        return raw

    try:
        curve = json.loads(row.reliability_json)
    except json.JSONDecodeError:
        return raw

    mapped = _interpolate_reliability(raw, curve)
    strength = min(1.0, max(0.0, (row.n_samples or 0) / float(full_strength_samples)))
    return clip_probability(((1.0 - strength) * raw) + (strength * mapped))
