from datetime import datetime, timedelta, timezone

from app.db.models import EloFormPrediction, Fixture, League, ModelVersion, OddsSnapshot, Team


def test_fixture_schedule_returns_upcoming_fixtures_with_lines(client, api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()

    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()

    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    fixture = Fixture(
        espn_id="sched-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="scheduled",
    )
    api_db.add(fixture)
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
            spread_home_line=-0.5,
            spread_home_odds=1.90,
            spread_away_line=0.5,
            spread_away_odds=1.95,
            captured_at=datetime.now(timezone.utc),
        )
    )
    api_db.flush()

    response = client.get("/fixture/schedule")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["home_team"] == "Arsenal"
    assert data[0]["away_team"] == "Chelsea"
    assert data[0]["lines"]["bookmaker"] == "pinnacle"
    assert data[0]["lines"]["spread_home_line"] == -0.5
    assert data[0]["lines"]["total_goals_line"] == 2.5


def test_fixture_schedule_returns_future_fixtures_beyond_seven_days_by_default(client, api_db):
    league = League(name="La Liga", country="Spain", espn_id="esp.1", odds_api_key="soccer_spain_la_liga")
    api_db.add(league)
    api_db.flush()

    home = Team(name="Barcelona", league_id=league.id)
    away = Team(name="Real Madrid", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()

    fixture = Fixture(
        espn_id="sched-10-days",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(days=10),
        status="scheduled",
    )
    api_db.add(fixture)
    api_db.flush()

    response = client.get("/fixture/schedule")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["home_team"] == "Barcelona"


def test_bully_schedule_returns_ranked_elo_games(client, api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()

    mv = ModelVersion(name="elo_bully_v1", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    api_db.add(mv)
    api_db.flush()

    home1 = Team(name="Liverpool", league_id=league.id)
    away1 = Team(name="Ipswich", league_id=league.id)
    home2 = Team(name="Villa", league_id=league.id)
    away2 = Team(name="Brighton", league_id=league.id)
    api_db.add_all([home1, away1, home2, away2])
    api_db.flush()

    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    fx1 = Fixture(
        espn_id="bully-1",
        home_team_id=home1.id,
        away_team_id=away1.id,
        league_id=league.id,
        kickoff_at=kickoff,
        status="scheduled",
    )
    fx2 = Fixture(
        espn_id="bully-2",
        home_team_id=home2.id,
        away_team_id=away2.id,
        league_id=league.id,
        kickoff_at=kickoff + timedelta(hours=2),
        status="scheduled",
    )
    api_db.add_all([fx1, fx2])
    api_db.flush()

    api_db.add_all([
        OddsSnapshot(
            fixture_id=fx1.id,
            bookmaker="pinnacle",
            home_odds=1.55,
            draw_odds=4.20,
            away_odds=6.80,
            captured_at=datetime.now(timezone.utc),
        ),
        OddsSnapshot(
            fixture_id=fx2.id,
            bookmaker="pinnacle",
            home_odds=2.10,
            draw_odds=3.50,
            away_odds=3.30,
            captured_at=datetime.now(timezone.utc),
        ),
    ])
    api_db.add_all([
        EloFormPrediction(
            model_id=mv.id,
            fixture_id=fx1.id,
            favorite_side="home",
            elo_gap=165.0,
            is_bully_spot=True,
            home_elo=1620.0,
            away_elo=1395.0,
            home_form_for_avg=2.0,
            home_form_against_avg=0.8,
            away_form_for_avg=0.7,
            away_form_against_avg=1.9,
            home_xg_diff_avg=0.9,
            away_xg_diff_avg=-0.5,
            home_xg_trend=-0.08,
            away_xg_trend=0.06,
            home_xg_matches_used=5,
            away_xg_matches_used=5,
            trend_adjustment=-0.03,
            home_probability=0.63,
            draw_probability=0.21,
            away_probability=0.16,
            created_at=datetime.now(timezone.utc),
        ),
        EloFormPrediction(
            model_id=mv.id,
            fixture_id=fx2.id,
            favorite_side="home",
            elo_gap=72.0,
            is_bully_spot=False,
            home_elo=1540.0,
            away_elo=1468.0,
            home_form_for_avg=1.4,
            home_form_against_avg=1.2,
            away_form_for_avg=1.1,
            away_form_against_avg=1.3,
            home_xg_diff_avg=0.3,
            away_xg_diff_avg=0.1,
            home_xg_trend=0.02,
            away_xg_trend=-0.01,
            home_xg_matches_used=5,
            away_xg_matches_used=5,
            trend_adjustment=0.01,
            home_probability=0.48,
            draw_probability=0.26,
            away_probability=0.26,
            created_at=datetime.now(timezone.utc),
        ),
    ])
    api_db.flush()

    response = client.get("/fixture/schedule/bully?use_xg_overlay=false")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["fixture_id"] == fx1.id
    assert data[0]["favorite_team"] == "Liverpool"
    assert data[0]["underdog_team"] == "Ipswich"
    assert data[0]["is_bully_spot"] is True
    assert data[0]["favorite_probability"] == 0.63
    assert data[0]["favorite_two_plus_probability"] > data[0]["underdog_two_plus_probability"]
    assert data[0]["favorite_clean_sheet_probability"] > data[0]["underdog_clean_sheet_probability"]
    assert data[0]["lines"]["bookmaker"] == "pinnacle"
    assert data[1]["fixture_id"] == fx2.id


def test_bully_schedule_applies_xg_overlay_by_default(client, api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()

    mv = ModelVersion(name="elo_bully_v1", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    api_db.add(mv)
    api_db.flush()

    home = Team(name="Liverpool", league_id=league.id)
    away = Team(name="Ipswich", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()

    fixture = Fixture(
        espn_id="bully-overlay-default",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(days=1),
        status="scheduled",
    )
    api_db.add(fixture)
    api_db.flush()

    api_db.add(
        EloFormPrediction(
            model_id=mv.id,
            fixture_id=fixture.id,
            favorite_side="home",
            elo_gap=165.0,
            is_bully_spot=True,
            home_elo=1620.0,
            away_elo=1395.0,
            home_form_for_avg=2.0,
            home_form_against_avg=0.8,
            away_form_for_avg=0.7,
            away_form_against_avg=1.9,
            home_xg_diff_avg=0.9,
            away_xg_diff_avg=-0.5,
            home_xg_trend=-0.08,
            away_xg_trend=0.06,
            home_xg_matches_used=5,
            away_xg_matches_used=5,
            trend_adjustment=-0.03,
            home_probability=0.63,
            draw_probability=0.21,
            away_probability=0.16,
            created_at=datetime.now(timezone.utc),
        )
    )
    api_db.flush()

    response = client.get("/fixture/schedule/bully")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["elo_gap"] == 165.0
    assert data[0]["expected_goals_delta"] < 2.0
    assert data[0]["is_bully_spot"] is False


def test_bully_schedule_ignores_inactive_models(client, api_db):
    league = League(name="Serie A", country="Italy", espn_id="ita.1", odds_api_key="soccer_italy_serie_a")
    api_db.add(league)
    api_db.flush()

    inactive = ModelVersion(name="elo_bully_v1", version="0.9", active=False, created_at=datetime.now(timezone.utc))
    api_db.add(inactive)
    api_db.flush()

    home = Team(name="Inter", league_id=league.id)
    away = Team(name="Como", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()

    fixture = Fixture(
        espn_id="bully-inactive",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(days=1),
        status="scheduled",
    )
    api_db.add(fixture)
    api_db.flush()

    api_db.add(
        EloFormPrediction(
            model_id=inactive.id,
            fixture_id=fixture.id,
            favorite_side="home",
            elo_gap=140.0,
            is_bully_spot=True,
            home_elo=1600.0,
            away_elo=1400.0,
            home_form_for_avg=1.9,
            home_form_against_avg=0.7,
            away_form_for_avg=0.8,
            away_form_against_avg=1.8,
            home_xg_matches_used=5,
            away_xg_matches_used=5,
            trend_adjustment=0.0,
            home_probability=0.60,
            draw_probability=0.23,
            away_probability=0.17,
            created_at=datetime.now(timezone.utc),
        )
    )
    api_db.flush()

    response = client.get("/fixture/schedule/bully")

    assert response.status_code == 200
    assert response.json() == []
