import logging
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.db.connection import get_session
from app.db.models import SchedulerLog
from app.celery_app import celery_app
from app.collector.collector import DataCollector
from app.predictor import PredictionEngine
from app.tracker import ResultsTracker
from app.config import settings
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

PARALLEL_SPREAD_WEIGHTS = (0.75, 0.25)
PARALLEL_OU_WEIGHTS = (0.70, 0.30)
PARALLEL_MONEYLINE_WEIGHTS = (0.20, 0.80)
PARALLEL_NO_MARKET_PRIOR_BASE = 0.30
PARALLEL_NO_MARKET_PRIOR_EXTRA = 0.20


def collect_job():
    session = get_session()
    log = SchedulerLog(job_name="collect", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        DataCollector(session).run()
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("collect_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def predict_job(model_classes):
    session = get_session()
    log = SchedulerLog(job_name="predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        PredictionEngine(session, model_classes=model_classes).run()
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def track_results_job():
    session = get_session()
    log = SchedulerLog(job_name="track_results", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.db.models import Fixture, Result
        from app.collector.espn_api import ESPNClient
        espn = ESPNClient()
        all_fixtures = espn.fetch_all_leagues()
        tracker = ResultsTracker(session)
        for league_id, fixtures in all_fixtures.items():
            for espn_fixture in fixtures:
                if espn_fixture["status"] != "completed":
                    continue
                db_fixture = session.query(Fixture).filter_by(espn_id=espn_fixture["espn_id"]).first()
                if not db_fixture:
                    continue
                existing = session.query(Result).filter_by(fixture_id=db_fixture.id).first()
                if not existing:
                    if espn_fixture["home_score"] is None:
                        continue
                    tracker.save_result(
                        db_fixture.id,
                        home_score=espn_fixture["home_score"],
                        away_score=espn_fixture["away_score"],
                        ht_home_score=espn_fixture.get("ht_home_score"),
                        ht_away_score=espn_fixture.get("ht_away_score"),
                    )
                    tracker.evaluate_predictions(db_fixture.id)
                tracker.settle_live_predictions(db_fixture.id)
                tracker.settle_weekly_model_picks(db_fixture.id)
                tracker.settle_manual_picks(db_fixture.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("track_results_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def form_cache_job():
    session = get_session()
    log = SchedulerLog(job_name="form_cache", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.form_cache import FormCacheBuilder
        count = FormCacheBuilder(session).build_all()
        log.status = "success"
        logger.info("form_cache_job: updated %d cache entries", count)
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("form_cache_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def spread_predict_job():
    session = get_session()
    log = SchedulerLog(job_name="spread_predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.spread_predictor import SpreadPredictor
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="spread_v1", active=True).first()
        if not mv:
            mv = ModelVersion(name="spread_v1", version=settings.spread_model_version,
                              description="Phase 1 Poisson spread predictor", active=True)
            session.add(mv)
            session.flush()
        SpreadPredictor(session, ml_enabled=settings.ml_lambda_enabled).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("spread_predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def ou_analyze_job():
    session = get_session()
    log = SchedulerLog(job_name="ou_analyze", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.ou_analyzer import OUAnalyzer
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="ou_v1", active=True).first()
        if not mv:
            mv = ModelVersion(name="ou_v1", version=settings.ou_model_version,
                              description="Phase 1 Poisson O/U analyzer", active=True)
            session.add(mv)
            session.flush()
        OUAnalyzer(session, ml_enabled=settings.ml_lambda_enabled).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("ou_analyze_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def moneyline_predict_job():
    session = get_session()
    log = SchedulerLog(job_name="moneyline_predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.moneyline_predictor import MoneylinePredictor
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="moneyline_v1", active=True).first()
        if not mv:
            mv = ModelVersion(name="moneyline_v1", version="1.0.0",
                              description="Dixon-Coles 3-way moneyline", active=True)
            session.add(mv)
            session.flush()
        MoneylinePredictor(session, ml_enabled=settings.ml_lambda_enabled).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("moneyline_predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def elo_bully_predict_job():
    session = get_session()
    log = SchedulerLog(job_name="elo_bully_predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.elo_form_predictor import EloFormPredictor
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="elo_bully_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="elo_bully_v1",
                version="1.0.0",
                description="Standalone Elo bully model with last-five xG trend adjustment",
                active=True,
            )
            session.add(mv)
            session.flush()
        EloFormPredictor(session).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("elo_bully_predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def weekly_model_snapshot_job():
    session = get_session()
    log = SchedulerLog(job_name="weekly_model_snapshot", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.season_tracker import ensure_current_week_model_snapshots

        ensure_current_week_model_snapshots(session)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("weekly_model_snapshot_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def parallel_spread_predict_job():
    session = get_session()
    log = SchedulerLog(job_name="parallel_spread_predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.spread_predictor import SpreadPredictor
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="parallel_spread_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="parallel_spread_v1",
                version=settings.spread_model_version,
                description="Parallel spread predictor with stronger market and prior shrink",
                active=True,
            )
            session.add(mv)
            session.flush()
        SpreadPredictor(
            session,
            ml_enabled=settings.ml_lambda_enabled,
            market_weights_override=PARALLEL_SPREAD_WEIGHTS,
            no_market_prior_base=PARALLEL_NO_MARKET_PRIOR_BASE,
            no_market_prior_extra=PARALLEL_NO_MARKET_PRIOR_EXTRA,
        ).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("parallel_spread_predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def parallel_ou_analyze_job():
    session = get_session()
    log = SchedulerLog(job_name="parallel_ou_analyze", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.ou_analyzer import OUAnalyzer
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="parallel_ou_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="parallel_ou_v1",
                version=settings.ou_model_version,
                description="Parallel O/U analyzer with stronger market and prior shrink",
                active=True,
            )
            session.add(mv)
            session.flush()
        OUAnalyzer(
            session,
            ml_enabled=settings.ml_lambda_enabled,
            market_weights_override=PARALLEL_OU_WEIGHTS,
            no_market_prior_base=PARALLEL_NO_MARKET_PRIOR_BASE,
            no_market_prior_extra=PARALLEL_NO_MARKET_PRIOR_EXTRA,
        ).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("parallel_ou_analyze_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def parallel_moneyline_predict_job():
    session = get_session()
    log = SchedulerLog(job_name="parallel_moneyline_predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.moneyline_predictor import MoneylinePredictor
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="parallel_moneyline_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="parallel_moneyline_v1",
                version="1.0.0",
                description="Parallel moneyline predictor with stronger market and prior shrink",
                active=True,
            )
            session.add(mv)
            session.flush()
        MoneylinePredictor(
            session,
            ml_enabled=settings.ml_lambda_enabled,
            market_weights_override=PARALLEL_MONEYLINE_WEIGHTS,
            no_market_prior_base=PARALLEL_NO_MARKET_PRIOR_BASE,
            no_market_prior_extra=PARALLEL_NO_MARKET_PRIOR_EXTRA,
        ).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("parallel_moneyline_predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def start_scheduler(model_classes):
    scheduler = BlockingScheduler()
    scheduler.add_job(
        collect_job, IntervalTrigger(hours=settings.collection_interval_hours),
        id="collect", replace_existing=True
    )
    scheduler.add_job(
        predict_job, IntervalTrigger(minutes=30),
        args=[model_classes], id="predict", replace_existing=True
    )
    scheduler.add_job(
        track_results_job, IntervalTrigger(hours=1),
        id="track_results", replace_existing=True
    )
    scheduler.add_job(
        form_cache_job, IntervalTrigger(hours=settings.collection_interval_hours),
        id="form_cache", replace_existing=True
    )
    scheduler.add_job(
        spread_predict_job, IntervalTrigger(minutes=30),
        id="spread_predict", replace_existing=True
    )
    scheduler.add_job(
        ou_analyze_job, IntervalTrigger(minutes=30),
        id="ou_analyze", replace_existing=True
    )
    scheduler.add_job(
        moneyline_predict_job, IntervalTrigger(minutes=30),
        id="moneyline_predict", replace_existing=True
    )
    scheduler.add_job(
        elo_bully_predict_job, IntervalTrigger(minutes=30),
        id="elo_bully_predict", replace_existing=True
    )
    scheduler.add_job(
        weekly_model_snapshot_job, IntervalTrigger(hours=6),
        id="weekly_model_snapshot", replace_existing=True
    )
    scheduler.add_job(
        parallel_spread_predict_job, IntervalTrigger(minutes=30),
        id="parallel_spread_predict", replace_existing=True
    )
    scheduler.add_job(
        parallel_ou_analyze_job, IntervalTrigger(minutes=30),
        id="parallel_ou_analyze", replace_existing=True
    )
    scheduler.add_job(
        parallel_moneyline_predict_job, IntervalTrigger(minutes=30),
        id="parallel_moneyline_predict", replace_existing=True
    )
    scheduler.add_job(
        lambda: celery_app.send_task("collect_line_movement"),
        IntervalTrigger(minutes=30), id="line_movement_poll",
        replace_existing=True
    )
    scheduler.add_job(
        lambda: celery_app.send_task("app.celery_app.monte_carlo_task"),
        IntervalTrigger(minutes=30), id="monte_carlo",
        replace_existing=True
    )
    scheduler.add_job(
        lambda: celery_app.send_task("app.celery_app.calibration_task"),
        CronTrigger(hour=3, minute=0), id="calibration",
        replace_existing=True
    )
    logger.info("Scheduler started")
    scheduler.start()
