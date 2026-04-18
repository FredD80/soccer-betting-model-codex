from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from api.routers.picks import _picks_in_window
from app.db.models import (
    Fixture,
    League,
    ManualPick,
    ModelVersion,
    OddsSnapshot,
    Team,
    WeeklyModelPick,
    EloFormPrediction,
)
from app.tracker import decimal_to_american


MODEL_VIEW_LABELS = {
    "main": "Alpha",
    "parallel": "Market-Edge",
    "bully": "Bully-Model",
}


@dataclass(frozen=True)
class SnapshotCandidate:
    fixture_id: int
    league_id: int
    home_team_id: int
    away_team_id: int
    kickoff_at: datetime
    model_id: int | None
    market_type: str
    selection: str
    line: float | None
    decimal_odds: float | None
    american_odds: int | None
    model_probability: float | None
    final_probability: float | None
    edge_pct: float | None
    confidence_tier: str | None


def season_key_for_date(value: date) -> str:
    if value.month >= 8:
        return f"{value.year}-{str(value.year + 1)[-2:]}"
    return f"{value.year - 1}-{str(value.year)[-2:]}"


def season_bounds(season_key: str) -> tuple[datetime, datetime]:
    start_year = int(season_key.split("-")[0])
    start = datetime(start_year, 8, 1, tzinfo=timezone.utc)
    end = datetime(start_year + 1, 7, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end


def current_week_start(now: datetime | None = None) -> date:
    current = (now or datetime.now(timezone.utc)).date()
    return current - timedelta(days=current.weekday())


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=7) - timedelta(microseconds=1)
    return start_dt, end_dt


def ensure_current_week_model_snapshots(session) -> None:
    today = datetime.now(timezone.utc).date()
    season_key = season_key_for_date(today)
    snapshot_model_week(session, season_key=season_key, week_start=current_week_start())


def snapshot_model_week(session, *, season_key: str, week_start: date) -> int:
    created = 0
    for model_view in ("main", "parallel", "bully"):
        existing = (
            session.query(WeeklyModelPick)
            .filter_by(season_key=season_key, week_start=week_start, model_view=model_view)
            .count()
        )
        if existing:
            continue
        candidates = build_weekly_candidates(session, model_view=model_view, week_start=week_start)
        selected_candidates = _select_unique_team_candidates(candidates, limit=5)
        for rank, candidate in enumerate(selected_candidates, start=1):
            session.add(
                WeeklyModelPick(
                    season_key=season_key,
                    week_start=week_start,
                    model_view=model_view,
                    model_label=MODEL_VIEW_LABELS[model_view],
                    rank=rank,
                    fixture_id=candidate.fixture_id,
                    model_id=candidate.model_id,
                    market_type=candidate.market_type,
                    selection=candidate.selection,
                    line=candidate.line,
                    decimal_odds=candidate.decimal_odds,
                    american_odds=candidate.american_odds,
                    model_probability=candidate.model_probability,
                    final_probability=candidate.final_probability,
                    edge_pct=candidate.edge_pct,
                    confidence_tier=candidate.confidence_tier,
                    result_status="open",
                    created_at=datetime.now(timezone.utc),
                )
            )
            created += 1
    session.commit()
    return created


def build_weekly_candidates(session, *, model_view: str, week_start: date) -> list[SnapshotCandidate]:
    return (
        _build_bully_candidates(session, week_start)
        if model_view == "bully"
        else _build_standard_candidates(session, model_view=model_view, week_start=week_start)
    )


def _build_standard_candidates(session, *, model_view: str, week_start: date) -> list[SnapshotCandidate]:
    start_dt, end_dt = week_bounds(week_start)
    fixture_picks = _picks_in_window(session, start_dt, end_dt, model_view=model_view)
    fixture_ids = [fixture_pick.fixture_id for fixture_pick in fixture_picks]
    fixtures = {
        fixture.id: fixture
        for fixture in session.query(Fixture).filter(Fixture.id.in_(fixture_ids)).all()
    }
    candidates: list[SnapshotCandidate] = []
    for fixture_pick in fixture_picks:
        fixture = fixtures.get(fixture_pick.fixture_id)
        if fixture is None:
            continue
        best_pick = _best_fixture_candidate(session, fixture_pick, fixture)
        if best_pick is not None:
            candidates.append(best_pick)
    return candidates


