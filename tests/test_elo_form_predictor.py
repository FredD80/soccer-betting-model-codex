import json
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import EloFormPrediction, Fixture, League, ModelVersion, Result, Team
from app.bully_engine import EloFormPredictor, goal_projection_from_lambdas, project_match_goal_probs


class StubUnderstatClient:
    def __init__(self, matches_by_key_and_season: dict[tuple[str, int], list[dict]] | None = None):
        self.matches_by_key_and_season = matches_by_key_and_season or {}

    def fetch_league_matches(self, understat_key: str, season: int) -> list[dict]:
        return list(self.matches_by_key_and_season.get((understat_key, season), []))


def _make_match(dt: datetime, home: str, away: str, home_xg: float, away_xg: float) -> dict:
    return {
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "h": {"title": home, "xG": f"{home_xg:.2f}"},
        "a": {"title": away, "xG": f"{away_xg:.2f}"},
        "goals": {"h": "0", "a": "0"},
    }


def _seed_league(db, *, espn_id: str = "eng.1") -> League:
    league = League(
        name="Test League",
        country="England",
        espn_id=espn_id,
        odds_api_key="test-league",
    )
    db.add(league)
    db.flush()
    return league


def _seed_fixture(db, league: League, *, espn_id: str = "future-fixture") -> tuple[Fixture, Team, Team]:
    home = Team(name=f"{espn_id}-Strong", league_id=league.id)
    away = Team(name=f"{espn_id}-Weak", league_id=league.id)
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
    return fixture, home, away


def _seed_history(db, league: League, home: Team, away: Team, n_matches: int = 8) -> None:
    start = datetime.now(timezone.utc) - timedelta(days=20)
    for idx in range(n_matches):
        fixture = Fixture(
            espn_id=f"hist-{idx}",
            home_team_id=home.id,
            away_team_id=away.id,
            league_id=league.id,
            kickoff_at=start + timedelta(days=idx),
            status="completed",
        )
        db.add(fixture)
        db.flush()
        db.add(
            Result(
                fixture_id=fixture.id,
                home_score=2,
                away_score=0,
                outcome="home",
                total_goals=2,
            )
        )
    db.flush()


def _seed_results_sequence(
    db,
    league: League,
    home: Team,
    away: Team,
    outcomes: list[str],
    *,
    start: datetime | None = None,
) -> None:
    base_start = start or (datetime.now(timezone.utc) - timedelta(days=40))
    score_by_outcome = {
        "home": (2, 0),
        "draw": (1, 1),
        "away": (0, 2),
    }
    for idx, outcome in enumerate(outcomes):
        home_score, away_score = score_by_outcome[outcome]
        fixture = Fixture(
            espn_id=f"seq-{league.id}-{idx}",
            home_team_id=home.id,
            away_team_id=away.id,
            league_id=league.id,
            kickoff_at=base_start + timedelta(days=idx),
            status="completed",
        )
        db.add(fixture)
        db.flush()
        db.add(
            Result(
                fixture_id=fixture.id,
                home_score=home_score,
                away_score=away_score,
                outcome=outcome,
                total_goals=home_score + away_score,
            )
        )
    db.flush()


def _seed_model(db, name: str) -> ModelVersion:
    mv = ModelVersion(name=name, version="1.0", active=False, created_at=datetime.now(timezone.utc))
    db.add(mv)
    db.flush()
    return mv


def _latest_prediction(db, model_id: int, fixture_id: int) -> EloFormPrediction:
    return (
        db.query(EloFormPrediction)
        .filter_by(model_id=model_id, fixture_id=fixture_id)
        .one()
    )


def test_elo_form_predictor_favors_higher_elo_team(db):
    league = _seed_league(db)
    fixture, home, away = _seed_fixture(db, league, espn_id="elo-base")
    _seed_history(db, league, home, away)
    model = _seed_model(db, "elo_form_v1")

    kickoff = fixture.kickoff_at - timedelta(days=1)
    matches = [
        _make_match(kickoff - timedelta(days=idx), home.name, f"Opp-{idx}", 2.6, 0.5)
        for idx in range(5)
    ] + [
        _make_match(kickoff - timedelta(days=idx), f"OppA-{idx}", away.name, 1.5, 0.5)
        for idx in range(5)
    ]

    EloFormPredictor(
        db,
        understat_client=StubUnderstatClient({("EPL", 2025): matches}),
        bully_xg_overlay_enabled=False,
    ).run(model.id)

    row = _latest_prediction(db, model.id, fixture.id)
    assert row.home_elo > row.away_elo
    assert row.favorite_side == "home"
    assert row.elo_gap > 0
    assert row.is_bully_spot is True
    assert row.home_probability > row.away_probability
    assert row.home_form_for_avg is not None
    assert row.home_form_against_avg is not None
    assert row.away_form_for_avg is not None
    assert row.away_form_against_avg is not None
    assert row.home_xg_matches_used == 5
    assert row.away_xg_matches_used == 5
    assert row.home_probability + row.draw_probability + row.away_probability == pytest.approx(1.0)
    assert row.p_joint is not None
    assert row.p_joint_raw is not None
    assert row.lambda_favorite is not None
    assert row.lambda_underdog is not None
    assert row.p_joint <= row.home_probability
    assert json.loads(row.gate_summary)["total_gates"] >= 1


