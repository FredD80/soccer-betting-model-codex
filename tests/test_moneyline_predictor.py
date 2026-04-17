from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import (
    Fixture,
    FormCache,
    League,
    ModelVersion,
    MoneylinePrediction,
    OddsSnapshot,
    Result,
    Team,
)
from app.moneyline_predictor import MoneylinePredictor


def _seed_fixture_and_forms(db, *, espn_id: str = "fx1") -> tuple[League, Fixture]:
    league = League(
        name="Premier League",
        country="England",
        espn_id="eng.1",
        odds_api_key="soccer_epl",
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
                goals_scored_avg=2.4,
                goals_conceded_avg=0.8,
                xg_scored_avg=2.3,
                xg_conceded_avg=0.9,
                matches_count=8,
                updated_at=datetime.now(timezone.utc),
            ),
            FormCache(
                team_id=away.id,
                is_home=False,
                goals_scored_avg=0.7,
                goals_conceded_avg=1.9,
                xg_scored_avg=0.8,
                xg_conceded_avg=1.8,
                matches_count=8,
                updated_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db.flush()
    return league, fixture


def _seed_model(db) -> ModelVersion:
    mv = ModelVersion(
        name="moneyline_v1",
        version="1.0",
        active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(mv)
    db.flush()
    return mv


def _seed_league_history(db, league: League, *, n_home=60, n_draw=20, n_away=20) -> None:
    kickoff_base = datetime.now(timezone.utc) - timedelta(days=30)
    counts = [("home", n_home), ("draw", n_draw), ("away", n_away)]
    idx = 0
    for outcome, count in counts:
        for _ in range(count):
            home = Team(name=f"HistHome-{outcome}-{idx}", league_id=league.id)
            away = Team(name=f"HistAway-{outcome}-{idx}", league_id=league.id)
            db.add_all([home, away])
            db.flush()
            fixture = Fixture(
                espn_id=f"hist-{outcome}-{idx}",
                home_team_id=home.id,
                away_team_id=away.id,
                league_id=league.id,
                kickoff_at=kickoff_base - timedelta(hours=idx),
                status="completed",
            )
            db.add(fixture)
            db.flush()
            db.add(
                Result(
                    fixture_id=fixture.id,
                    outcome=outcome,
                    total_goals=2,
                )
            )
            idx += 1
    db.flush()


def test_moneyline_without_market_shrinks_toward_prior(db):
    league, fixture = _seed_fixture_and_forms(db, espn_id="no-market")
    _seed_league_history(db, league, n_home=55, n_draw=25, n_away=20)
    mv = _seed_model(db)

    MoneylinePredictor(db).run(mv.id)

    rows = (
        db.query(MoneylinePrediction)
        .filter_by(model_id=mv.id, fixture_id=fixture.id)
        .order_by(MoneylinePrediction.outcome.asc())
        .all()
    )
    assert len(rows) == 3

    by_outcome = {row.outcome: row for row in rows}
    assert by_outcome["home"].final_probability < by_outcome["home"].probability
    assert sum(row.final_probability for row in rows) == pytest.approx(1.0)


def test_moneyline_with_market_blends_and_normalizes(db):
    league, fixture = _seed_fixture_and_forms(db, espn_id="with-market")
    mv = _seed_model(db)
    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            home_odds=1.90,
            draw_odds=3.50,
            away_odds=4.50,
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.flush()

    MoneylinePredictor(db).run(mv.id)

    rows = (
        db.query(MoneylinePrediction)
        .filter_by(model_id=mv.id, fixture_id=fixture.id)
        .all()
    )
    assert len(rows) == 3
    assert sum(row.final_probability for row in rows) == pytest.approx(1.0)
    assert any(row.final_probability != pytest.approx(row.probability) for row in rows)


def test_parallel_moneyline_profile_differs_from_main(db):
    league, fixture = _seed_fixture_and_forms(db, espn_id="parallel-with-market")
    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            home_odds=1.90,
            draw_odds=3.50,
            away_odds=4.50,
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.flush()

    main_mv = ModelVersion(name="moneyline_v1", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    parallel_mv = ModelVersion(name="parallel_moneyline_v1", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    db.add_all([main_mv, parallel_mv])
    db.flush()

    MoneylinePredictor(db).run(main_mv.id)
    MoneylinePredictor(
        db,
        market_weights_override=(0.20, 0.80),
        no_market_prior_base=0.30,
        no_market_prior_extra=0.20,
    ).run(parallel_mv.id)

    main_home = (
        db.query(MoneylinePrediction)
        .filter_by(model_id=main_mv.id, fixture_id=fixture.id, outcome="home")
        .one()
    )
    parallel_home = (
        db.query(MoneylinePrediction)
        .filter_by(model_id=parallel_mv.id, fixture_id=fixture.id, outcome="home")
        .one()
    )
    assert main_home.final_probability != pytest.approx(parallel_home.final_probability)
