import logging
import os
from celery import Celery

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "app",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

app = celery_app  # alias for `celery -A app.celery_app worker` discovery

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,           # re-queue on worker crash
    worker_prefetch_multiplier=1,  # one task at a time per worker (CPU-heavy tasks)
)


@celery_app.task(name="app.celery_app.form_cache_task")
def form_cache_task():
    """Rebuild form cache for all teams from completed results."""
    from app.db.connection import get_session
    from app.form_cache import FormCacheBuilder
    session = get_session()
    try:
        count = FormCacheBuilder(session).build_all()
        logger.info("form_cache_task: updated %d entries", count)
        return {"updated": count}
    finally:
        session.close()


@celery_app.task(name="app.celery_app.spread_predict_task")
def spread_predict_task():
    """Run spread predictor for upcoming fixtures."""
    from app.db.connection import get_session
    from app.db.models import ModelVersion
    from app.spread_predictor import SpreadPredictor
    from app.config import settings
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="spread_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="spread_v1", version=settings.spread_model_version,
                description="Phase 1 Poisson spread predictor", active=True,
            )
            session.add(mv)
            session.flush()
        SpreadPredictor(session).run(mv.id)
        session.commit()
        logger.info("spread_predict_task: complete")
        return {"status": "ok"}
    finally:
        session.close()


@celery_app.task(name="app.celery_app.ou_analyze_task")
def ou_analyze_task():
    """Run O/U analyzer for upcoming fixtures."""
    from app.db.connection import get_session
    from app.db.models import ModelVersion
    from app.ou_analyzer import OUAnalyzer
    from app.config import settings
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="ou_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="ou_v1", version=settings.ou_model_version,
                description="Phase 1 Poisson O/U analyzer", active=True,
            )
            session.add(mv)
            session.flush()
        OUAnalyzer(session).run(mv.id)
        session.commit()
        logger.info("ou_analyze_task: complete")
        return {"status": "ok"}
    finally:
        session.close()
