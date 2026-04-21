from datetime import datetime, timedelta, timezone

from app.db.models import (
    BacktestRun,
    FavoriteSgpBacktestRow,
    Fixture,
    HistoricalOddsBundle,
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


def seed_bully_history(db):
    league = League(name="La Liga", country="Spain", espn_id="esp.1", odds_api_key="soccer_spain_la_liga")
    db.add(league)
    db.flush()

    home = Team(name="Barcelona", league_id=league.id)
    away = Team(name="Alaves", league_id=league.id)
    db.add_all([home, away])
    db.flush()

    start = datetime.now(timezone.utc) - timedelta(days=16)
    for idx in range(8):
        hist_fixture = Fixture(
            espn_id=f"bully-prior-{idx}",
            home_team_id=home.id,
            away_team_id=away.id,
            league_id=league.id,
            kickoff_at=start + timedelta(days=idx),
            status="completed",
        )
        db.add(hist_fixture)
        db.flush()
        db.add(
            Result(
                fixture_id=hist_fixture.id,
                home_score=3,
                away_score=0,
                outcome="home",
                total_goals=3,
                verified_at=hist_fixture.kickoff_at + timedelta(hours=2),
            )
        )

    kickoff = datetime.now(timezone.utc) - timedelta(days=4)
    fixture = Fixture(
        espn_id="bully-hist-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="completed",
    )
    db.add(fixture)
    db.flush()

    mv = ModelVersion(name="elo_bully_v1", version="1.0", active=True, created_at=kickoff)
    db.add(mv)
    db.flush()

    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            home_odds=1.55,
            draw_odds=4.10,
            away_odds=6.50,
            captured_at=kickoff - timedelta(hours=2),
        )
    )
    db.add(
        Result(
            fixture_id=fixture.id,
            home_score=3,
            away_score=0,
            outcome="home",
            total_goals=3,
            verified_at=kickoff + timedelta(hours=2),
        )
    )
    db.flush()
    return kickoff, mv.id


def seed_bully_history_mixed(db):
    league = League(name="La Liga", country="Spain", espn_id="esp.1", odds_api_key="soccer_spain_la_liga")
    db.add(league)
    db.flush()

    home = Team(name="Real Madrid", league_id=league.id)
    away = Team(name="Getafe", league_id=league.id)
    db.add_all([home, away])
    db.flush()

    start = datetime.now(timezone.utc) - timedelta(days=18)
    for idx in range(8):
        hist_fixture = Fixture(
            espn_id=f"bully-mixed-prior-{idx}",
            home_team_id=home.id,
            away_team_id=away.id,
            league_id=league.id,
            kickoff_at=start + timedelta(days=idx),
            status="completed",
        )
        db.add(hist_fixture)
        db.flush()
        db.add(
            Result(
                fixture_id=hist_fixture.id,
                home_score=3,
                away_score=0,
                outcome="home",
                total_goals=3,
                verified_at=hist_fixture.kickoff_at + timedelta(hours=2),
            )
        )

    first_kickoff = datetime.now(timezone.utc) - timedelta(days=5)
    second_kickoff = datetime.now(timezone.utc) - timedelta(days=4)

    first_fixture = Fixture(
        espn_id="bully-mixed-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=first_kickoff,
        status="completed",
    )
    second_fixture = Fixture(
        espn_id="bully-mixed-2",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=second_kickoff,
        status="completed",
    )
    db.add_all([first_fixture, second_fixture])
    db.flush()

    mv = ModelVersion(name="elo_bully_v1", version="1.0", active=True, created_at=second_kickoff)
    db.add(mv)
    db.flush()

    db.add_all(
        [
            OddsSnapshot(
                fixture_id=first_fixture.id,
                bookmaker="pinnacle",
                home_odds=1.42,
                draw_odds=4.80,
                away_odds=8.20,
                captured_at=first_kickoff - timedelta(hours=2),
            ),
            OddsSnapshot(
                fixture_id=second_fixture.id,
                bookmaker="pinnacle",
                home_odds=1.42,
                draw_odds=4.80,
                away_odds=8.20,
                captured_at=second_kickoff - timedelta(hours=2),
            ),
            Result(
                fixture_id=first_fixture.id,
                home_score=3,
                away_score=0,
                outcome="home",
                total_goals=3,
                verified_at=first_kickoff + timedelta(hours=2),
            ),
            Result(
                fixture_id=second_fixture.id,
                home_score=0,
                away_score=1,
                outcome="away",
                total_goals=1,
                verified_at=second_kickoff + timedelta(hours=2),
            ),
        ]
    )
    db.flush()
    return first_kickoff, second_kickoff, mv.id


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


def test_pick_backtester_backtests_bully_metrics(db):
    kickoff, model_id = seed_bully_history(db)

    summaries = PickBacktester(db).run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
        markets=("bully",),
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.market == "bully"
    assert summary.model_id == model_id
    assert summary.total == 1
    assert summary.correct == 1
    assert summary.accuracy == 1.0
    assert round(summary.roi, 4) == round(1.55 - 1.0, 4)
    assert summary.win_two_plus_hit_rate == 1.0
    assert summary.two_plus_hit_rate == 1.0
    assert summary.clean_sheet_hit_rate == 1.0
    assert summary.two_plus_given_win_rate == 1.0
    assert summary.clean_sheet_given_win_rate == 1.0

    run = db.query(BacktestRun).one()
    assert run.bet_type == "bully"
    assert run.two_plus_hit_rate == 1.0
    assert run.clean_sheet_hit_rate == 1.0
    assert run.two_plus_given_win_rate == 1.0
    assert run.clean_sheet_given_win_rate == 1.0


