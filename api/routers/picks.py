from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.models import (
    Fixture, League, Team, SpreadPrediction, OUAnalysis, OddsSnapshot,
    MoneylinePrediction,
)
from api.deps import get_session
from api.schemas import (
    FixturePickResponse, SpreadPickResponse, OUPickResponse, MoneylinePickResponse,
)

router = APIRouter()

_TIER_PRIORITY = {
    "ELITE": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "SKIP": 3,
}


def _to_american(decimal_odds: float | None) -> int | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1.0) * 100))
    return int(round(-100.0 / (decimal_odds - 1.0)))


def _spread_odds(session: Session, fixture_id: int, team_side: str, line: float) -> float | None:
    q = session.query(OddsSnapshot).filter_by(fixture_id=fixture_id)
    if team_side == "home":
        q = q.filter(OddsSnapshot.spread_home_line == line,
                     OddsSnapshot.spread_home_odds.isnot(None))
        snap = q.order_by(OddsSnapshot.captured_at.desc()).first()
        return snap.spread_home_odds if snap else None
    q = q.filter(OddsSnapshot.spread_away_line == line,
                 OddsSnapshot.spread_away_odds.isnot(None))
    snap = q.order_by(OddsSnapshot.captured_at.desc()).first()
    return snap.spread_away_odds if snap else None


def _ou_odds(session: Session, fixture_id: int, line: float, direction: str) -> float | None:
    col = OddsSnapshot.over_odds if direction == "over" else OddsSnapshot.under_odds
    snap = (
        session.query(OddsSnapshot)
        .filter_by(fixture_id=fixture_id)
        .filter(OddsSnapshot.total_goals_line == line)
        .filter(col.isnot(None))
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )
    if not snap:
        return None
    return snap.over_odds if direction == "over" else snap.under_odds


def _team_name(session: Session, team_id: int) -> str:
    t = session.query(Team).filter_by(id=team_id).first()
    return t.name if t else "Unknown"


def _league_name(session: Session, league_id: int) -> str:
    lg = session.query(League).filter_by(id=league_id).first()
    return lg.name if lg else "Unknown"


def _is_us_style_line(line: float) -> bool:
    """Accept half/whole goal lines (±0.5, ±1.0, ±1.5...); reject quarter Asian (±0.25, ±0.75)."""
    return abs(round(line * 2) - line * 2) < 1e-6


def _best_spread(session: Session, fixture_id: int) -> SpreadPickResponse | None:
    picks = (
        session.query(SpreadPrediction)
        .filter(SpreadPrediction.fixture_id == fixture_id)
        .order_by(SpreadPrediction.ev_score.desc())
        .all()
    )
    picks = next((p for p in picks if _is_us_style_line(p.goal_line)), None)
    if not picks:
        return None
    dec = _spread_odds(session, fixture_id, picks.team_side, picks.goal_line)

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
        decimal_odds=dec,
        american_odds=_to_american(dec),
    )


def _best_ou(session: Session, fixture_id: int) -> OUPickResponse | None:
    pick = (
        session.query(OUAnalysis)
        .filter(OUAnalysis.fixture_id == fixture_id)
        .order_by(OUAnalysis.ev_score.desc())
        .first()
    )
    if not pick:
        return None
    dec = _ou_odds(session, fixture_id, pick.line, pick.direction)
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
        decimal_odds=dec,
        american_odds=_to_american(dec),
    )


def _ml_odds(session: Session, fixture_id: int, outcome: str) -> float | None:
    snap = (
        session.query(OddsSnapshot)
        .filter_by(fixture_id=fixture_id)
        .filter(OddsSnapshot.home_odds.isnot(None))
        .filter(OddsSnapshot.away_odds.isnot(None))
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )
    if not snap:
        return None
    return {"home": snap.home_odds, "draw": snap.draw_odds, "away": snap.away_odds}[outcome]


def _best_moneyline(session: Session, fixture_id: int) -> MoneylinePickResponse | None:
    pick = (
        session.query(MoneylinePrediction)
        .filter(MoneylinePrediction.fixture_id == fixture_id)
        .order_by(MoneylinePrediction.ev_score.desc())
        .first()
    )
    if not pick:
        return None
    dec = _ml_odds(session, fixture_id, pick.outcome)
    return MoneylinePickResponse(
        outcome=pick.outcome,
        probability=pick.probability,
        ev_score=pick.ev_score,
        confidence_tier=pick.confidence_tier,
        final_probability=pick.final_probability,
        edge_pct=pick.edge_pct,
        kelly_fraction=pick.kelly_fraction,
        steam_downgraded=bool(pick.steam_downgraded),
        decimal_odds=dec,
        american_odds=_to_american(dec),
    )


def _fixture_tier_rank(fixture_pick: FixturePickResponse) -> int:
    tiers = [
        pick.confidence_tier
        for pick in (fixture_pick.best_spread, fixture_pick.best_ou, fixture_pick.best_moneyline)
        if pick
    ]
    if not tiers:
        return len(_TIER_PRIORITY)
    return min(_TIER_PRIORITY.get(tier, len(_TIER_PRIORITY)) for tier in tiers)


def _build_fixture_pick(session: Session, fixture: Fixture) -> FixturePickResponse:
    spread = _best_spread(session, fixture.id)
    ou = _best_ou(session, fixture.id)
    ml = _best_moneyline(session, fixture.id)
    evs = [p.ev_score for p in (spread, ou, ml) if p and p.ev_score is not None]
    top_ev = max(evs) if evs else None
    return FixturePickResponse(
        fixture_id=fixture.id,
        home_team=_team_name(session, fixture.home_team_id),
        away_team=_team_name(session, fixture.away_team_id),
        league=_league_name(session, fixture.league_id),
        kickoff_at=fixture.kickoff_at,
        best_spread=spread,
        best_ou=ou,
        best_moneyline=ml,
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
    picks = [_build_fixture_pick(session, fixture) for fixture in fixtures]
    return sorted(
        picks,
        key=lambda pick: (
            _fixture_tier_rank(pick),
            -(pick.top_ev or float("-inf")),
            pick.kickoff_at,
        ),
    )


def _league_picks_in_window(
    session: Session,
    league_espn_id: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[FixturePickResponse]:
    league = session.query(League).filter_by(espn_id=league_espn_id).first()
    if not league:
        return []
    fixtures = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.league_id == league.id)
        .filter(Fixture.kickoff_at >= from_dt)
        .filter(Fixture.kickoff_at <= to_dt)
        .all()
    )
    picks = [_build_fixture_pick(session, fixture) for fixture in fixtures]
    return sorted(
        picks,
        key=lambda pick: (
            _fixture_tier_rank(pick),
            -(pick.top_ev or float("-inf")),
            pick.kickoff_at,
        ),
    )


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
    return _league_picks_in_window(session, "uefa.champions", now, end)


@router.get("/league/{league_espn_id}", response_model=list[FixturePickResponse])
def picks_by_league(league_espn_id: str, session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    return _league_picks_in_window(session, league_espn_id, now, end)
