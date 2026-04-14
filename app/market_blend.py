"""
Market blending — combine model probability with Pinnacle implied probability
using per-(league, bet_type) weights fit offline by scripts/fit_market_weights.py.

Falls back to (w_model=1.0, w_market=0.0) (pure model) when no weights row
exists, so new leagues don't get silently zero'd out.
"""
from app.db.models import MarketWeights


def blend(model_p: float, implied_p: float | None, w1: float, w2: float) -> float:
    """Convex combination w1*model + w2*market. If implied is None, return model_p."""
    if implied_p is None:
        return model_p
    if abs(w1 + w2 - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1: {w1} + {w2} = {w1 + w2}")
    return w1 * model_p + w2 * implied_p


def get_weights(session, league_espn_id: str, bet_type: str) -> tuple[float, float]:
    row = (
        session.query(MarketWeights)
        .filter_by(league_espn_id=league_espn_id, bet_type=bet_type)
        .first()
    )
    if row is None:
        return 1.0, 0.0
    return row.w_model, row.w_market
