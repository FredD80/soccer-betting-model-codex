from datetime import datetime, timezone, timedelta
from app.db.models import (
    League, Team, Fixture, FormCache, ModelVersion,
    SpreadPrediction, OUAnalysis
)


def _seed_fixture_with_data(db):
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="detail1",
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=2),
        status="scheduled",
    )
    db.add(fixture)
    db.flush()
    db.add(FormCache(team_id=home.id, is_home=True,
                     goals_scored_avg=1.8, goals_conceded_avg=0.9,
                     spread_cover_rate=0.6, ou_hit_rate_25=0.55,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    db.add(FormCache(team_id=away.id, is_home=False,
                     goals_scored_avg=1.2, goals_conceded_avg=1.5,
                     spread_cover_rate=0.4, ou_hit_rate_25=0.6,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    mv2 = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add_all([mv, mv2])
    db.flush()
    for line in [-1.5, -1.0, -0.5, 0.5, 1.0, 1.5]:
        db.add(SpreadPrediction(
            model_id=mv.id, fixture_id=fixture.id,
            team_side="home" if line < 0 else "away",
            goal_line=line, cover_probability=0.55,
            push_probability=0.0, ev_score=0.05,
            confidence_tier="HIGH", created_at=datetime.now(timezone.utc),
        ))
    for line in [1.5, 2.5, 3.5]:
        db.add(OUAnalysis(
            model_id=mv2.id, fixture_id=fixture.id,
            line=line, direction="over", probability=0.57,
            ev_score=0.05, confidence_tier="HIGH",
            created_at=datetime.now(timezone.utc),
        ))
    db.flush()
    return fixture


def test_fixture_detail_returns_200(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    assert response.status_code == 200


def test_fixture_detail_404_on_missing(client, api_db):
    response = client.get("/fixture/99999")
    assert response.status_code == 404


def test_fixture_detail_includes_form(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    data = response.json()
    assert data["home_form"]["goals_scored_avg"] == 1.8
    assert data["away_form"]["goals_conceded_avg"] == 1.5


def test_fixture_detail_includes_all_spread_picks(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    data = response.json()
    assert len(data["spread_picks"]) == 6


def test_fixture_detail_includes_all_ou_picks(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    data = response.json()
    assert len(data["ou_picks"]) == 3