def _best_fixture_candidate(session, fixture_pick, fixture: Fixture) -> SnapshotCandidate | None:
    options = []
    if fixture_pick.best_spread is not None:
        options.append(
            (
                fixture_pick.best_spread.ev_score if fixture_pick.best_spread.ev_score is not None else float("-inf"),
                fixture_pick.best_spread.final_probability if fixture_pick.best_spread.final_probability is not None else float("-inf"),
                SnapshotCandidate(
                    fixture_id=fixture_pick.fixture_id,
                    league_id=fixture.league_id,
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    kickoff_at=fixture.kickoff_at,
                    model_id=_model_id(session, fixture_pick.best_spread.model_name, fixture_pick.best_spread.model_version),
                    market_type="spread",
                    selection=fixture_pick.best_spread.team_side,
                    line=fixture_pick.best_spread.goal_line,
                    decimal_odds=fixture_pick.best_spread.decimal_odds,
                    american_odds=fixture_pick.best_spread.american_odds,
                    model_probability=fixture_pick.best_spread.cover_probability,
                    final_probability=fixture_pick.best_spread.final_probability,
                    edge_pct=fixture_pick.best_spread.edge_pct,
                    confidence_tier=fixture_pick.best_spread.confidence_tier,
                ),
            )
        )
    if fixture_pick.best_ou is not None:
        options.append(
            (
                fixture_pick.best_ou.ev_score if fixture_pick.best_ou.ev_score is not None else float("-inf"),
                fixture_pick.best_ou.final_probability if fixture_pick.best_ou.final_probability is not None else float("-inf"),
                SnapshotCandidate(
                    fixture_id=fixture_pick.fixture_id,
                    league_id=fixture.league_id,
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    kickoff_at=fixture.kickoff_at,
                    model_id=_model_id(session, fixture_pick.best_ou.model_name, fixture_pick.best_ou.model_version),
                    market_type="ou",
                    selection=fixture_pick.best_ou.direction,
                    line=fixture_pick.best_ou.line,
                    decimal_odds=fixture_pick.best_ou.decimal_odds,
                    american_odds=fixture_pick.best_ou.american_odds,
                    model_probability=fixture_pick.best_ou.probability,
                    final_probability=fixture_pick.best_ou.final_probability,
                    edge_pct=fixture_pick.best_ou.edge_pct,
                    confidence_tier=fixture_pick.best_ou.confidence_tier,
                ),
            )
        )
    if fixture_pick.best_moneyline is not None:
        options.append(
            (
                fixture_pick.best_moneyline.ev_score if fixture_pick.best_moneyline.ev_score is not None else float("-inf"),
                fixture_pick.best_moneyline.final_probability if fixture_pick.best_moneyline.final_probability is not None else float("-inf"),
                SnapshotCandidate(
                    fixture_id=fixture_pick.fixture_id,
                    league_id=fixture.league_id,
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    kickoff_at=fixture.kickoff_at,
                    model_id=_model_id(
                        session,
                        fixture_pick.best_moneyline.model_name,
                        fixture_pick.best_moneyline.model_version,
                    ),
                    market_type="moneyline",
                    selection=fixture_pick.best_moneyline.outcome,
                    line=None,
                    decimal_odds=fixture_pick.best_moneyline.decimal_odds,
                    american_odds=fixture_pick.best_moneyline.american_odds,
                    model_probability=fixture_pick.best_moneyline.probability,
                    final_probability=fixture_pick.best_moneyline.final_probability,
                    edge_pct=fixture_pick.best_moneyline.edge_pct,
                    confidence_tier=fixture_pick.best_moneyline.confidence_tier,
                ),
            )
        )
    if not options:
        return None
    _, _, candidate = max(options, key=lambda item: (item[0], item[1]))
    return candidate


def _build_bully_candidates(session, week_start: date) -> list[SnapshotCandidate]:
    start_dt, end_dt = week_bounds(week_start)
    fixtures = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.kickoff_at >= start_dt)
        .filter(Fixture.kickoff_at <= end_dt)
        .order_by(Fixture.kickoff_at.asc())
        .all()
    )

    candidates: list[tuple[tuple, SnapshotCandidate]] = []
    for fixture in fixtures:
        row = (
            session.query(EloFormPrediction, ModelVersion)
            .join(ModelVersion, ModelVersion.id == EloFormPrediction.model_id)
            .filter(EloFormPrediction.fixture_id == fixture.id)
            .filter(ModelVersion.active.is_(True))
            .order_by(ModelVersion.created_at.desc(), EloFormPrediction.created_at.desc())
            .first()
        )
        if row is None:
            continue
        pred, model = row
        if not pred.is_bully_spot:
            continue
        model_probability = pred.home_probability if pred.favorite_side == "home" else pred.away_probability
        decimal_odds = _moneyline_odds(session, fixture.id, pred.favorite_side)
        edge_pct = None if decimal_odds is None else model_probability - (1.0 / decimal_odds)
        candidate = SnapshotCandidate(
            fixture_id=fixture.id,
            league_id=fixture.league_id,
            home_team_id=fixture.home_team_id,
            away_team_id=fixture.away_team_id,
            kickoff_at=fixture.kickoff_at,
            model_id=model.id,
            market_type="moneyline",
            selection=pred.favorite_side,
            line=None,
            decimal_odds=decimal_odds,
            american_odds=decimal_to_american(decimal_odds),
            model_probability=model_probability,
            final_probability=model_probability,
            edge_pct=edge_pct,
            confidence_tier=_bully_confidence_tier(pred.is_bully_spot, model_probability),
        )
        candidates.append(((-pred.elo_gap, -model_probability, fixture.kickoff_at), candidate))

    candidates.sort(key=lambda item: item[0])
    return [candidate for _, candidate in candidates]


