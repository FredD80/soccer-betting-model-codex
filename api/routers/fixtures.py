import math
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.models import (
    Fixture, League, Team, FormCache, Result, ManualPick,
    SpreadPrediction, OUAnalysis, OddsSnapshot, MoneylinePrediction, EloFormPrediction, ModelVersion
)
from app.bully_engine import (
    DEFAULT_BULLY_GAP_THRESHOLD,
    fit_league_goal_rates,
    passes_bully_xg_overlay,
    project_match_goal_probs,
)
from api.deps import get_session
from api.schemas import (
    FixtureDetailResponse, FormSummary,
    SpreadPickResponse, OUPickResponse, ScheduledFixtureResponse, ScheduleLineResponse,
    EloFormScheduleResponse, DashboardStatusResponse
)
from datetime import datetime, timedelta, timezone

router = APIRouter()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _poisson_zero_probability(expected_goals: float) -> float:
    return math.exp(-expected_goals)


def _poisson_two_plus_probability(expected_goals: float) -> float:
    return 1.0 - (_poisson_zero_probability(expected_goals) * (1.0 + expected_goals))


def _project_match_goal_probs(
    *,
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    home_xg_diff_avg: float | None,
    away_xg_diff_avg: float | None,
    home_xg_trend: float | None,
    away_xg_trend: float | None,
) -> dict[str, float]:
    strength_signal = _clamp(home_probability - away_probability, -0.75, 0.75)
    trend_signal = _clamp((home_xg_trend or 0.0) - (away_xg_trend or 0.0), -0.4, 0.4)
    form_signal = _clamp((home_xg_diff_avg or 0.0) - (away_xg_diff_avg or 0.0), -2.0, 2.0)
    total_signal = _clamp((home_xg_diff_avg or 0.0) + (away_xg_diff_avg or 0.0), -2.0, 2.0)

    total_goals = _clamp(2.6 + (0.12 * total_signal) + (0.18 * abs(trend_signal)), 1.8, 3.8)
    home_share = _clamp(
        0.5 + (0.42 * strength_signal) + (0.08 * form_signal) + (0.20 * trend_signal),
        0.18,
        0.82,
    )
    draw_drag = _clamp((draw_probability - 0.22) * 0.6, 0.0, 0.08)
    home_expected_goals = _clamp((total_goals * home_share) - draw_drag, 0.2, 3.6)
    away_expected_goals = _clamp(total_goals - home_expected_goals - draw_drag, 0.2, 3.6)

    return {
        "home_two_plus_probability": _poisson_two_plus_probability(home_expected_goals),
        "away_two_plus_probability": _poisson_two_plus_probability(away_expected_goals),
        "home_clean_sheet_probability": _poisson_zero_probability(away_expected_goals),
        "away_clean_sheet_probability": _poisson_zero_probability(home_expected_goals),
    }


def _latest_snapshot(session: Session, fixture_id: int) -> OddsSnapshot | None:
    return (
        session.query(OddsSnapshot)
        .filter_by(fixture_id=fixture_id)
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )


def _schedule_line_response(snap: OddsSnapshot | None) -> ScheduleLineResponse | None:
    if snap is None:
        return None
    return ScheduleLineResponse(
        home_odds=snap.home_odds,
        draw_odds=snap.draw_odds,
        away_odds=snap.away_odds,
        spread_home_line=snap.spread_home_line,
        spread_home_odds=snap.spread_home_odds,
        spread_away_line=snap.spread_away_line,
        spread_away_odds=snap.spread_away_odds,
        total_goals_line=snap.total_goals_line,
        over_odds=snap.over_odds,
        under_odds=snap.under_odds,
        bookmaker=snap.bookmaker,
        captured_at=snap.captured_at,
    )