def test_elo_form_predictor_penalizes_strong_team_with_falling_xg(db):
    league = _seed_league(db)
    fixture, home, away = _seed_fixture(db, league, espn_id="elo-trend")
    _seed_history(db, league, home, away)
    base_model = _seed_model(db, "elo_form_flat_v1")
    trend_model = _seed_model(db, "elo_form_trend_v1")

    kickoff = fixture.kickoff_at - timedelta(days=1)
    flat_matches = [
        _make_match(kickoff - timedelta(days=idx), home.name, f"HomeFlat-{idx}", 1.6, 1.0)
        for idx in range(5)
    ] + [
        _make_match(kickoff - timedelta(days=idx), f"AwayFlat-{idx}", away.name, 1.1, 0.5)
        for idx in range(5)
    ]
    trend_matches = [
        _make_match(kickoff - timedelta(days=4), home.name, "HomeTrend-0", 2.1, 0.6),
        _make_match(kickoff - timedelta(days=3), home.name, "HomeTrend-1", 1.8, 0.8),
        _make_match(kickoff - timedelta(days=2), home.name, "HomeTrend-2", 1.3, 1.0),
        _make_match(kickoff - timedelta(days=1), home.name, "HomeTrend-3", 0.9, 1.1),
        _make_match(kickoff, home.name, "HomeTrend-4", 0.7, 1.2),
        _make_match(kickoff - timedelta(days=4), "AwayTrend-0", away.name, 1.4, 0.4),
        _make_match(kickoff - timedelta(days=3), "AwayTrend-1", away.name, 1.1, 0.6),
        _make_match(kickoff - timedelta(days=2), "AwayTrend-2", away.name, 0.8, 0.9),
        _make_match(kickoff - timedelta(days=1), "AwayTrend-3", away.name, 0.7, 1.3),
        _make_match(kickoff, "AwayTrend-4", away.name, 0.5, 1.6),
    ]

    EloFormPredictor(
        db,
        understat_client=StubUnderstatClient({("EPL", 2025): flat_matches}),
    ).run(base_model.id)
    EloFormPredictor(
        db,
        understat_client=StubUnderstatClient({("EPL", 2025): trend_matches}),
    ).run(trend_model.id)

    flat_row = _latest_prediction(db, base_model.id, fixture.id)
    trend_row = _latest_prediction(db, trend_model.id, fixture.id)
    assert trend_row.home_probability < flat_row.home_probability
    assert trend_row.away_probability > flat_row.away_probability
    assert trend_row.p_joint < flat_row.p_joint
    assert trend_row.home_xg_trend < 0
    assert trend_row.away_xg_trend > 0
    assert trend_row.trend_adjustment < 0


def test_elo_form_predictor_handles_leagues_without_understat(db):
    league = _seed_league(db, espn_id="usa.1")
    fixture, home, away = _seed_fixture(db, league, espn_id="elo-no-understat")
    _seed_history(db, league, home, away)
    model = _seed_model(db, "elo_form_mls_v1")

    EloFormPredictor(db, understat_client=StubUnderstatClient()).run(model.id)

    row = _latest_prediction(db, model.id, fixture.id)
    assert row.home_form_for_avg == pytest.approx(2.0)
    assert row.home_form_against_avg == pytest.approx(0.0)
    assert row.away_form_for_avg == pytest.approx(0.0)
    assert row.away_form_against_avg == pytest.approx(2.0)
    assert row.home_xg_diff_avg == pytest.approx(2.0)
    assert row.away_xg_diff_avg == pytest.approx(-2.0)
    assert row.home_xg_trend == pytest.approx(0.0)
    assert row.away_xg_trend == pytest.approx(0.0)
    assert row.home_xg_matches_used == 8
    assert row.away_xg_matches_used == 8
    assert row.favorite_side == "home"
    assert row.is_bully_spot is True
    assert row.home_probability + row.draw_probability + row.away_probability == pytest.approx(1.0)
    assert row.p_joint is not None


