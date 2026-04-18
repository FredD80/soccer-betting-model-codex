from datetime import datetime, timezone, timedelta
from app.db.models import (
    League, Team, Fixture, FormCache, ModelVersion,
    SpreadPrediction, OUAnalysis, MoneylinePrediction, OddsSnapshot, EloFormPrediction,
)


def _seed_pick(
    db,
    espn_id="p1",
    hours_until_kickoff=2,
    tier="HIGH",
    league_name="EPL",
    country="England",
    league_espn_id="eng.1",
    league_odds_key="soccer_epl",
):
    league = League(name=league_name, country=country, espn_id=league_espn_id, odds_api_key=league_odds_key)
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


def _seed_bully_only_fixture(
    db,
    espn_id="bully-only",
    hours_until_kickoff=2,
    favorite_side="home",
    favorite_probability=0.69,
):
    league = League(name="Serie A", country="Italy", espn_id="ita.1", odds_api_key="soccer_italy_serie_a")
    db.add(league)
    db.flush()

    home = Team(name="Inter", league_id=league.id)
    away = Team(name="Empoli", league_id=league.id)
    db.add_all([home, away])
    db.flush()

    fixture = Fixture(
        espn_id=espn_id,
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=hours_until_kickoff),
        status="scheduled",
    )
    db.add(fixture)

    mv = ModelVersion(name="elo_bully_v1", version="1.0", active=True, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()

    db.add(
        OddsSnapshot(
            fixture_id=fixture.id,
            bookmaker="pinnacle",
            home_odds=1.62,
            draw_odds=4.00,
            away_odds=6.20,
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        EloFormPrediction(
            model_id=mv.id,
            fixture_id=fixture.id,
            favorite_side=favorite_side,
            elo_gap=155.0,
            is_bully_spot=True,
            home_elo=1690.0,
            away_elo=1450.0,
            home_probability=favorite_probability if favorite_side == "home" else 0.17,
            draw_probability=0.14,
            away_probability=favorite_probability if favorite_side == "away" else 0.17,
            home_form_for_avg=2.1,
            home_form_against_avg=0.7,
            away_form_for_avg=0.8,
            away_form_against_avg=1.9,
            home_xg_diff_avg=0.8,
            away_xg_diff_avg=-0.4,
            home_xg_trend=0.06,
            away_xg_trend=-0.04,
            home_xg_matches_used=5,
            away_xg_matches_used=5,
            trend_adjustment=0.03,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    return fixture


def test_picks_today_returns_200(client, api_db):
    response = client.get("/picks/today")
    assert response.status_code == 200


def test_picks_week_returns_all_fixture_tiers(client, api_db):
    _seed_pick(api_db, espn_id="high1", tier="HIGH", hours_until_kickoff=2)
    _seed_pick(api_db, espn_id="skip1", tier="SKIP", hours_until_kickoff=2)
    response = client.get("/picks/week")
    data = response.json()
    tiers = {
        (
            p["best_spread"]["confidence_tier"] if p["best_spread"] else None,
            p["best_ou"]["confidence_tier"] if p["best_ou"] else None,
        )
        for p in data
    }
    assert ("HIGH", "HIGH") in tiers
    assert ("SKIP", "SKIP") in tiers


def test_picks_week_sorts_high_tiers_before_lower_tiers(client, api_db):
    _seed_pick(api_db, espn_id="skip1", tier="SKIP", hours_until_kickoff=2)
    _seed_pick(api_db, espn_id="elite1", tier="ELITE", hours_until_kickoff=2)
    response = client.get("/picks/week")
    data = response.json()
    assert data[0]["best_spread"]["confidence_tier"] == "ELITE"
    assert data[-1]["best_spread"]["confidence_tier"] == "SKIP"


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


def test_picks_by_league_filters_to_requested_league(client, api_db):
    _seed_pick(
        api_db,
        espn_id="primeira1",
        league_name="Primeira Liga",
        country="Portugal",
        league_espn_id="por.1",
        league_odds_key="soccer_portugal_primeira_liga",
    )
    _seed_pick(
        api_db,
        espn_id="mls1",
        league_name="MLS",
        country="USA",
        league_espn_id="usa.1",
        league_odds_key="soccer_usa_mls",
    )
    response = client.get("/picks/league/por.1")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["league"] == "Primeira Liga"


def test_picks_by_league_returns_empty_for_unseeded_league(client, api_db):
    response = client.get("/picks/league/por.1")
    assert response.status_code == 200
    assert response.json() == []


def test_picks_today_can_filter_main_vs_parallel(client, api_db):
    fixture = _seed_pick(api_db, espn_id="parallel1", tier="HIGH", hours_until_kickoff=2)

    main_mv = ModelVersion(name="main_moneyline", version="1.0", active=True)
    parallel_mv = ModelVersion(name="parallel_moneyline", version="1.0", active=True)
    api_db.add_all([main_mv, parallel_mv])
    api_db.flush()

    api_db.add_all([
        MoneylinePrediction(
            model_id=main_mv.id,
            fixture_id=fixture.id,
            outcome="home",
            probability=0.61,
            ev_score=0.03,
            confidence_tier="HIGH",
            final_probability=0.60,
            edge_pct=0.03,
            created_at=datetime.now(timezone.utc),
        ),
        MoneylinePrediction(
            model_id=parallel_mv.id,
            fixture_id=fixture.id,
            outcome="away",
            probability=0.58,
            ev_score=0.09,
            confidence_tier="ELITE",
            final_probability=0.57,
            edge_pct=0.09,
            created_at=datetime.now(timezone.utc),
        ),
    ])
    api_db.flush()

    best = client.get("/picks/today?model_view=best")
    main = client.get("/picks/today?model_view=main")
    parallel = client.get("/picks/today?model_view=parallel")

    assert best.status_code == 200
    assert main.status_code == 200
    assert parallel.status_code == 200

    best_pick = next(p for p in best.json() if p["fixture_id"] == fixture.id)["best_moneyline"]
    main_pick = next(p for p in main.json() if p["fixture_id"] == fixture.id)["best_moneyline"]
    parallel_pick = next(p for p in parallel.json() if p["fixture_id"] == fixture.id)["best_moneyline"]

    assert best_pick["model_name"] == "parallel_moneyline"
    assert main_pick["model_name"] == "main_moneyline"
    assert parallel_pick["model_name"] == "parallel_moneyline"


def test_picks_today_best_includes_bully_moneyline_for_bully_only_fixture(client, api_db):
    fixture = _seed_bully_only_fixture(api_db)

    best = client.get("/picks/today?model_view=best")
    main = client.get("/picks/today?model_view=main")
    parallel = client.get("/picks/today?model_view=parallel")

    assert best.status_code == 200
    assert main.status_code == 200
    assert parallel.status_code == 200

    best_row = next(p for p in best.json() if p["fixture_id"] == fixture.id)
    main_fixture_ids = {p["fixture_id"] for p in main.json()}
    parallel_fixture_ids = {p["fixture_id"] for p in parallel.json()}

    assert best_row["best_moneyline"]["model_name"] == "elo_bully_v1"
    assert best_row["best_moneyline"]["confidence_tier"] in {"HIGH", "ELITE"}
    assert fixture.id not in main_fixture_ids
    assert fixture.id not in parallel_fixture_ids