@router.get("/schedule", response_model=list[ScheduledFixtureResponse])
def fixture_schedule(session: Session = Depends(get_session), days: int | None = None):
    now = datetime.now(timezone.utc)
    query = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.kickoff_at >= now)
    )
    if days is not None:
        query = query.filter(Fixture.kickoff_at <= now + timedelta(days=days))
    fixtures = query.order_by(Fixture.kickoff_at.asc()).all()

    team_ids = {fixture.home_team_id for fixture in fixtures} | {fixture.away_team_id for fixture in fixtures}
    league_ids = {fixture.league_id for fixture in fixtures}
    teams = {team.id: team.name for team in session.query(Team).filter(Team.id.in_(team_ids)).all()} if team_ids else {}
    leagues = {league.id: league.name for league in session.query(League).filter(League.id.in_(league_ids)).all()} if league_ids else {}
    league_espn_ids = {league.id: league.espn_id for league in session.query(League).filter(League.id.in_(league_ids)).all()} if league_ids else {}
    league_espn_ids = {league.id: league.espn_id for league in session.query(League).filter(League.id.in_(league_ids)).all()} if league_ids else {}

    response: list[ScheduledFixtureResponse] = []
    for fixture in fixtures:
        response.append(
            ScheduledFixtureResponse(
                fixture_id=fixture.id,
                home_team=teams.get(fixture.home_team_id, "Unknown"),
                away_team=teams.get(fixture.away_team_id, "Unknown"),
                league=leagues.get(fixture.league_id, "Unknown"),
                kickoff_at=fixture.kickoff_at,
                lines=_schedule_line_response(_latest_snapshot(session, fixture.id)),
            )
        )
    return response


@router.get("/status", response_model=DashboardStatusResponse)
def fixture_status(session: Session = Depends(get_session)):
    prediction_timestamps = [
        session.query(func.max(SpreadPrediction.created_at)).scalar(),
        session.query(func.max(OUAnalysis.created_at)).scalar(),
        session.query(func.max(MoneylinePrediction.created_at)).scalar(),
        session.query(func.max(EloFormPrediction.created_at)).scalar(),
    ]
    latest_prediction_at = max((value for value in prediction_timestamps if value is not None), default=None)
    latest_odds_at = session.query(func.max(OddsSnapshot.captured_at)).scalar()
    latest_result_at = session.query(func.max(Result.verified_at)).scalar()
    latest_manual_pick_at = session.query(func.max(ManualPick.created_at)).scalar()

    return DashboardStatusResponse(
        latest_prediction_at=latest_prediction_at,
        latest_odds_at=latest_odds_at,
        latest_result_at=latest_result_at,
        latest_manual_pick_at=latest_manual_pick_at,
        refreshed_at=datetime.now(timezone.utc),
    )


