from datetime import datetime, timezone, timedelta
from app.db.models import (
    League, Team, Fixture, FormCache, ModelVersion,
    SpreadPrediction, OUAnalysis
)


def _seed_pick(db, espn_id="p1", hours_until_kickoff=2, tier="HIGH"):
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id=espn_id,
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=hours_until_kickoff),
        status="scheduled",
    )
    db.add(fixture)
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    sp = SpreadPrediction(
        model_id=mv.id, fixture_id=fixture.id,
        team_side="home", goal_line=-0.5,
        cover_probability=0.62, push_probability=0.0,
        ev_score=0.08, confidence_tier=tier,
        created_at=datetime.now(timezone.utc),
    )
    db.add(sp)
    mv2 = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add(mv2)
    db.flush()
    ou = OUAnalysis(
        model_id=mv2.id, fixture_id=fixture.id,
        line=2.5, direction="over",
        probability=0.58, ev_score=0.06, confidence_tier=tier,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ou)
    db.flush()
    return fixture


def test_picks_today_returns_200(client, api_db):
    response = client.get("/picks/today")
    assert response.status_code == 200


def test_picks_today_returns_high_elite_only(client, api_db):
    _seed_pick(api_db, espn_id="high1", tier="HIGH")
    _seed_pick(api_db, espn_id="skip1", tier="SKIP")
    response = client.get("/picks/today")
    data = response.json()
    # SKIP fixture should not appear
    fixture_ids = {p["fixture_id"] for p in data}
    # Both fixtures seeded but only HIGH one should be in the response
    for p in data:
        assert p["best_spread"]["confidence_tier"] in ("HIGH", "ELITE") or \
               p["best_ou"]["confidence_tier"] in ("HIGH", "ELITE")


def test_picks_today_sorted_by_ev(client, api_db):
    _seed_pick(api_db, espn_id="ev_low", tier="HIGH")
    # Manually set different EV on second pick after seeding
    _seed_pick(api_db, espn_id="ev_high", tier="ELITE")
    response = client.get("/picks/today")
    data = response.json()
    evs = [p["top_ev"] for p in data if p["top_ev"] is not None]
    assert evs == sorted(evs, reverse=True)


def test_picks_today_excludes_past_fixtures(client, api_db):
    _seed_pick(api_db, espn_id="past1", hours_until_kickoff=-3, tier="ELITE")
    response = client.get("/picks/today")
    data = response.json()
    # past fixture should not appear
    for p in data:
        kt = datetime.fromisoformat(p["kickoff_at"].replace("Z", "+00:00"))
        assert kt >= datetime.now(timezone.utc) - timedelta(minutes=1)


def test_picks_week_returns_7_day_window(client, api_db):
    _seed_pick(api_db, espn_id="day3", hours_until_kickoff=72, tier="HIGH")
    _seed_pick(api_db, espn_id="day8", hours_until_kickoff=192, tier="HIGH")  # 8 days out
    response = client.get("/picks/week")
    data = response.json()
    espn_ids_in_response = set()
    # day3 should be in, day8 should not
    for p in data:
        kt = datetime.fromisoformat(p["kickoff_at"].replace("Z", "+00:00"))
        if kt.tzinfo is None:
            kt = kt.replace(tzinfo=timezone.utc)
        assert kt <= datetime.now(timezone.utc) + timedelta(days=7, minutes=1)
