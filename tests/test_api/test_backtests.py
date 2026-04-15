from datetime import datetime, timedelta, timezone

from app.db.models import (
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


def test_run_backtest_picks_returns_results(client, api_db):
    kickoff = _seed_completed_pick(api_db)

    response = client.post(
        "/backtests/picks/run",
        json={
            "from_date": (kickoff - timedelta(days=1)).date().isoformat(),
            "to_date": (kickoff + timedelta(days=1)).date().isoformat(),
            "markets": ["spread", "moneyline"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {row["market"] for row in data} == {"spread", "moneyline"}
    assert api_db.query(BacktestRun).count() == 2


def test_list_backtest_runs_returns_recent_rows(client, api_db):
    kickoff = _seed_completed_pick(api_db)
    client.post(
        "/backtests/picks/run",
        json={
            "from_date": (kickoff - timedelta(days=1)).date().isoformat(),
            "to_date": (kickoff + timedelta(days=1)).date().isoformat(),
            "markets": ["ou"],
        },
    )

    response = client.get("/backtests/runs")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["market"] == "ou"
    assert data[0]["model_name"] == "moneyline_v1"
