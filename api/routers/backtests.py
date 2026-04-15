from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import BacktestRunRequest, BacktestRunResponse
from app.db.models import BacktestRun, ModelVersion
from app.pick_backtester import PickBacktester

router = APIRouter()


def _to_response(run: BacktestRun, mv: ModelVersion | None) -> BacktestRunResponse:
    return BacktestRunResponse(
        market=run.bet_type,
        model_id=run.model_id,
        model_name=mv.name if mv else "unknown",
        model_version=mv.version if mv else "unknown",
        total=run.total or 0,
        correct=run.correct or 0,
        accuracy=run.accuracy or 0.0,
        roi=run.roi or 0.0,
        date_from=run.date_from,
        date_to=run.date_to,
        run_at=run.run_at,
    )


@router.get("/runs", response_model=list[BacktestRunResponse])
def list_runs(session: Session = Depends(get_session), limit: int = 20):
    rows = (
        session.query(BacktestRun)
        .order_by(BacktestRun.run_at.desc())
        .limit(limit)
        .all()
    )
    versions = {
        mv.id: mv
        for mv in session.query(ModelVersion)
        .filter(ModelVersion.id.in_([row.model_id for row in rows]))
        .all()
    }
    return [_to_response(row, versions.get(row.model_id)) for row in rows]


@router.post("/picks/run", response_model=list[BacktestRunResponse])
def run_pick_backtest(payload: BacktestRunRequest, session: Session = Depends(get_session)):
    date_from = datetime.combine(payload.from_date, time.min, tzinfo=timezone.utc)
    date_to = datetime.combine(payload.to_date, time.max, tzinfo=timezone.utc)
    summaries = PickBacktester(session).run(date_from, date_to, markets=tuple(payload.markets))

    responses: list[BacktestRunResponse] = []
    for summary in summaries:
        mv = session.query(ModelVersion).filter_by(id=summary.model_id).first()
        responses.append(
            BacktestRunResponse(
                market=summary.market,
                model_id=summary.model_id,
                model_name=mv.name if mv else "unknown",
                model_version=mv.version if mv else "unknown",
                total=summary.total,
                correct=summary.correct,
                accuracy=summary.accuracy,
                roi=summary.roi,
                date_from=date_from,
                date_to=date_to,
                run_at=datetime.now(timezone.utc),
            )
        )
    return responses
