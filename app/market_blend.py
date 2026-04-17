"""
Market blending — combine model probability with Pinnacle implied probability
using per-(league, bet_type) weights fit offline by scripts/fit_market_weights.py.

Falls back to conservative market-aware priors when no fitted weights row
exists yet. Moneyline gets the strongest market weight because it is the most
efficient market and the path most likely to show overconfident raw model
percentages.
"""
from app.db.models import MarketWeights


DEFAULT_WEIGHTS = {
    "h2h": (0.35, 0.65),
    "spread": (1.0, 0.0),
    "ou": (1.0, 0.0),
}


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
        return DEFAULT_WEIGHTS.get(bet_type, (1.0, 0.0))
    return row.w_model, row.w_market
