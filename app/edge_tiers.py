"""
Edge-vs-market tier bucketing + fractional-Kelly sizing.

Buckets on edge = final_p - implied_p, not raw EV. Kelly fraction is
computed analytically and scaled per tier.
"""

TIER_KELLY_MULT = {"SKIP": 0.0, "MEDIUM": 0.10, "HIGH": 0.15, "ELITE": 0.25}


def edge_tier(edge_pct: float | None) -> str:
    if edge_pct is None or edge_pct < 0.02:
        return "SKIP"
    if edge_pct < 0.05:
        return "MEDIUM"
    if edge_pct < 0.10:
        return "HIGH"
    return "ELITE"


def kelly_fraction(tier: str, final_p: float, decimal_odds: float | None) -> float:
    """Fractional Kelly. Clamps to 0 when full_kelly is negative or tier is SKIP."""
    if tier == "SKIP" or decimal_odds is None or decimal_odds <= 1.0:
        return 0.0
    b = decimal_odds - 1.0
    full = (b * final_p - (1.0 - final_p)) / b
    return max(0.0, full * TIER_KELLY_MULT[tier])