def test_pick_backtester_uses_synthesized_bully_odds_when_team_totals_available(db):
    kickoff, model_id = seed_bully_history(db)
    snap = db.query(OddsSnapshot).one()
    snap.home_team_total_1_5_over_odds = 1.42
    snap.home_team_total_1_5_under_odds = 2.75
    db.flush()

    backtester = PickBacktester(db)
    summaries = backtester.run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
        markets=("bully",),
    )

    expected_odds = backtester._synthesized_bully_joint_odds(
        favorite_odds=1.55,
        opposite_odds=6.50,
        team_total_over_odds=1.42,
        team_total_under_odds=2.75,
    )
    assert expected_odds is not None
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.market == "bully"
    assert summary.model_id == model_id
    assert round(summary.roi, 6) == round(expected_odds - 1.0, 6)


def test_pick_backtester_prefers_historical_bully_components_over_snapshot(db):
    kickoff, model_id = seed_bully_history(db)
    fixture = db.query(Fixture).filter(Fixture.espn_id == "bully-hist-1").one()
    db.add(
        HistoricalOddsBundle(
            fixture_id=fixture.id,
            source="oddalerts",
            source_fixture_id=114502461,
            competition_id=200,
            season_id=4629,
            bookmaker_id=2,
            bookmaker_name="Bet365",
            odds_type="closing",
            home_odds=1.72,
            draw_odds=3.90,
            away_odds=5.10,
            home_team_total_1_5_over_odds=1.55,
            home_team_total_1_5_under_odds=2.45,
        )
    )
    db.flush()

    backtester = PickBacktester(db)
    summaries = backtester.run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
        markets=("bully",),
    )

    expected_odds = backtester._synthesized_bully_joint_odds(
        favorite_odds=1.72,
        opposite_odds=5.10,
        team_total_over_odds=1.55,
        team_total_under_odds=2.45,
    )
    assert expected_odds is not None
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.market == "bully"
    assert summary.model_id == model_id
    assert round(summary.roi, 6) == round(expected_odds - 1.0, 6)


def test_pick_backtester_prefers_prebuilt_favorite_sgp_backtest_rows(db):
    kickoff, model_id = seed_bully_history(db)
    fixture = db.query(Fixture).filter(Fixture.espn_id == "bully-hist-1").one()
    bundle = HistoricalOddsBundle(
        fixture_id=fixture.id,
        source="oddalerts",
        source_fixture_id=114502462,
        competition_id=419,
        season_id=4634,
        bookmaker_id=1,
        bookmaker_name="Pinnacle",
        odds_type="closing",
        home_odds=1.60,
        draw_odds=4.20,
        away_odds=6.20,
        home_team_total_1_5_over_odds=1.40,
        home_team_total_1_5_under_odds=2.95,
    )
    db.add(bundle)
    db.flush()
    db.add(
        FavoriteSgpBacktestRow(
            historical_bundle_id=bundle.id,
            fixture_id=fixture.id,
            league_id=fixture.league_id,
            kickoff_at=fixture.kickoff_at,
            bookmaker_id=1,
            bookmaker_name="Pinnacle",
            odds_type="closing",
            favorite_side="home",
            favorite_team_id=fixture.home_team_id,
            favorite_team_name="Barcelona",
            underdog_team_id=fixture.away_team_id,
            underdog_team_name="Alaves",
            favorite_ml_odds=1.60,
            favorite_ml_american_odds=-167,
            underdog_ml_odds=6.20,
            underdog_ml_american_odds=520,
            draw_odds=4.20,
            draw_american_odds=320,
            favorite_team_total_over_1_5_odds=1.40,
            favorite_team_total_over_1_5_american_odds=-250,
            favorite_team_total_under_1_5_odds=2.95,
            favorite_team_total_under_1_5_american_odds=195,
            p_favorite_win_fair=0.7948717949,
            p_favorite_team_total_over_1_5_fair=0.6781609195,
            p_joint_fair_independent=0.5383849915,
            sgp_synth_odds=1.3937677054,
            sgp_synth_american_odds=-254,
            sgp_usable_odds=1.91,
            sgp_usable_american_odds=-110,
            favorite_won=True,
            favorite_scored_2_plus=True,
            favorite_ml_and_over_1_5_hit=True,
        )
    )
    db.flush()

    summaries = PickBacktester(db).run(
        kickoff - timedelta(days=1),
        kickoff + timedelta(days=1),
        markets=("bully",),
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.market == "bully"
    assert summary.model_id == model_id
    assert round(summary.roi, 6) == round(1.91 - 1.0, 6)


def test_pick_backtester_backtests_bully_conditional_win_metrics(db):
    first_kickoff, second_kickoff, model_id = seed_bully_history_mixed(db)

    summaries = PickBacktester(db).run(
        first_kickoff - timedelta(days=1),
        second_kickoff + timedelta(days=1),
        markets=("bully",),
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.market == "bully"
    assert summary.model_id == model_id
    assert summary.total == 2
    assert summary.correct == 1
    assert summary.accuracy == 0.5
    assert summary.win_two_plus_hit_rate == 0.5
    assert summary.two_plus_hit_rate == 0.5
    assert summary.clean_sheet_hit_rate == 0.5
    assert summary.two_plus_given_win_rate == 1.0
    assert summary.clean_sheet_given_win_rate == 1.0
