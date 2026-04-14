import logging
import os
from celery import Celery
from celery.signals import setup_logging

from app.logging_config import configure_logging


@setup_logging.connect
def _on_celery_setup_logging(**_kwargs):
    configure_logging()


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
        SpreadPredictor(session, ml_enabled=settings.ml_lambda_enabled).run(mv.id)
        session.commit()
        logger.info("spread_predict_task: complete")
        return {"status": "ok"}
    finally:
        session.close()


@celery_app.task(name="collect_line_movement")
def collect_line_movement_task():
    """Poll current odds for all upcoming fixtures and write LineMovement rows."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session
    from app.db.connection import get_engine
    from app.db.models import Fixture, LineMovement
    from app.collector.odds_api import OddsAPIClient
    from app.config import settings

    engine = get_engine()
    client = OddsAPIClient(api_key=settings.odds_api_key)
    now = datetime.now(timezone.utc)
    window = now + timedelta(days=7)

    with Session(engine) as session:
        upcoming = (session.query(Fixture)
                    .filter(Fixture.kickoff_at >= now, Fixture.kickoff_at <= window)
                    .all())
        recorded = 0
        for fixture in upcoming:
            snapshots = client.fetch_odds_for_fixture(fixture.external_id)
            for snap in snapshots:
                for market in ("spreads", "totals"):
                    lines = snap.get(market, [])
                    for entry in lines:
                        lm = LineMovement(
                            fixture_id=fixture.id,
                            book=snap.get("bookmaker", "unknown"),
                            market="spread" if market == "spreads" else "ou",
                            line=entry.get("line", 0.0),
                            odds=entry.get("odds"),
                            recorded_at=datetime.now(timezone.utc),
                        )
                        session.add(lm)
                        recorded += 1
        session.commit()
        return {"recorded": recorded}


@celery_app.task(name="app.celery_app.monte_carlo_task")
def monte_carlo_task():
    """Run Monte Carlo simulation for fixtures kicking off within 2 hours."""
    from datetime import datetime, timedelta, timezone
    from app.db.connection import get_session
    from app.db.models import Fixture, ModelVersion, MonteCarloRun, League, FormCache
    from app.dixon_coles import build_score_matrix
    from app.league_calibration import get_league_params
    from app.monte_carlo import MonteCarloSimulator
    from app.config import settings

    LEAGUE_AVG_GOALS = 1.5
    WINDOW_HOURS = 2

    session = get_session()
    try:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=WINDOW_HOURS)
        upcoming = (
            session.query(Fixture)
            .filter(Fixture.status == "scheduled")
            .filter(Fixture.kickoff_at >= now)
            .filter(Fixture.kickoff_at <= cutoff)
            .all()
        )

        mv = session.query(ModelVersion).filter_by(name="dc_monte_carlo_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="dc_monte_carlo_v1",
                version="1.0",
                description="Dixon-Coles Monte Carlo simulator",
                active=True,
            )
            session.add(mv)
            session.flush()

        simulator = MonteCarloSimulator()
        ran = 0
        for fixture in upcoming:
            home_form = session.query(FormCache).filter_by(
                team_id=fixture.home_team_id, is_home=True
            ).first()
            away_form = session.query(FormCache).filter_by(
                team_id=fixture.away_team_id, is_home=False
            ).first()
            if not home_form or not away_form:
                continue

            league = session.query(League).filter_by(id=fixture.league_id).first()
            league_espn_id = league.espn_id if league else "unknown"
            params = get_league_params(session, league_espn_id)

            lambda_home = max(
                0.1,
                home_form.goals_scored_avg
                * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS)
                * params.home_advantage,
            )
            lambda_away = max(
                0.1,
                away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS),
            )

            matrix = build_score_matrix(lambda_home, lambda_away, rho=params.rho)
            result = simulator.run(matrix)

            mcr = MonteCarloRun(
                fixture_id=fixture.id,
                model_id=mv.id,
                lambda_home=lambda_home,
                lambda_away=lambda_away,
                rho=params.rho,
                home_win_prob=result.home_win_prob,
                draw_prob=result.draw_prob,
                away_win_prob=result.away_win_prob,
                over_15_prob=result.over_15_prob,
                over_25_prob=result.over_25_prob,
                over_35_prob=result.over_35_prob,
                scoreline_json=result.scoreline_json,
                run_at=datetime.now(timezone.utc),
            )
            session.add(mcr)
            ran += 1

        session.commit()
        logger.info("monte_carlo_task: simulated %d fixtures", ran)
        return {"simulated": ran}
    finally:
        session.close()


@celery_app.task(name="app.celery_app.calibration_task")
def calibration_task(window_days: int = 30):
    """Compute rolling Brier + reliability curve per (active model, bet_type)."""
    from app.db.connection import get_session
    from scripts.compute_calibration import run as compute_run
    session = get_session()
    try:
        compute_run(session, window_days=window_days)
        logger.info("calibration_task: complete")
        return {"status": "ok", "window_days": window_days}
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