def test_predict_fixture_fits_league_specific_home_advantage_and_draw_model(db):
    league = _seed_league(db)
    fixture, home, away = _seed_fixture(db, league, espn_id="elo-fit")
    _seed_history(db, league, home, away, n_matches=12)

    prediction = EloFormPredictor(
        db,
        understat_client=StubUnderstatClient(),
        enable_understat_fetch=False,
    ).predict_fixture(fixture, as_of=fixture.kickoff_at)

    assert prediction is not None
    assert prediction.league_fit.home_advantage_elo > 60.0
    assert prediction.league_fit.home_advantage_elo <= 100.0
    assert prediction.league_fit.draw_slope < 0.0
    assert 0.14 <= prediction.league_fit.draw_baseline_probability <= 0.34
    assert prediction.league_fit.avg_home_goals > prediction.league_fit.avg_away_goals
    assert prediction.goals.home_expected_goals > prediction.goals.away_expected_goals


def test_predict_fixture_shrinks_thin_league_draw_fit_toward_global_history(db):
    draw_heavy_league = _seed_league(db, espn_id="fra.1")
    draw_heavy_fixture, draw_heavy_home, draw_heavy_away = _seed_fixture(db, draw_heavy_league, espn_id="draw-heavy")
    _seed_results_sequence(
        db,
        draw_heavy_league,
        draw_heavy_home,
        draw_heavy_away,
        ["draw"] * 36 + ["home"] * 4,
        start=draw_heavy_fixture.kickoff_at - timedelta(days=60),
    )

    thin_league = _seed_league(db, espn_id="ger.1")
    thin_fixture, thin_home, thin_away = _seed_fixture(db, thin_league, espn_id="thin-draw-fit")
    _seed_results_sequence(
        db,
        thin_league,
        thin_home,
        thin_away,
        ["home"],
        start=thin_fixture.kickoff_at - timedelta(days=10),
    )

    prediction = EloFormPredictor(
        db,
        understat_client=StubUnderstatClient(),
        enable_understat_fetch=False,
    ).predict_fixture(thin_fixture, as_of=thin_fixture.kickoff_at)

    assert prediction is not None
    assert prediction.league_fit.samples_used == 1
    assert prediction.league_fit.draw_baseline_probability > 0.30
    assert 0.0 < prediction.v3.p_joint < 1.0


def test_predict_fixture_computes_joint_probability_from_single_score_matrix(db):
    league = _seed_league(db, espn_id="eng.1")
    fixture, home, away = _seed_fixture(db, league, espn_id="elo-joint")
    _seed_history(db, league, home, away, n_matches=12)

    kickoff = fixture.kickoff_at - timedelta(days=1)
    matches = [
        _make_match(kickoff - timedelta(days=idx), home.name, f"HomeJoint-{idx}", 1.85, 0.80)
        for idx in range(5)
    ] + [
        _make_match(kickoff - timedelta(days=idx), f"AwayJoint-{idx}", away.name, 0.85, 1.65)
        for idx in range(5)
    ]

    prediction = EloFormPredictor(
        db,
        understat_client=StubUnderstatClient({("EPL", 2025): matches}),
    ).predict_fixture(fixture, as_of=fixture.kickoff_at)

    assert prediction is not None
    favorite_probability = prediction.probabilities[prediction.favorite_side]
    assert 0.0 < prediction.v3.p_joint_raw <= favorite_probability
    assert 0.0 < prediction.v3.p_joint <= prediction.v3.p_favorite_2plus
    assert prediction.is_bully_spot == prediction.v3.is_bully_candidate


def test_goal_projection_from_lambdas_tracks_expected_goal_side():
    goals = goal_projection_from_lambdas(
        favorite_side="home",
        lambda_favorite=1.9,
        lambda_underdog=0.8,
    )

    assert goals.home_expected_goals == pytest.approx(1.9)
    assert goals.away_expected_goals == pytest.approx(0.8)
    assert goals.home_two_plus_probability > goals.away_two_plus_probability
    assert goals.home_clean_sheet_probability > goals.away_clean_sheet_probability


def test_goal_projection_favors_dominant_team_scoring_and_clean_sheet():
    goals = project_match_goal_probs(
        home_probability=0.66,
        draw_probability=0.19,
        away_probability=0.15,
        home_form_for_avg=2.1,
        home_form_against_avg=0.8,
        away_form_for_avg=0.7,
        away_form_against_avg=1.8,
        home_xg_diff_avg=0.95,
        away_xg_diff_avg=-0.45,
        home_xg_trend=0.08,
        away_xg_trend=-0.06,
        league_avg_home_goals=1.45,
        league_avg_away_goals=1.15,
    )

    assert goals.home_expected_goals > goals.away_expected_goals
    assert goals.home_two_plus_probability > 0.5
    assert goals.home_two_plus_probability > goals.away_two_plus_probability
    assert goals.home_clean_sheet_probability > goals.away_clean_sheet_probability
    assert goals.home_clean_sheet_probability > 0.3
