"""
One-time script to seed league_calibration with the Dixon-Coles defaults.

Inserts rows for each league in app.league_calibration.LEAGUE_DEFAULTS so the
backtester (future) can UPDATE these values rather than having them live only
in Python source. Idempotent: skips leagues that already have a row.

Usage:
    DATABASE_URL=postgresql://... python scripts/seed_league_calibration.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.db.connection import get_engine
from app.db.models import LeagueCalibration
from app.league_calibration import LEAGUE_DEFAULTS


def seed(session: Session | None = None) -> int:
    """Insert LEAGUE_DEFAULTS into league_calibration. Idempotent."""
    owns_session = session is None
    if owns_session:
        session = Session(get_engine())

    inserted = 0
    try:
        for league_espn_id, params in LEAGUE_DEFAULTS.items():
            existing = (
                session.query(LeagueCalibration)
                .filter_by(league_espn_id=league_espn_id)
                .first()
            )
            if existing:
                continue
            session.add(LeagueCalibration(
                league_espn_id=league_espn_id,
                rho=params.rho,
                home_advantage=params.home_advantage,
                attack_scale=params.attack_scale,
                defense_scale=params.defense_scale,
                fitted_at=None,  # None = manually seeded (not backtester-fitted)
            ))
            inserted += 1
        session.commit()
    finally:
        if owns_session:
            session.close()

    print(f"Seeded {inserted} league_calibration rows ({len(LEAGUE_DEFAULTS) - inserted} already existed)")
    return inserted


if __name__ == "__main__":
    seed()
