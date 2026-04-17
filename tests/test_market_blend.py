import pytest
from datetime import datetime, timezone

from app.db.models import MarketWeights
from app.market_blend import blend, get_weights


def test_blend_convex_combination():
    assert blend(0.6, 0.4, 0.5, 0.5) == pytest.approx(0.5)


def test_blend_returns_model_when_implied_none():
    assert blend(0.6, None, 0.5, 0.5) == 0.6


def test_blend_rejects_weights_not_summing_to_one():
    with pytest.raises(ValueError):
        blend(0.5, 0.5, 0.4, 0.4)


def test_blend_pure_model():
    assert blend(0.7, 0.3, 1.0, 0.0) == 0.7


def test_blend_pure_market():
    assert blend(0.7, 0.3, 0.0, 1.0) == 0.3


def test_get_weights_default_when_missing(db):
    assert get_weights(db, "eng.1", "spread") == (1.0, 0.0)
    assert get_weights(db, "eng.1", "h2h") == (0.35, 0.65)


def test_get_weights_reads_db_row(db):
    db.add(MarketWeights(
        league_espn_id="eng.1", bet_type="spread",
        w_model=0.7, w_market=0.3, n_samples=300,
        fitted_at=datetime.now(timezone.utc),
    ))
    db.flush()
    assert get_weights(db, "eng.1", "spread") == (0.7, 0.3)
    # unrelated league still falls back
    assert get_weights(db, "esp.1", "spread") == (1.0, 0.0)
