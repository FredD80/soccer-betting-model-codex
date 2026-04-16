from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.models import (
    Fixture, League, Team, FormCache,
    SpreadPrediction, OUAnalysis, OddsSnapshot
)
from api.deps import get_session
from api.schemas import (
    FixtureDetailResponse, FormSummary,
    SpreadPickResponse, OUPickResponse, ScheduledFixtureResponse, ScheduleLineResponse
)
from datetime import datetime, timedelta, timezone

router = APIRouter()


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

    response: list[ScheduledFixtureResponse] = []
    for fixture in fixtures:
        snap = (
            session.query(OddsSnapshot)
            .filter_by(fixture_id=fixture.id)
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )
        lines = None
        if snap:
            lines = ScheduleLineResponse(
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
        response.append(
            ScheduledFixtureResponse(
                fixture_id=fixture.id,
                home_team=teams.get(fixture.home_team_id, "Unknown"),
                away_team=teams.get(fixture.away_team_id, "Unknown"),
                league=leagues.get(fixture.league_id, "Unknown"),
                kickoff_at=fixture.kickoff_at,
                lines=lines,
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
