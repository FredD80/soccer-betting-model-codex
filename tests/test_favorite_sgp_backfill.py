from datetime import datetime, timezone

from app.db.models import FavoriteSgpBacktestRow, Fixture, HistoricalOddsBundle, League, Result, Team
from app.favorite_sgp_backfill import FavoriteSgpBacktestBuilder


def test_favorite_sgp_backfill_builds_home_favorite_row(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Manchester City", league_id=league.id)
    away = Team(name="Brentford", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime(2024, 2, 17, 15, 0, tzinfo=timezone.utc),
        status="completed",
    )
    db.add(fixture)
    db.flush()
    db.add(
        Result(
            fixture_id=fixture.id,
            home_score=3,
            away_score=1,
            outcome="home",
            total_goals=4,
            verified_at=datetime.now(timezone.utc),
        )
    )
    bundle = HistoricalOddsBundle(
        fixture_id=fixture.id,
        source="oddalerts",
        source_fixture_id=7002,
        competition_id=423,
        season_id=4630,
        bookmaker_id=2,
        bookmaker_name="Bet365",
        odds_type="closing",
        home_odds=1.42,
        draw_odds=4.95,
        away_odds=7.80,
        home_team_total_1_5_over_odds=1.36,
        home_team_total_1_5_under_odds=3.10,
        imported_at=datetime.now(timezone.utc),
    )
    db.add(bundle)
    db.flush()

    stats = FavoriteSgpBacktestBuilder(db).run(
        league_name="Premier League",
        league_country="England",
    )

    assert stats.bundles_seen == 1
    assert stats.rows_created == 1
    row = db.query(FavoriteSgpBacktestRow).filter_by(historical_bundle_id=bundle.id).one()
    assert row.favorite_side == "home"
    assert row.favorite_team_name == "Manchester City"
    assert row.underdog_team_name == "Brentford"
    assert row.favorite_ml_american_odds == -238
    assert row.favorite_team_total_over_1_5_american_odds == -278
    assert row.p_favorite_win_fair is not None
    assert row.p_favorite_team_total_over_1_5_fair is not None
    assert row.sgp_synth_odds is not None
    assert row.sgp_usable_odds == row.sgp_synth_odds
    assert row.favorite_won is True
    assert row.favorite_scored_2_plus is True
    assert row.favorite_ml_and_over_1_5_hit is True
