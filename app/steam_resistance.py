"""
Steam Resistance — if Pinnacle's line has already moved >=2% in the direction
of the model's pick since it opened, downgrade the confidence tier one step.

Movement is measured in American odds terms on the pick side:
    move_pct = (current_odds - opening_odds) / abs(opening_odds)
A shortening price on the pick side (odds moved toward favourite) is
positive movement in the pick's direction.
"""
from app.db.models import LineMovement

DOWNGRADE_LADDER = {
    "ELITE": "HIGH",
    "HIGH": "MEDIUM",
    "MEDIUM": "SKIP",
    "SKIP": "SKIP",
}
THRESHOLD = 0.02


def steam_move_pct(
    session,
    fixture_id: int,
    market: str,          # "spread" | "ou"
    pick_side: str,       # "home"|"away" for spread; "over"|"under" for ou
    pick_line: float,
) -> float:
    """
    Return signed move pct in the pick's direction.
    0.0 if we have fewer than 2 rows for this market/line.
    """
    rows = (
        session.query(LineMovement)
        .filter_by(fixture_id=fixture_id, book="pinnacle", market=market, line=pick_line)
        .order_by(LineMovement.recorded_at.asc())
        .all()
    )
    if len(rows) < 2:
        return 0.0
    opening, current = rows[0], rows[-1]
    if opening.odds is None or current.odds is None or opening.odds == 0:
        return 0.0
    # Positive = odds shortened on the pick side (price moved toward favourite).
    # For American odds, a shift from -110 → -120 is "the pick side got more expensive."
    # We express this as a positive fraction relative to |opening|.
    return (current.odds - opening.odds) / abs(opening.odds)


def apply_steam(tier: str, move_pct: float) -> tuple[str, bool]:
    """
    Given a tier and the signed move in pick's direction, maybe downgrade.
    Returns (new_tier, downgraded_flag).
    """
    if move_pct >= THRESHOLD:
        return DOWNGRADE_LADDER[tier], True
    return tier, False