def _select_unique_team_candidates(candidates: list[SnapshotCandidate], *, limit: int) -> list[SnapshotCandidate]:
    selected: list[SnapshotCandidate] = []
    seen_team_ids: set[int] = set()
    for candidate in candidates:
        if candidate.home_team_id in seen_team_ids or candidate.away_team_id in seen_team_ids:
            continue
        selected.append(candidate)
        seen_team_ids.add(candidate.home_team_id)
        seen_team_ids.add(candidate.away_team_id)
        if len(selected) >= limit:
            break
    return selected


def grouped_manual_picks_for_season(session, *, season_key: str) -> dict[date, list[ManualPick]]:
    start_dt, end_dt = season_bounds(season_key)
    rows = (
        session.query(ManualPick, Fixture)
        .join(Fixture, Fixture.id == ManualPick.fixture_id)
        .filter(Fixture.kickoff_at >= start_dt)
        .filter(Fixture.kickoff_at <= end_dt)
        .order_by(Fixture.kickoff_at.desc(), ManualPick.created_at.desc())
        .all()
    )
    grouped: dict[date, list[ManualPick]] = defaultdict(list)
    for pick, fixture in rows:
        grouped[_week_start_for_kickoff(fixture.kickoff_at)].append(pick)
    return grouped


def weekly_model_picks_for_season(session, *, season_key: str) -> list[WeeklyModelPick]:
    return (
        session.query(WeeklyModelPick)
        .filter(WeeklyModelPick.season_key == season_key)
        .order_by(WeeklyModelPick.week_start.desc(), WeeklyModelPick.model_view.asc(), WeeklyModelPick.rank.asc())
        .all()
    )


def _week_start_for_kickoff(kickoff_at: datetime) -> date:
    kickoff_date = kickoff_at.astimezone(timezone.utc).date() if kickoff_at.tzinfo else kickoff_at.date()
    return kickoff_date - timedelta(days=kickoff_date.weekday())


def _moneyline_odds(session, fixture_id: int, selection: str) -> float | None:
    snap = (
        session.query(OddsSnapshot)
        .filter_by(fixture_id=fixture_id)
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )
    if snap is None:
        return None
    return {"home": snap.home_odds, "draw": snap.draw_odds, "away": snap.away_odds}.get(selection)


def _model_id(session, model_name: str | None, model_version: str | None) -> int | None:
    if model_name is None or model_version is None:
        return None
    row = (
        session.query(ModelVersion)
        .filter_by(name=model_name, version=model_version)
        .order_by(ModelVersion.created_at.desc())
        .first()
    )
    return row.id if row else None


def _bully_confidence_tier(is_bully_spot: bool, model_probability: float) -> str:
    if is_bully_spot and model_probability >= 0.68:
        return "ELITE"
    if is_bully_spot or model_probability >= 0.60:
        return "HIGH"
    return "MEDIUM"


def fixture_context_map(session, fixture_ids: set[int]) -> dict[int, dict[str, object]]:
    if not fixture_ids:
        return {}
    fixtures = session.query(Fixture).filter(Fixture.id.in_(fixture_ids)).all()
    team_ids = {fixture.home_team_id for fixture in fixtures} | {fixture.away_team_id for fixture in fixtures}
    league_ids = {fixture.league_id for fixture in fixtures}
    teams = {team.id: team.name for team in session.query(Team).filter(Team.id.in_(team_ids)).all()}
    leagues = {league.id: league.name for league in session.query(League).filter(League.id.in_(league_ids)).all()}
    return {
        fixture.id: {
            "home_team": teams.get(fixture.home_team_id, "Unknown"),
            "away_team": teams.get(fixture.away_team_id, "Unknown"),
            "league": leagues.get(fixture.league_id, "Unknown"),
            "kickoff_at": fixture.kickoff_at,
        }
        for fixture in fixtures
    }
