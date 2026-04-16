from datetime import datetime, timedelta, timezone

from app.db.models import Fixture, League, OddsSnapshot, Team


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
