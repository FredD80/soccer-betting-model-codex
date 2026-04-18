from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import BacktestJobResponse, BacktestRunRequest, BacktestRunResponse
from app.celery_app import backtest_run_task
from app.db.models import BacktestJob, BacktestRun, ModelVersion

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
        win_two_plus_hit_rate=(
            (run.accuracy or 0.0) * run.two_plus_given_win_rate
            if run.two_plus_given_win_rate is not None
            else None
        ),
        two_plus_hit_rate=run.two_plus_hit_rate,
        clean_sheet_hit_rate=run.clean_sheet_hit_rate,
        two_plus_given_win_rate=run.two_plus_given_win_rate,
        clean_sheet_given_win_rate=run.clean_sheet_given_win_rate,
        date_from=run.date_from,
        date_to=run.date_to,
        run_at=run.run_at,
    )


def _job_runs(session: Session, job_id: int) -> list[BacktestRun]:
    return (
        session.query(BacktestRun)
        .filter(BacktestRun.backtest_job_id == job_id)
        .order_by(BacktestRun.run_at.desc(), BacktestRun.id.desc())
        .all()
    )


def _job_to_response(session: Session, job: BacktestJob) -> BacktestJobResponse:
    runs = _job_runs(session, job.id)
    versions = {
        mv.id: mv
        for mv in session.query(ModelVersion)
        .filter(ModelVersion.id.in_([row.model_id for row in runs]))
        .all()
    }
    return BacktestJobResponse(
        id=job.id,
        task_id=job.task_id,
        status=job.status,
        requested_markets=[m for m in (job.requested_markets or "").split(",") if m],
        date_from=job.date_from,
        date_to=job.date_to,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        results=[_to_response(run, versions.get(run.model_id)) for run in runs],
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


@router.get("/jobs/{job_id}", response_model=BacktestJobResponse)
def get_backtest_job(job_id: int, session: Session = Depends(get_session)):
    job = session.query(BacktestJob).filter_by(id=job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Backtest job not found.")
    return _job_to_response(session, job)


@router.post("/picks/run", response_model=BacktestJobResponse, status_code=status.HTTP_202_ACCEPTED)
def run_pick_backtest(payload: BacktestRunRequest, session: Session = Depends(get_session)):
    date_from = datetime.combine(payload.from_date, time.min, tzinfo=timezone.utc)
    date_to = datetime.combine(payload.to_date, time.max, tzinfo=timezone.utc)
    job = BacktestJob(
        status="queued",
        requested_markets=",".join(payload.markets),
        date_from=date_from,
        date_to=date_to,
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    try:
        task = backtest_run_task.delay(job.id)
        job.task_id = task.id
        session.commit()
        session.refresh(job)
    except Exception as exc:
        session.rollback()
        job = session.query(BacktestJob).filter_by(id=job.id).first()
        if job is not None:
            job.status = "failed"
            job.error = f"Failed to enqueue backtest job: {exc}"
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(job)

    return _job_to_response(session, job)
