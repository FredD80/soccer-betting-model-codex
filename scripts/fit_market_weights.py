"""
Grid-search (w_model, w_market) minimising Brier on historical settled picks
for each (league, bet_type). Writes results to the market_weights table.

Usage:
    DATABASE_URL=postgresql://... python scripts/fit_market_weights.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connection import get_engine
from app.db.models import (
    Fixture, League, Result, SpreadPrediction, OUAnalysis, MoneylinePrediction,
    OddsSnapshot, MarketWeights,
)


class InsufficientDataError(RuntimeError):
    pass


def _spread_triples(session, league_id):
    """Return list of (model_p, implied_p, outcome) for settled spread picks."""
    rows = (
        session.query(SpreadPrediction, Fixture, Result)
        .join(Fixture, SpreadPrediction.fixture_id == Fixture.id)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(Fixture.league_id == league_id)
        .filter(Result.home_score.isnot(None))
        .all()
    )
    triples = []
    for sp, fx, res in rows:
        snap = (
            session.query(OddsSnapshot)
            .filter_by(fixture_id=fx.id)
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )
        if snap is None:
            continue
        odds = snap.spread_home_odds if sp.goal_line < 0 else snap.spread_away_odds
        if not odds or odds <= 1.0:
            continue
        implied = 1.0 / odds
        # Outcome: did the pick side cover?
        margin = res.home_score - res.away_score
        if sp.team_side == "home":
            covered = 1.0 if (margin + sp.goal_line) > 0 else 0.0
        else:
            covered = 1.0 if (-margin + sp.goal_line) > 0 else 0.0
        triples.append((sp.cover_probability, implied, covered))
    return triples


def _ou_triples(session, league_id):
    rows = (
        session.query(OUAnalysis, Fixture, Result)
        .join(Fixture, OUAnalysis.fixture_id == Fixture.id)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(Fixture.league_id == league_id)
        .filter(Result.total_goals.isnot(None))
        .all()
    )
    triples = []
    for ou, fx, res in rows:
        snap = (
            session.query(OddsSnapshot)
            .filter_by(fixture_id=fx.id)
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )
        if snap is None:
            continue
        odds = snap.over_odds if ou.direction == "over" else snap.under_odds
        if not odds or odds <= 1.0:
            continue
        implied = 1.0 / odds
        if ou.direction == "over":
            hit = 1.0 if res.total_goals > ou.line else 0.0
        else:
            hit = 1.0 if res.total_goals < ou.line else 0.0
        triples.append((ou.probability, implied, hit))
    return triples


def _h2h_triples(session, league_id):
    rows = (
        session.query(MoneylinePrediction, Fixture, Result)
        .join(Fixture, MoneylinePrediction.fixture_id == Fixture.id)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(Fixture.league_id == league_id)
        .filter(Result.outcome.isnot(None))
        .all()
    )
    triples = []
    for ml, fx, res in rows:
        snap = (
            session.query(OddsSnapshot)
            .filter_by(fixture_id=fx.id)
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )
        if snap is None:
            continue
        raw = {
            "home": 1.0 / snap.home_odds if snap.home_odds and snap.home_odds > 1.0 else None,
            "draw": 1.0 / snap.draw_odds if snap.draw_odds and snap.draw_odds > 1.0 else None,
            "away": 1.0 / snap.away_odds if snap.away_odds and snap.away_odds > 1.0 else None,
        }
        if any(value is None for value in raw.values()):
            continue
        total = sum(value for value in raw.values() if value is not None)
        if total <= 0:
            continue
        implied = raw[ml.outcome] / total
        hit = 1.0 if ml.outcome == res.outcome else 0.0
        triples.append((ml.probability, implied, hit))
    return triples


def _grid_search(triples) -> tuple[float, float, float]:
    models = np.array([t[0] for t in triples])
    implieds = np.array([t[1] for t in triples])
    outs = np.array([t[2] for t in triples])
    best = None
    for w1 in np.arange(0.0, 1.001, 0.05):
        w2 = 1.0 - w1
        preds = w1 * models + w2 * implieds
        brier = float(np.mean((preds - outs) ** 2))
        if best is None or brier < best[2]:
            best = (float(w1), float(w2), brier)
    return best


def _upsert(session, league_espn_id, bet_type, w1, w2, n):
    row = (
        session.query(MarketWeights)
        .filter_by(league_espn_id=league_espn_id, bet_type=bet_type)
        .first()
    )
    if row is None:
        session.add(MarketWeights(
            league_espn_id=league_espn_id, bet_type=bet_type,
            w_model=w1, w_market=w2, n_samples=n,
            fitted_at=datetime.now(timezone.utc),
        ))
    else:
        row.w_model = w1
        row.w_market = w2
        row.n_samples = n
        row.fitted_at = datetime.now(timezone.utc)


def fit(session: Session, league_espn_id: str, bet_type: str, min_samples: int = 200):
    league = session.query(League).filter_by(espn_id=league_espn_id).first()
    if league is None:
        raise InsufficientDataError(f"league {league_espn_id} not found")
    if bet_type == "spread":
        triples = _spread_triples(session, league.id)
    elif bet_type == "ou":
        triples = _ou_triples(session, league.id)
    elif bet_type == "h2h":
        triples = _h2h_triples(session, league.id)
    else:
        raise ValueError(f"unknown bet_type {bet_type}")

    if len(triples) < min_samples:
        raise InsufficientDataError(
            f"{len(triples)} samples < {min_samples} for {league_espn_id}/{bet_type}"
        )
    w1, w2, brier = _grid_search(triples)
    _upsert(session, league_espn_id, bet_type, w1, w2, len(triples))
    session.commit()
    print(f"{league_espn_id}/{bet_type}: w_model={w1:.2f} w_market={w2:.2f} "
          f"brier={brier:.4f} n={len(triples)}")
    return w1, w2, brier


def fit_all(session: Session, min_samples: int = 200):
    leagues = session.query(League).all()
    for lg in leagues:
        for bt in ("spread", "ou", "h2h"):
            try:
                fit(session, lg.espn_id, bt, min_samples=min_samples)
            except InsufficientDataError as e:
                print(f"skip {lg.espn_id}/{bt}: {e}")


if __name__ == "__main__":
    with Session(get_engine()) as s:
        fit_all(s)
