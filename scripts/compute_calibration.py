"""
Nightly job — compute rolling Brier + reliability curve per (model, bet_type)
and persist to calibration_runs.
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connection import get_engine
from app.db.models import (
    ModelVersion, SpreadPrediction, OUAnalysis, MoneylinePrediction,
    Fixture, Result, CalibrationRun,
)
from app.calibration import brier_score, reliability_curve


def _spread_pairs(session, model_id, since):
    rows = (
        session.query(SpreadPrediction, Fixture, Result)
        .join(Fixture, SpreadPrediction.fixture_id == Fixture.id)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(SpreadPrediction.model_id == model_id)
        .filter(SpreadPrediction.created_at >= since)
        .filter(Result.home_score.isnot(None))
        .all()
    )
    preds, outs = [], []
    for sp, _, res in rows:
        margin = res.home_score - res.away_score
        if sp.team_side == "home":
            covered = 1.0 if (margin + sp.goal_line) > 0 else 0.0
        else:
            covered = 1.0 if (-margin + sp.goal_line) > 0 else 0.0
        preds.append(sp.final_probability or sp.cover_probability)
        outs.append(covered)
    return preds, outs


def _ou_pairs(session, model_id, since):
    rows = (
        session.query(OUAnalysis, Fixture, Result)
        .join(Fixture, OUAnalysis.fixture_id == Fixture.id)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(OUAnalysis.model_id == model_id)
        .filter(OUAnalysis.created_at >= since)
        .filter(Result.total_goals.isnot(None))
        .all()
    )
    preds, outs = [], []
    for ou, _, res in rows:
        if ou.direction == "over":
            hit = 1.0 if res.total_goals > ou.line else 0.0
        else:
            hit = 1.0 if res.total_goals < ou.line else 0.0
        preds.append(ou.final_probability or ou.probability)
        outs.append(hit)
    return preds, outs


def _h2h_pairs(session, model_id, since):
    rows = (
        session.query(MoneylinePrediction, Fixture, Result)
        .join(Fixture, MoneylinePrediction.fixture_id == Fixture.id)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(MoneylinePrediction.model_id == model_id)
        .filter(MoneylinePrediction.created_at >= since)
        .filter(Result.outcome.isnot(None))
        .all()
    )
    preds, outs = [], []
    for ml, _, res in rows:
        preds.append(ml.final_probability or ml.probability)
        outs.append(1.0 if ml.outcome == res.outcome else 0.0)
    return preds, outs


def run(session: Session, window_days: int = 30):
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    for model in session.query(ModelVersion).filter_by(active=True).all():
        for bet_type, loader in (("spread", _spread_pairs), ("ou", _ou_pairs), ("h2h", _h2h_pairs)):
            preds, outs = loader(session, model.id, since)
            if not preds:
                continue
            b = brier_score(preds, outs)
            curve = reliability_curve(preds, outs, n_bins=10)
            session.add(CalibrationRun(
                model_id=model.id,
                bet_type=bet_type,
                window_days=window_days,
                brier_score=b,
                n_samples=len(preds),
                reliability_json=json.dumps(curve),
                computed_at=datetime.now(timezone.utc),
            ))
            print(f"model={model.name} type={bet_type} brier={b:.4f} n={len(preds)}")
    session.commit()


if __name__ == "__main__":
    with Session(get_engine()) as s:
        run(s)
