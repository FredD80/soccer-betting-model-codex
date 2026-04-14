from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.models import (
    Fixture, League, Team, SpreadPrediction, OUAnalysis
)
from api.deps import get_session
from api.schemas import FixturePickResponse, SpreadPickResponse, OUPickResponse

router = APIRouter()

_SHOW_TIERS = {"HIGH", "ELITE"}


def _team_name(session: Session, team_id: int) -> str:
    t = session.query(Team).filter_by(id=team_id).first()
    return t.name if t else "Unknown"


def _league_name(session: Session, league_id: int) -> str:
    lg = session.query(League).filter_by(id=league_id).first()
    return lg.name if lg else "Unknown"


def _best_spread(session: Session, fixture_id: int) -> SpreadPickResponse | None:
    picks = (
        session.query(SpreadPrediction)
        .filter(SpreadPrediction.fixture_id == fixture_id)
        .filter(SpreadPrediction.confidence_tier.in_(_SHOW_TIERS))
        .order_by(SpreadPrediction.ev_score.desc())
        .first()
    )
    if not picks:
        return None
    return SpreadPickResponse(
        team_side=picks.team_side,
        goal_line=picks.goal_line,
        cover_probability=picks.cover_probability,
        push_probability=picks.push_probability or 0.0,
        ev_score=picks.ev_score,
        confidence_tier=picks.confidence_tier,
        final_probability=picks.final_probability,
        edge_pct=picks.edge_pct,
        kelly_fraction=picks.kelly_fraction,
        steam_downgraded=bool(picks.steam_downgraded),
    )


def _best_ou(session: Session, fixture_id: int) -> OUPickResponse | None:
    pick = (
        session.query(OUAnalysis)
        .filter(OUAnalysis.fixture_id == fixture_id)
        .filter(OUAnalysis.confidence_tier.in_(_SHOW_TIERS))
        .order_by(OUAnalysis.ev_score.desc())
        .first()
    )
    if not pick:
        return None
    return OUPickResponse(
        line=pick.line,
        direction=pick.direction,
        probability=pick.probability,
        ev_score=pick.ev_score,
        confidence_tier=pick.confidence_tier,
        final_probability=pick.final_probability,
        edge_pct=pick.edge_pct,
        kelly_fraction=pick.kelly_fraction,
        steam_downgraded=bool(pick.steam_downgraded),
    )


def _build_fixture_pick(session: Session, fixture: Fixture) -> FixturePickResponse | None:
    spread = _best_spread(session, fixture.id)
    ou = _best_ou(session, fixture.id)
    if not spread and not ou:
        return None
    spread_ev = spread.ev_score if spread else None
    ou_ev = ou.ev_score if ou else None
    top_ev = max(e for e in (spread_ev, ou_ev) if e is not None) if (spread_ev or ou_ev) else None
    return FixturePickResponse(
        fixture_id=fixture.id,
        home_team=_team_name(session, fixture.home_team_id),
        away_team=_team_name(session, fixture.away_team_id),
        league=_league_name(session, fixture.league_id),
        kickoff_at=fixture.kickoff_at,
        best_spread=spread,
        best_ou=ou,
        top_ev=top_ev,
    )


def _picks_in_window(session: Session, from_dt: datetime, to_dt: datetime) -> list[FixturePickResponse]:
    fixtures = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.kickoff_at >= from_dt)
        .filter(Fixture.kickoff_at <= to_dt)
        .all()
    )
    picks = []
    for f in fixtures:
        p = _build_fixture_pick(session, f)
        if p:
            picks.append(p)
    return sorted(picks, key=lambda p: p.top_ev or 0.0, reverse=True)


@router.get("/today", response_model=list[FixturePickResponse])
def picks_today(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    return _picks_in_window(session, now, end)


@router.get("/week", response_model=list[FixturePickResponse])
def picks_week(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    return _picks_in_window(session, now, end)


@router.get("/ucl", response_model=list[FixturePickResponse])
def picks_ucl(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    ucl_league = session.query(League).filter_by(espn_id="uefa.champions").first()
    if not ucl_league:
        return []
    fixtures = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.league_id == ucl_league.id)
        .filter(Fixture.kickoff_at >= now)
        .filter(Fixture.kickoff_at <= end)
        .all()
    )
    picks = []
    for f in fixtures:
        p = _build_fixture_pick(session, f)
        if p:
            picks.append(p)
    return sorted(picks, key=lambda p: p.top_ev or 0.0, reverse=True)
