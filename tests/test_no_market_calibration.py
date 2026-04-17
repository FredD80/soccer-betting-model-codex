from datetime import datetime, timedelta, timezone

from app.db.models import (
    Fixture,
    FormCache,
    League,
    ModelVersion,
    OUAnalysis,
    OddsSnapshot,
    Result,
    SpreadPrediction,
    Team,
)
from app.ou_analyzer import OUAnalyzer
from app.spread_predictor import SpreadPredictor


def _seed_fixture_and_forms(db, *, espn_id: str) -> tuple[League, Fixture]:
    league = League(
        name="Serie A",
        country="Italy",
        espn_id="ita.1",
        odds_api_key="soccer_italy_serie_a",
    )
    db.add(league)
    db.flush()

    home = Team(name=f"{espn_id}-Home", league_id=league.id)
    away = Team(name=f"{espn_id}-Away", league_id=league.id)
    db.add_all([home, away])
    db.flush()

    fixture = Fixture(
        espn_id=espn_id,
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=2),
        status="scheduled",
    )
    db.add(fixture)
    db.flush()

    db.add_all(
        [
            FormCache(
                team_id=home.id,
                is_home=True,
                goals_scored_avg=2.3,
                goals_conceded_avg=0.9,
                xg_scored_avg=2.2,
                xg_conceded_avg=1.0,
                matches_count=8,
                updated_at=datetime.now(timezone.utc),
            ),
            FormCache(
                team_id=away.id,
                is_home=False,
                goals_scored_avg=0.8,
                goals_conceded_avg=1.8,
                xg_scored_avg=0.9,
                xg_conceded_avg=1.7,
                matches_count=8,
                updated_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db.flush()
    return league, fixture


def _seed_model(db, name: str) -> ModelVersion:
    mv = ModelVersion(name=name, version="1.0", active=True, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()
    return mv


def _seed_history(db, league: League, *, n: int = 80) -> None:
    kickoff_base = datetime.now(timezone.utc) - timedelta(days=30)
    for idx in range(n):
        home = Team(name=f"HistHome-{idx}", league_id=league.id)
        away = Team(name=f"HistAway-{idx}", league_id=league.id)
        db.add_all([home, away])
        db.flush()
        fixture = Fixture(
            espn_id=f"hist-no-market-{idx}",
            home_team_id=home.id,
            away_team_id=away.id,
            league_id=league.id,
            kickoff_at=kickoff_base - timedelta(hours=idx),
            status="completed",
        )
        db.add(fixture)
        db.flush()
        # Mostly lower-margin, lower-total outcomes so aggressive priors get pulled down.
        home_score = 1 if idx % 4 else 2
        away_score = 0 if idx % 3 else 1
        db.add(
            Result(
                fixture_id=fixture.id,
                home_score=home_score,
                away_score=away_score,
                total_goals=home_score + away_score,
                outcome="home" if home_score > away_score else "draw",
            )
        )
    db.flush()


def test_spread_without_market_shrinks_probability(db):
    league, fixture = _seed_fixture_and_forms(db, espn_id="spread-no-market")
    _seed_history(db, league, n=90)
    mv = _seed_model(db, "spread_v1")

    SpreadPredictor(db).run(mv.id)

    row = (
        db.query(SpreadPrediction)
        .filter_by(model_id=mv.id, fixture_id=fixture.id, team_side="home", goal_line=-1.5)
        .first()
    )
    assert row is not None
    assert row.final_probability < row.cover_probability


def test_ou_without_market_shrinks_probability(db):
    league, fixture = _seed_fixture_and_forms(db, espn_id="ou-no-market")
    _seed_history(db, league, n=90)
    mv = _seed_model(db, "ou_v1")

    OUAnalyzer(db).run(mv.id)

    row = (
        db.query(OUAnalysis)
        .filter_by(model_id=mv.id, fixture_id=fixture.id, line=1.5)
        .first()
    )
    assert row is not None
    assert row.final_probability < row.probability


def test_spread_with_market_keeps_priced_branch(db):
    league, fixture = _seed_fixture_and_forms(db, espn_id="spread-market")
    mv = _seed_model(db, "spread_v1_market")
    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            spread_home_line=-1.5,
            spread_home_odds=2.10,
            spread_away_line=1.5,
            spread_away_odds=1.76,
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.flush()

    SpreadPredictor(db).run(mv.id)

    row = (
        db.query(SpreadPrediction)
        .filter_by(model_id=mv.id, fixture_id=fixture.id, team_side="home", goal_line=-1.5)
        .first()
    )
    assert row is not None
    assert row.odds_snapshot_id is not None
    assert row.edge_pct is not None


def test_parallel_spread_profile_differs_from_main(db):
    _, fixture = _seed_fixture_and_forms(db, espn_id="spread-parallel-market")
    main_mv = _seed_model(db, "spread_v1_main")
    parallel_mv = _seed_model(db, "parallel_spread_v1")
    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            spread_home_line=-1.5,
            spread_home_odds=2.10,
            spread_away_line=1.5,
            spread_away_odds=1.76,
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.flush()

    SpreadPredictor(db).run(main_mv.id)
    SpreadPredictor(
        db,
        market_weights_override=(0.75, 0.25),
        no_market_prior_base=0.30,
        no_market_prior_extra=0.20,
    ).run(parallel_mv.id)

    main_row = (
        db.query(SpreadPrediction)
        .filter_by(model_id=main_mv.id, fixture_id=fixture.id, team_side="home", goal_line=-1.5)
        .one()
    )
    parallel_row = (
        db.query(SpreadPrediction)
        .filter_by(model_id=parallel_mv.id, fixture_id=fixture.id, team_side="home", goal_line=-1.5)
        .one()
    )
    assert main_row.final_probability != parallel_row.final_probability


def test_parallel_ou_profile_differs_from_main(db):
    _, fixture = _seed_fixture_and_forms(db, espn_id="ou-parallel-market")
    main_mv = _seed_model(db, "ou_v1_main")
    parallel_mv = _seed_model(db, "parallel_ou_v1")
    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            total_goals_line=2.5,
            over_odds=1.91,
            under_odds=1.95,
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.flush()

    OUAnalyzer(db).run(main_mv.id)
    OUAnalyzer(
        db,
        market_weights_override=(0.70, 0.30),
        no_market_prior_base=0.30,
        no_market_prior_extra=0.20,
    ).run(parallel_mv.id)

    main_row = (
        db.query(OUAnalysis)
        .filter_by(model_id=main_mv.id, fixture_id=fixture.id, line=2.5)
        .one()
    )
    parallel_row = (
        db.query(OUAnalysis)
        .filter_by(model_id=parallel_mv.id, fixture_id=fixture.id, line=2.5)
        .one()
    )
    assert main_row.final_probability != parallel_row.final_probability