@router.get("/schedule/bully", response_model=list[EloFormScheduleResponse])
def fixture_bully_schedule(
    session: Session = Depends(get_session),
    days: int | None = None,
    use_xg_overlay: bool = True,
):
    now = datetime.now(timezone.utc)
    query = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.kickoff_at >= now)
    )
    if days is not None:
        query = query.filter(Fixture.kickoff_at <= now + timedelta(days=days))
    fixtures = query.order_by(Fixture.kickoff_at.asc()).all()

    team_ids = {fixture.home_team_id for fixture in fixtures} | {fixture.away_team_id for fixture in fixtures}
    league_ids = {fixture.league_id for fixture in fixtures}
    teams = {team.id: team.name for team in session.query(Team).filter(Team.id.in_(team_ids)).all()} if team_ids else {}
    leagues = {league.id: league.name for league in session.query(League).filter(League.id.in_(league_ids)).all()} if league_ids else {}
    league_espn_ids = {league.id: league.espn_id for league in session.query(League).filter(League.id.in_(league_ids)).all()} if league_ids else {}

    response: list[EloFormScheduleResponse] = []
    for fixture in fixtures:
        prediction = (
            session.query(EloFormPrediction, ModelVersion)
            .join(ModelVersion, ModelVersion.id == EloFormPrediction.model_id)
            .filter(EloFormPrediction.fixture_id == fixture.id)
            .filter(ModelVersion.active.is_(True))
            .order_by(ModelVersion.created_at.desc(), EloFormPrediction.created_at.desc())
            .first()
        )
        if prediction is None:
            continue

        pred, model = prediction
        home_team = teams.get(fixture.home_team_id, "Unknown")
        away_team = teams.get(fixture.away_team_id, "Unknown")
        favorite_team = home_team if pred.favorite_side == "home" else away_team
        underdog_side = "away" if pred.favorite_side == "home" else "home"
        underdog_team = away_team if pred.favorite_side == "home" else home_team
        favorite_probability = pred.home_probability if pred.favorite_side == "home" else pred.away_probability
        underdog_probability = pred.away_probability if pred.favorite_side == "home" else pred.home_probability
        avg_home_goals, avg_away_goals, _ = fit_league_goal_rates(session, fixture.league_id, fixture.kickoff_at)
        goals = project_match_goal_probs(
            home_probability=pred.home_probability,
            draw_probability=pred.draw_probability,
            away_probability=pred.away_probability,
            home_form_for_avg=pred.home_form_for_avg,
            home_form_against_avg=pred.home_form_against_avg,
            away_form_for_avg=pred.away_form_for_avg,
            away_form_against_avg=pred.away_form_against_avg,
            home_xg_diff_avg=pred.home_xg_diff_avg,
            away_xg_diff_avg=pred.away_xg_diff_avg,
            home_xg_trend=pred.home_xg_trend,
            away_xg_trend=pred.away_xg_trend,
            league_avg_home_goals=avg_home_goals,
            league_avg_away_goals=avg_away_goals,
        )
        favorite_two_plus_probability = (
            goals.home_two_plus_probability if pred.favorite_side == "home" else goals.away_two_plus_probability
        )
        underdog_two_plus_probability = (
            goals.away_two_plus_probability if pred.favorite_side == "home" else goals.home_two_plus_probability
        )
        favorite_expected_goals = (
            goals.home_expected_goals if pred.favorite_side == "home" else goals.away_expected_goals
        )
        underdog_expected_goals = (
            goals.away_expected_goals if pred.favorite_side == "home" else goals.home_expected_goals
        )
        favorite_clean_sheet_probability = (
            goals.home_clean_sheet_probability if pred.favorite_side == "home" else goals.away_clean_sheet_probability
        )
        underdog_clean_sheet_probability = (
            goals.away_clean_sheet_probability if pred.favorite_side == "home" else goals.home_clean_sheet_probability
        )
        expected_goals_delta = favorite_expected_goals - underdog_expected_goals
        is_bully_spot = (pred.elo_gap >= DEFAULT_BULLY_GAP_THRESHOLD) and passes_bully_xg_overlay(
            league_espn_ids.get(fixture.league_id, ""),
            expected_goals_delta,
            enabled=use_xg_overlay,
        )

        response.append(
            EloFormScheduleResponse(
                fixture_id=fixture.id,
                home_team=home_team,
                away_team=away_team,
                league=leagues.get(fixture.league_id, "Unknown"),
                kickoff_at=fixture.kickoff_at,
                model_name=model.name,
                model_version=model.version,
                favorite_side=pred.favorite_side,
                underdog_side=underdog_side,
                favorite_team=favorite_team,
                underdog_team=underdog_team,
                elo_gap=pred.elo_gap,
                is_bully_spot=is_bully_spot,
                home_elo=pred.home_elo,
                away_elo=pred.away_elo,
                home_probability=pred.home_probability,
                draw_probability=pred.draw_probability,
                away_probability=pred.away_probability,
                home_expected_goals=goals.home_expected_goals,
                away_expected_goals=goals.away_expected_goals,
                home_two_plus_probability=goals.home_two_plus_probability,
                away_two_plus_probability=goals.away_two_plus_probability,
                home_clean_sheet_probability=goals.home_clean_sheet_probability,
                away_clean_sheet_probability=goals.away_clean_sheet_probability,
                favorite_probability=favorite_probability,
                underdog_probability=underdog_probability,
                favorite_expected_goals=favorite_expected_goals,
                underdog_expected_goals=underdog_expected_goals,
                expected_goals_delta=expected_goals_delta,
                favorite_two_plus_probability=favorite_two_plus_probability,
                underdog_two_plus_probability=underdog_two_plus_probability,
                favorite_clean_sheet_probability=favorite_clean_sheet_probability,
                underdog_clean_sheet_probability=underdog_clean_sheet_probability,
                home_xg_diff_avg=pred.home_xg_diff_avg,
                away_xg_diff_avg=pred.away_xg_diff_avg,
                home_xg_trend=pred.home_xg_trend,
                away_xg_trend=pred.away_xg_trend,
                trend_adjustment=pred.trend_adjustment,
                lines=_schedule_line_response(_latest_snapshot(session, fixture.id)),
            )
        )

    response.sort(
        key=lambda row: (
            not row.is_bully_spot,
            -row.elo_gap,
            -row.favorite_probability,
            row.kickoff_at,
        )
    )
    return response


