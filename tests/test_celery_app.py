def test_celery_app_imports():
    from app.celery_app import celery_app
    assert celery_app.main == "app"


def test_task_names_registered():
    from app.celery_app import celery_app
    registered = set(celery_app.tasks.keys())
    assert "app.celery_app.form_cache_task" in registered
    assert "app.celery_app.spread_predict_task" in registered
    assert "app.celery_app.ou_analyze_task" in registered
    assert "app.celery_app.calibration_task" in registered
    assert "app.celery_app.backtest_run_task" in registered


def test_backtest_run_task_processes_job(db, monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    from app.celery_app import backtest_run_task
    from app.db import connection as db_connection
    from app.db.models import BacktestJob, BacktestRun, Fixture, League, MoneylinePrediction, ModelVersion, OddsSnapshot, Result, Team

    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()

    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()

    kickoff = datetime.now(timezone.utc) - timedelta(days=2)
    fixture = Fixture(
        espn_id="celery-backtest-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="completed",
    )
    db.add(fixture)
    db.flush()

    mv = ModelVersion(name="moneyline_v1", version="1.0", active=True, created_at=kickoff)
    db.add(mv)
    db.flush()

    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            home_odds=2.10,
            draw_odds=3.40,
            away_odds=3.20,
            captured_at=kickoff - timedelta(hours=2),
        )
    )
    db.add(
        MoneylinePrediction(
            model_id=mv.id,
            fixture_id=fixture.id,
            outcome="home",
            probability=0.49,
            ev_score=0.04,
            confidence_tier="ELITE",
            created_at=kickoff - timedelta(hours=1),
        )
    )
    db.add(
        Result(
            fixture_id=fixture.id,
            home_score=2,
            away_score=0,
            outcome="home",
            total_goals=2,
            verified_at=kickoff + timedelta(hours=2),
        )
    )
    job = BacktestJob(
        status="queued",
        requested_markets="moneyline",
        date_from=kickoff - timedelta(days=1),
        date_to=kickoff + timedelta(days=1),
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()

    class SessionProxy:
        def __init__(self, session):
            self._session = session

        def __getattr__(self, name):
            return getattr(self._session, name)

        def close(self):
            return None

    monkeypatch.setattr(db_connection, "get_session", lambda: SessionProxy(db))

    result = backtest_run_task.run(job.id)

    assert result["status"] == "completed"
    db.refresh(job)
    assert job.status == "completed"
    assert job.started_at is not None
    assert job.completed_at is not None
    stored_run = db.query(BacktestRun).one()
    assert stored_run.backtest_job_id == job.id
    assert stored_run.bet_type == "moneyline"
