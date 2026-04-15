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
from app.pick_backtester import PickBacktester


def seed_pick_history(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()

    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()

    kickoff = datetime.now(timezone.utc) - timedelta(days=3)
    fixture = Fixture(
        espn_id="hist-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="completed",
    )
    db.add(fixture)
    db.flush()

    mv = ModelVersion(name="practical_backtest_model", version="1.0", active=True, created_at=kickoff)
    db.add(mv)
    db.flush()

    snap = OddsSnapshot(
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
    db.add(snap)
    db.flush()

    created_at = kickoff - timedelta(hours=1)
    db.add(
        SpreadPrediction(
            model_id=mv.id,
            fixture_id=fixture.id,
            team_side="home",
            goal_line=-0.5,
            cover_probability=0.61,
            push_probability=0.0,
            ev_score=0.08,
            confidence_tier="HIGH",
            final_probability=0.61,
            edge_pct=0.08,
            kelly_fraction=0.02,
            steam_downgraded=False,
            created_at=created_at,
        )
    )
    db.add(
        OUAnalysis(
            model_id=mv.id,
            fixture_id=fixture.id,
            line=2.5,
            direction="under",
            probability=0.58,
            ev_score=0.06,
            confidence_tier="HIGH",
            final_probability=0.58,
            edge_pct=0.06,
            kelly_fraction=0.01,
            steam_downgraded=False,
            created_at=created_at,
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
            final_probability=0.49,
            edge_pct=0.04,
            kelly_fraction=0.01,
            steam_downgraded=False,
            created_at=created_at,
        )
    )

    db.add(
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
    db.flush()
    return kickoff, mv.id


def test_pick_backtester_creates_runs_for_all_markets(db):
    kickoff, model_id = seed_pick_history(db)

    summaries = PickBacktester(db).run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
    )

    runs = db.query(BacktestRun).order_by(BacktestRun.bet_type).all()
    assert [run.bet_type for run in runs] == ["moneyline", "ou", "spread"]
    assert len(summaries) == 3
    assert all(run.model_id == model_id for run in runs)
    assert all(run.total == 1 for run in runs)
    assert all(run.correct == 1 for run in runs)


def test_pick_backtester_filters_by_market(db):
    kickoff, _ = seed_pick_history(db)

    summaries = PickBacktester(db).run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
        markets=("spread",),
    )

    assert len(summaries) == 1
    assert summaries[0].market == "spread"
    runs = db.query(BacktestRun).all()
    assert len(runs) == 1
    assert runs[0].bet_type == "spread"