@router.get("/{fixture_id:int}", response_model=FixtureDetailResponse)
def fixture_detail(fixture_id: int, session: Session = Depends(get_session)):
    fixture = session.query(Fixture).filter_by(id=fixture_id).first()
    if not fixture:
        raise HTTPException(status_code=404, detail="Fixture not found")

    home_team = session.query(Team).filter_by(id=fixture.home_team_id).first()
    away_team = session.query(Team).filter_by(id=fixture.away_team_id).first()
    league = session.query(League).filter_by(id=fixture.league_id).first()

    home_fc = session.query(FormCache).filter_by(team_id=fixture.home_team_id, is_home=True).first()
    away_fc = session.query(FormCache).filter_by(team_id=fixture.away_team_id, is_home=False).first()

    spread_rows = (
        session.query(SpreadPrediction)
        .filter_by(fixture_id=fixture_id)
        .order_by(SpreadPrediction.goal_line)
        .all()
    )
    ou_rows = (
        session.query(OUAnalysis)
        .filter_by(fixture_id=fixture_id)
        .order_by(OUAnalysis.line)
        .all()
    )

    return FixtureDetailResponse(
        fixture_id=fixture.id,
        home_team=home_team.name if home_team else "Unknown",
        away_team=away_team.name if away_team else "Unknown",
        league=league.name if league else "Unknown",
        kickoff_at=fixture.kickoff_at,
        home_form=FormSummary(
            goals_scored_avg=home_fc.goals_scored_avg,
            goals_conceded_avg=home_fc.goals_conceded_avg,
            spread_cover_rate=home_fc.spread_cover_rate,
            ou_hit_rate_25=home_fc.ou_hit_rate_25,
            matches_count=home_fc.matches_count,
        ) if home_fc else None,
        away_form=FormSummary(
            goals_scored_avg=away_fc.goals_scored_avg,
            goals_conceded_avg=away_fc.goals_conceded_avg,
            spread_cover_rate=away_fc.spread_cover_rate,
            ou_hit_rate_25=away_fc.ou_hit_rate_25,
            matches_count=away_fc.matches_count,
        ) if away_fc else None,
        spread_picks=[
            SpreadPickResponse(
                team_side=s.team_side,
                goal_line=s.goal_line,
                cover_probability=s.cover_probability,
                push_probability=s.push_probability or 0.0,
                ev_score=s.ev_score,
                confidence_tier=s.confidence_tier,
            ) for s in spread_rows
        ],
        ou_picks=[
            OUPickResponse(
                line=o.line,
                direction=o.direction,
                probability=o.probability,
                ev_score=o.ev_score,
                confidence_tier=o.confidence_tier,
            ) for o in ou_rows
        ],
    )
