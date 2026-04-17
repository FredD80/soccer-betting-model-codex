from datetime import datetime, timezone, timedelta

from app.db.models import (
    League, Team, Fixture, ModelVersion, PredictionOutcome, ManualPick,
)


def _seed_outcome(api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()
    fixture = Fixture(
        espn_id="po-api-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) - timedelta(hours=3),
        status="completed",
    )
    api_db.add(fixture)
    mv = ModelVersion(name="moneyline_v1", version="1.0", active=True)
    api_db.add(mv)
    api_db.flush()
    api_db.add(PredictionOutcome(
        fixture_id=fixture.id,
        model_id=mv.id,
        market_type="moneyline",
        prediction_row_id=101,
        selection="home",
        decimal_odds=2.1,
        american_odds=110,
        model_probability=0.52,
        final_probability=0.50,
        edge_pct=0.02,
        kelly_fraction=0.01,
        confidence_tier="HIGH",
        result_status="win",
        profit_units=1.1,
        graded_at=datetime.now(timezone.utc),
    ))
    api_db.flush()


def _seed_manual_vs_models(api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()
    home = Team(name="Liverpool", league_id=league.id)
    away = Team(name="Brighton", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()
    fixture = Fixture(
        espn_id="compare-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc),
        status="completed",
    )
    api_db.add(fixture)
    main_model = ModelVersion(name="main_ou", version="1.0", active=True)
    parallel_model = ModelVersion(name="parallel_ou", version="1.0", active=True)
    api_db.add_all([main_model, parallel_model])
    api_db.flush()
    manual = ManualPick(
        fixture_id=fixture.id,
        market_type="ou",
        selection="over",
        line=2.5,
        decimal_odds=1.95,
        american_odds=-105,
        stake_units=2.0,
        result_status="win",
        profit_units=1.9,
        graded_at=datetime.now(timezone.utc),
    )
    api_db.add(manual)
    api_db.add_all([
        PredictionOutcome(
            fixture_id=fixture.id,
            model_id=main_model.id,
            market_type="ou",
            prediction_row_id=201,
            selection="over",
            line=2.5,
            decimal_odds=1.90,
            american_odds=-111,
            model_probability=0.58,
            final_probability=0.56,
            edge_pct=0.03,
            confidence_tier="HIGH",
            result_status="win",
            profit_units=0.9,
            graded_at=datetime.now(timezone.utc),
        ),
        PredictionOutcome(
            fixture_id=fixture.id,
            model_id=parallel_model.id,
            market_type="ou",
            prediction_row_id=202,
            selection="over",
            line=2.5,
            decimal_odds=2.05,
            american_odds=105,
            model_probability=0.61,
            final_probability=0.59,
            edge_pct=0.05,
            confidence_tier="ELITE",
            result_status="win",
            profit_units=1.05,
            graded_at=datetime.now(timezone.utc),
        ),
    ])
    api_db.flush()
    return manual


def _seed_fixture_level_compare(api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()
    fixture = Fixture(
        espn_id="compare-fixture-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc),
        status="completed",
    )
    api_db.add(fixture)
    main_model = ModelVersion(name="main_model", version="1.0", active=True)
    parallel_model = ModelVersion(name="parallel_model", version="1.0", active=True)
    api_db.add_all([main_model, parallel_model])
    api_db.flush()
    manual = ManualPick(
        fixture_id=fixture.id,
        market_type="ou",
        selection="over",
        line=2.5,
        decimal_odds=1.95,
        american_odds=-105,
        stake_units=1.0,
        result_status="win",
        profit_units=0.95,
        graded_at=datetime.now(timezone.utc),
    )
    api_db.add(manual)
    api_db.add_all([
        PredictionOutcome(
            fixture_id=fixture.id,
            model_id=main_model.id,
            market_type="ou",
            prediction_row_id=301,
            selection="over",
            line=2.5,
            decimal_odds=1.9,
            american_odds=-111,
            model_probability=0.57,
            final_probability=0.55,
            edge_pct=0.03,
            confidence_tier="HIGH",
            result_status="win",
            profit_units=0.9,
            graded_at=datetime.now(timezone.utc),
        ),
        PredictionOutcome(
            fixture_id=fixture.id,
            model_id=main_model.id,
            market_type="moneyline",
            prediction_row_id=302,
            selection="home",
            line=None,
            decimal_odds=2.1,
            american_odds=110,
            model_probability=0.51,
            final_probability=0.49,
            edge_pct=0.06,
            confidence_tier="ELITE",
            result_status="win",
            profit_units=1.1,
            graded_at=datetime.now(timezone.utc),
        ),
        PredictionOutcome(
            fixture_id=fixture.id,
            model_id=parallel_model.id,
            market_type="ou",
            prediction_row_id=303,
            selection="under",
            line=2.5,
            decimal_odds=2.0,
            american_odds=100,
            model_probability=0.54,
            final_probability=0.52,
            edge_pct=0.04,
            confidence_tier="HIGH",
            result_status="loss",
            profit_units=-1.0,
            graded_at=datetime.now(timezone.utc),
        ),
    ])
    api_db.flush()
    return manual


def test_performance_outcomes_returns_settled_rows(client, api_db):
    _seed_outcome(api_db)
    response = client.get("/performance/outcomes")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["market_type"] == "moneyline"
    assert data[0]["result_status"] == "win"
    assert data[0]["home_team"] == "Arsenal"


def test_performance_outcomes_summary_groups_rows(client, api_db):
    _seed_outcome(api_db)
    response = client.get("/performance/outcomes/summary")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["market_type"] == "moneyline"
    assert data[0]["wins"] == 1
    assert data[0]["roi"] == 1.1


def test_create_manual_pick_and_list_it(client, api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()
    fixture = Fixture(
        espn_id="manual-api-1",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc),
        status="scheduled",
    )
    api_db.add(fixture)
    api_db.flush()

    response = client.post("/performance/manual-picks", json={
        "fixture_id": fixture.id,
        "market_type": "ou",
        "selection": "over",
        "line": 2.5,
        "american_odds": -105,
        "stake_units": 1.5,
        "bookmaker": "draftkings",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["market_type"] == "ou"
    assert data["stake_units"] == 1.5

    list_response = client.get("/performance/manual-picks")
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]["bookmaker"] == "draftkings"


def test_manual_pick_summary_groups_settled_picks(client, api_db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    api_db.add(league)
    api_db.flush()
    home = Team(name="Liverpool", league_id=league.id)
    away = Team(name="Brighton", league_id=league.id)
    api_db.add_all([home, away])
    api_db.flush()
    fixture = Fixture(
        espn_id="manual-api-2",
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc),
        status="completed",
    )
    api_db.add(fixture)
    api_db.flush()
    api_db.add(ManualPick(
        fixture_id=fixture.id,
        market_type="moneyline",
        selection="home",
        decimal_odds=1.8,
        american_odds=-125,
        stake_units=2.0,
        result_status="win",
        profit_units=1.6,
        graded_at=datetime.now(timezone.utc),
    ))
    api_db.flush()

    response = client.get("/performance/manual-picks/summary")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["market_type"] == "moneyline"
    assert data[0]["profit_units"] == 1.6
    assert data[0]["roi"] == 0.8


def test_manual_vs_models_returns_both_main_and_parallel(client, api_db):
    manual = _seed_manual_vs_models(api_db)

    response = client.get("/performance/compare/manual-vs-models")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    model_names = {row["model_name"] for row in data}
    assert model_names == {"main_ou", "parallel_ou"}
    assert {row["manual_pick_id"] for row in data} == {manual.id}


def test_manual_vs_models_summary_groups_by_model(client, api_db):
    _seed_manual_vs_models(api_db)
    response = client.get("/performance/compare/manual-vs-models/summary")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {row["model_name"] for row in data}
    assert names == {"main_ou", "parallel_ou"}


def test_compare_fixtures_returns_best_pick_per_model_even_if_different(client, api_db):
    manual = _seed_fixture_level_compare(api_db)
    response = client.get("/performance/compare/fixtures")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    row = data[0]
    assert row["manual_pick_id"] == manual.id
    assert row["manual_market_type"] == "ou"
    compared = {item["model_name"]: item for item in row["compared_models"]}
    assert set(compared) == {"main_model", "parallel_model"}
    assert compared["main_model"]["market_type"] == "moneyline"
    assert compared["main_model"]["selection"] == "home"
    assert compared["parallel_model"]["market_type"] == "ou"
    assert compared["parallel_model"]["selection"] == "under"
