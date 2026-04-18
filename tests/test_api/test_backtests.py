from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from api.routers import backtests as backtests_router
from app.db.models import (
    BacktestJob,
    BacktestRun,
    Fixture,
    League,
    ModelVersion,
    MoneylinePrediction,
    OddsSnapshot,
    OUAnalysis,
    Result,
    SpreadPrediction,
    Team,
)
from app.pick_backtester import PickBacktester


def _seed_completed_pick(api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()

    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()

    kickoff = datetime.now(timezone.utc) - timedelta(days=2)
    fixture = Fixture(
        espn_id="backtest-fixture-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="completed",
    )
    api_db.add(fixture)
    api_db.flush()

    mv = ModelVersion(name="moneyline_v1", version="1.0", active=True, created_at=kickoff)
    api_db.add(mv)
    api_db.flush()

    api_db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            home_odds=2.10,
            draw_odds=3.40,
            away_odds=3.20,
            total_goals_line=2.5,
            over_odds=1.95,
            under_odds=1.85,
            captured_at=kickoff - timedelta(hours=2),
            spread_home_line=-0.5,
            spread_home_odds=1.90,
            spread_away_line=0.5,
            spread_away_odds=1.95,
        )
    )
    created_at = kickoff - timedelta(hours=1)
    api_db.add(
        SpreadPrediction(
            model_id=mv.id,
            fixture_id=fixture.id,
            team_side="home",
            goal_line=-0.5,
            cover_probability=0.60,
            push_probability=0.0,
            ev_score=0.07,
            confidence_tier="HIGH",
            created_at=created_at,
        )
    )
    api_db.add(
        OUAnalysis(
            model_id=mv.id,
            fixture_id=fixture.id,
            line=2.5,
            direction="under",
            probability=0.58,
            ev_score=0.05,
            confidence_tier="HIGH",
            created_at=created_at,
        )
    )
    api_db.add(
        MoneylinePrediction(
            model_id=mv.id,
            fixture_id=fixture.id,
            outcome="home",
            probability=0.49,
            ev_score=0.04,
            confidence_tier="ELITE",
            created_at=created_at,
        )
    )
    api_db.add(
        Result(
            fixture_id=fixture.id,
            home_score=2,
            away_score=0,
            outcome="home",
            ht_home_score=1,
            ht_away_score=0,
            ht_outcome="home",
            total_goals=2,
            ht_total_goals=1,
            verified_at=kickoff + timedelta(hours=2),
        )
    )
    api_db.flush()
    return kickoff


def _seed_completed_bully_pick(api_db):
    league = League(name="Serie A", country="Italy", espn_id="ita.1", odds_api_key="soccer_italy_serie_a")
    api_db.add(league)
    api_db.flush()

    home = Team(name="Internazionale", league_id=league.id)
    away = Team(name="Cagliari", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()

    start = datetime.now(timezone.utc) - timedelta(days=15)
    for idx in range(8):
        hist_fixture = Fixture(
            espn_id=f"backtest-bully-prior-{idx}",
            home_team_id=home.id,
            away_team_id=away.id,
            league_id=league.id,
            kickoff_at=start + timedelta(days=idx),
            status="completed",
        )
        api_db.add(hist_fixture)
        api_db.flush()
        api_db.add(
            Result(
                fixture_id=hist_fixture.id,
                home_score=2,
                away_score=0,
                outcome="home",
                total_goals=2,
                verified_at=hist_fixture.kickoff_at + timedelta(hours=2),
            )
        )

    kickoff = datetime.now(timezone.utc) - timedelta(days=3)
    fixture = Fixture(
        espn_id="backtest-bully-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="completed",
    )
    api_db.add(fixture)
    api_db.flush()

    mv = ModelVersion(name="elo_bully_v1", version="1.0", active=True, created_at=kickoff)
    api_db.add(mv)
    api_db.flush()

    api_db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            home_odds=1.48,
            draw_odds=4.50,
            away_odds=7.80,
            captured_at=kickoff - timedelta(hours=2),
        )
    )
    api_db.add(
        Result(
            fixture_id=fixture.id,
            home_score=2,
            away_score=0,
            outcome="home",
            total_goals=2,
            verified_at=kickoff + timedelta(hours=2),
        )
    )
    api_db.flush()
    return kickoff


def test_run_backtest_picks_enqueues_job(client, api_db, monkeypatch):
    kickoff = _seed_completed_pick(api_db)
    monkeypatch.setattr(
        backtests_router.backtest_run_task,
        "delay",
        lambda job_id: SimpleNamespace(id=f"task-{job_id}"),
    )

    response = client.post(
        "/backtests/picks/run",
        json={
            "from_date": (kickoff - timedelta(days=1)).date().isoformat(),
            "to_date": (kickoff + timedelta(days=1)).date().isoformat(),
            "markets": ["spread", "moneyline"],
        },
    )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "queued"
    assert data["requested_markets"] == ["spread", "moneyline"]
    assert data["results"] == []

    job = api_db.query(BacktestJob).one()
    assert job.task_id == f"task-{job.id}"
    assert job.requested_markets == "spread,moneyline"
    assert api_db.query(BacktestRun).count() == 0


def test_list_backtest_runs_returns_recent_rows(client, api_db):
    kickoff = _seed_completed_pick(api_db)
    PickBacktester(api_db).run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
        markets=("ou",),
    )

    response = client.get("/backtests/runs")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["market"] == "ou"
    assert data[0]["model_name"] == "moneyline_v1"


def test_get_backtest_job_returns_bully_metrics(client, api_db):
    kickoff = _seed_completed_bully_pick(api_db)
    job = BacktestJob(
        status="completed",
        requested_markets="bully",
        date_from=kickoff - timedelta(days=1),
        date_to=kickoff + timedelta(days=1),
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    api_db.add(job)
    api_db.flush()
    PickBacktester(api_db).run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
        markets=("bully",),
        backtest_job_id=job.id,
    )

    response = client.get(f"/backtests/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["requested_markets"] == ["bully"]
    assert len(data["results"]) == 1
    assert data["results"][0]["market"] == "bully"
    assert data["results"][0]["model_name"] == "elo_bully_v1"
    assert data["results"][0]["accuracy"] == 1.0
    assert data["results"][0]["win_two_plus_hit_rate"] == 1.0
    assert data["results"][0]["two_plus_hit_rate"] == 1.0
    assert data["results"][0]["clean_sheet_hit_rate"] == 1.0
    assert data["results"][0]["two_plus_given_win_rate"] == 1.0
    assert data["results"][0]["clean_sheet_given_win_rate"] == 1.0

    stored = api_db.query(BacktestRun).one()
    assert stored.backtest_job_id == job.id
    assert stored.bet_type == "bully"
    assert stored.two_plus_hit_rate == 1.0
    assert stored.clean_sheet_hit_rate == 1.0
    assert stored.two_plus_given_win_rate == 1.0
    assert stored.clean_sheet_given_win_rate == 1.0
