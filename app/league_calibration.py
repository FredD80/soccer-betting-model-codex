"""
Per-league calibration parameters for the Dixon-Coles model.

Priority: DB row (league_calibration table) → LEAGUE_DEFAULTS → GENERIC_DEFAULT.
This allows fitted parameters from backtesting to override hard-coded defaults
without requiring a code change.
"""
from dataclasses import dataclass


@dataclass
class LeagueParams:
    rho: float = -0.13           # DC low-score correlation; typically -0.10 to -0.16
    home_advantage: float = 1.10  # multiplier on lambda_home
    attack_scale: float = 1.0    # league-level goal-rate scalar
    defense_scale: float = 1.0


# Hard-coded defaults per ESPN league ID (fitted from historical averages).
LEAGUE_DEFAULTS: dict[str, LeagueParams] = {
    "eng.1":         LeagueParams(rho=-0.13, home_advantage=1.10),  # Premier League
    "esp.1":         LeagueParams(rho=-0.12, home_advantage=1.12),  # La Liga
    "ger.1":         LeagueParams(rho=-0.10, home_advantage=1.08),  # Bundesliga (higher scoring)
    "ita.1":         LeagueParams(rho=-0.14, home_advantage=1.09),  # Serie A
    "fra.1":         LeagueParams(rho=-0.13, home_advantage=1.11),  # Ligue 1
    "uefa.champions": LeagueParams(rho=-0.16, home_advantage=1.06),  # UCL (weaker HFA)
}

GENERIC_DEFAULT = LeagueParams()


def get_league_params(session, league_espn_id: str) -> LeagueParams:
    """
    Return calibration params for a league with three-tier fallback.

    1. DB row in league_calibration (per-league fitted values from backtester)
    2. LEAGUE_DEFAULTS hard-coded above
    3. GENERIC_DEFAULT (all defaults)
    """
    try:
        from app.db.models import LeagueCalibration
        row = (
            session.query(LeagueCalibration)
            .filter_by(league_espn_id=league_espn_id)
            .first()
        )
        if row is not None:
            return LeagueParams(
                rho=row.rho,
                home_advantage=row.home_advantage,
                attack_scale=row.attack_scale,
                defense_scale=row.defense_scale,
            )
    except Exception:
        pass

    return LEAGUE_DEFAULTS.get(league_espn_id, GENERIC_DEFAULT)
