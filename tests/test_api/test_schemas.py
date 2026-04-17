def test_spread_pick_schema():
    from api.schemas import SpreadPickResponse
    pick = SpreadPickResponse(
        team_side="home",
        goal_line=-0.5,
        cover_probability=0.62,
        push_probability=0.0,
        ev_score=0.08,
        confidence_tier="HIGH",
    )
    assert pick.goal_line == -0.5
    assert pick.confidence_tier == "HIGH"


def test_ou_pick_schema():
    from api.schemas import OUPickResponse
    ou = OUPickResponse(
        line=2.5,
        direction="over",
        probability=0.58,
        ev_score=0.06,
        confidence_tier="HIGH",
    )
    assert ou.line == 2.5
    assert ou.direction == "over"


def test_fixture_pick_response_schema():
    from api.schemas import FixturePickResponse, SpreadPickResponse, OUPickResponse
    from datetime import datetime, timezone
    pick = FixturePickResponse(
        fixture_id=1,
        home_team="Arsenal",
        away_team="Chelsea",
        league="Premier League",
        kickoff_at=datetime.now(timezone.utc),
        best_spread=SpreadPickResponse(
            team_side="home", goal_line=-0.5,
            cover_probability=0.62, push_probability=0.0,
            ev_score=0.08, confidence_tier="HIGH",
        ),
        best_ou=None,
        top_ev=0.08,
    )
    assert pick.home_team == "Arsenal"
    assert pick.best_spread is not None


def test_prediction_outcome_response_schema():
    from api.schemas import PredictionOutcomeResponse
    from datetime import datetime, timezone

    outcome = PredictionOutcomeResponse(
        fixture_id=1,
        home_team="Arsenal",
        away_team="Chelsea",
        league="Premier League",
        model_name="moneyline_v1",
        version="1.0",
        market_type="moneyline",
        selection="home",
        result_status="win",
        profit_units=1.1,
        graded_at=datetime.now(timezone.utc),
    )
    assert outcome.market_type == "moneyline"
    assert outcome.result_status == "win"


def test_manual_pick_response_schema():
    from api.schemas import ManualPickResponse
    from datetime import datetime, timezone

    pick = ManualPickResponse(
        id=1,
        fixture_id=2,
        home_team="Arsenal",
        away_team="Chelsea",
        league="Premier League",
        market_type="ou",
        selection="over",
        line=2.5,
        decimal_odds=1.95,
        american_odds=-105,
        stake_units=1.0,
        result_status="open",
        created_at=datetime.now(timezone.utc),
    )
    assert pick.market_type == "ou"
    assert pick.selection == "over"
