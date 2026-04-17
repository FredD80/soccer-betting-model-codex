from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.db.models import Performance, ModelVersion, PredictionOutcome, Fixture, League, Team, ManualPick
from api.deps import get_session
from api.schemas import (
    ModelPerformanceResponse,
    PredictionOutcomeResponse,
    PredictionOutcomeSummaryResponse,
    ManualPickCreateRequest,
    ManualPickResponse,
    ManualPickSummaryResponse,
    ManualVsModelComparisonResponse,
    ManualVsModelSummaryResponse,
    FixtureModelTopPickResponse,
    FixtureManualComparisonResponse,
)
from app.tracker import decimal_to_american

router = APIRouter()


@router.get("", response_model=list[ModelPerformanceResponse])
def model_performance(session: Session = Depends(get_session)):
    rows = session.query(Performance).all()
    result = []
    for row in rows:
        mv = session.query(ModelVersion).filter_by(id=row.model_id).first()
        result.append(ModelPerformanceResponse(
            model_name=mv.name if mv else "unknown",
            version=mv.version if mv else "unknown",
            bet_type=row.bet_type,
            total_predictions=row.total_predictions or 0,
            correct=row.correct or 0,
            accuracy=row.accuracy or 0.0,
            roi=row.roi or 0.0,
        ))
    return result


def _fixture_context(session: Session, fixture_id: int) -> tuple[str, str, str]:
    fixture = session.query(Fixture).filter_by(id=fixture_id).first()
    if fixture is None:
        return "Unknown", "Unknown", "Unknown"
    home = session.query(Team).filter_by(id=fixture.home_team_id).first()
    away = session.query(Team).filter_by(id=fixture.away_team_id).first()
    league = session.query(League).filter_by(id=fixture.league_id).first()
    return (
        home.name if home else "Unknown",
        away.name if away else "Unknown",
        league.name if league else "Unknown",
    )


def _american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def _valid_selection(market_type: str, selection: str) -> bool:
    allowed = {
        "moneyline": {"home", "draw", "away"},
        "spread": {"home", "away"},
        "ou": {"over", "under"},
    }
    return selection in allowed.get(market_type, set())


def _same_line(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < 1e-6


def _best_model_picks_for_fixture(session: Session, fixture_id: int) -> list[FixtureModelTopPickResponse]:
    rows = (
        session.query(PredictionOutcome)
        .filter(PredictionOutcome.fixture_id == fixture_id)
        .filter(PredictionOutcome.result_status.in_(("win", "loss", "push")))
        .all()
    )
    best_by_model: dict[int, PredictionOutcome] = {}
    for row in rows:
        current = best_by_model.get(row.model_id)
        if current is None:
            best_by_model[row.model_id] = row
            continue
        current_edge = current.edge_pct if current.edge_pct is not None else float("-inf")
        row_edge = row.edge_pct if row.edge_pct is not None else float("-inf")
        if row_edge > current_edge:
            best_by_model[row.model_id] = row
            continue
        if row_edge == current_edge:
            current_prob = current.final_probability if current.final_probability is not None else float("-inf")
            row_prob = row.final_probability if row.final_probability is not None else float("-inf")
            if row_prob > current_prob:
                best_by_model[row.model_id] = row

    response: list[FixtureModelTopPickResponse] = []
    for model_id, row in best_by_model.items():
        mv = session.query(ModelVersion).filter_by(id=model_id).first()
        response.append(FixtureModelTopPickResponse(
            model_name=mv.name if mv else "unknown",
            version=mv.version if mv else "unknown",
            market_type=row.market_type,
            selection=row.selection,
            line=row.line,
            result_status=row.result_status,
            profit_units=row.profit_units,
            model_probability=row.model_probability,
            final_probability=row.final_probability,
            edge_pct=row.edge_pct,
            confidence_tier=row.confidence_tier,
        ))
    return sorted(response, key=lambda item: (item.model_name, item.version))


@router.get("/outcomes", response_model=list[PredictionOutcomeResponse])
def settled_outcomes(
    market_type: str | None = None,
    confidence_tier: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    query = session.query(PredictionOutcome).filter(
        PredictionOutcome.result_status.in_(("win", "loss", "push"))
    )
    if market_type:
        query = query.filter(PredictionOutcome.market_type == market_type)
    if confidence_tier:
        query = query.filter(PredictionOutcome.confidence_tier == confidence_tier)
    rows = query.order_by(PredictionOutcome.graded_at.desc()).limit(limit).all()

    response: list[PredictionOutcomeResponse] = []
    for row in rows:
        mv = session.query(ModelVersion).filter_by(id=row.model_id).first()
        home_team, away_team, league = _fixture_context(session, row.fixture_id)
        response.append(PredictionOutcomeResponse(
            fixture_id=row.fixture_id,
            home_team=home_team,
            away_team=away_team,
            league=league,
            model_name=mv.name if mv else "unknown",
            version=mv.version if mv else "unknown",
            market_type=row.market_type,
            selection=row.selection,
            line=row.line,
            result_status=row.result_status,
            profit_units=row.profit_units,
            model_probability=row.model_probability,
            final_probability=row.final_probability,
            edge_pct=row.edge_pct,
            kelly_fraction=row.kelly_fraction,
            confidence_tier=row.confidence_tier,
            decimal_odds=row.decimal_odds,
            american_odds=row.american_odds,
            graded_at=row.graded_at,
        ))
    return response


@router.get("/outcomes/summary", response_model=list[PredictionOutcomeSummaryResponse])
def settled_outcome_summary(session: Session = Depends(get_session)):
    rows = (
        session.query(PredictionOutcome)
        .filter(PredictionOutcome.result_status.in_(("win", "loss", "push")))
        .all()
    )
    summary: dict[tuple[int, str, int, str | None], dict] = {}
    for row in rows:
        fixture = session.query(Fixture).filter_by(id=row.fixture_id).first()
        league_id = fixture.league_id if fixture else None
        key = (row.model_id, row.market_type, league_id or -1, row.confidence_tier)
        bucket = summary.setdefault(key, {
            "settled_count": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "roi_sum": 0.0,
        })
        bucket["settled_count"] += 1
        if row.result_status == "win":
            bucket["wins"] += 1
        elif row.result_status == "loss":
            bucket["losses"] += 1
        else:
            bucket["pushes"] += 1
        bucket["roi_sum"] += row.profit_units or 0.0

    response: list[PredictionOutcomeSummaryResponse] = []
    for (model_id, market_type, league_id, confidence_tier), bucket in summary.items():
        mv = session.query(ModelVersion).filter_by(id=model_id).first()
        league = session.query(League).filter_by(id=league_id).first() if league_id != -1 else None
        settled_count = bucket["settled_count"]
        response.append(PredictionOutcomeSummaryResponse(
            model_name=mv.name if mv else "unknown",
            version=mv.version if mv else "unknown",
            market_type=market_type,
            league=league.name if league else "Unknown",
            confidence_tier=confidence_tier,
            settled_count=settled_count,
            wins=bucket["wins"],
            losses=bucket["losses"],
            pushes=bucket["pushes"],
            win_rate=(
                bucket["wins"] / (bucket["wins"] + bucket["losses"])
                if (bucket["wins"] + bucket["losses"])
                else 0.0
            ),
            roi=(bucket["roi_sum"] / settled_count) if settled_count else 0.0,
        ))

    return sorted(
        response,
        key=lambda row: (row.market_type, row.league, row.model_name, row.confidence_tier or ""),
    )


@router.post("/manual-picks", response_model=ManualPickResponse)
def create_manual_pick(payload: ManualPickCreateRequest, session: Session = Depends(get_session)):
    fixture = session.query(Fixture).filter_by(id=payload.fixture_id).first()
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")
    if payload.market_type not in {"moneyline", "spread", "ou"}:
        raise HTTPException(status_code=400, detail="Invalid market_type")
    if not _valid_selection(payload.market_type, payload.selection):
        raise HTTPException(status_code=400, detail="Invalid selection for market_type")
    if payload.market_type in {"spread", "ou"} and payload.line is None:
        raise HTTPException(status_code=400, detail="line is required for spread and ou picks")
    if payload.decimal_odds is None and payload.american_odds is None:
        raise HTTPException(status_code=400, detail="Provide decimal_odds or american_odds")

    decimal_odds = (
        payload.decimal_odds
        if payload.decimal_odds is not None
        else _american_to_decimal(payload.american_odds)
    )
    american_odds = (
        payload.american_odds
        if payload.american_odds is not None
        else decimal_to_american(decimal_odds)
    )

    pick = ManualPick(
        fixture_id=payload.fixture_id,
        market_type=payload.market_type,
        selection=payload.selection,
        line=payload.line,
        decimal_odds=decimal_odds,
        american_odds=american_odds,
        stake_units=payload.stake_units,
        bookmaker=payload.bookmaker,
        notes=payload.notes,
        result_status="open",
        created_at=datetime.now(timezone.utc),
    )
    session.add(pick)
    session.commit()
    session.refresh(pick)

    home_team, away_team, league = _fixture_context(session, pick.fixture_id)
    return ManualPickResponse(
        id=pick.id,
        fixture_id=pick.fixture_id,
        home_team=home_team,
        away_team=away_team,
        league=league,
        market_type=pick.market_type,
        selection=pick.selection,
        line=pick.line,
        decimal_odds=pick.decimal_odds,
        american_odds=pick.american_odds,
        stake_units=pick.stake_units,
        bookmaker=pick.bookmaker,
        notes=pick.notes,
        result_status=pick.result_status,
        profit_units=pick.profit_units,
        graded_at=pick.graded_at,
        created_at=pick.created_at,
    )


@router.get("/manual-picks", response_model=list[ManualPickResponse])
def list_manual_picks(
    result_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    query = session.query(ManualPick)
    if result_status:
        query = query.filter(ManualPick.result_status == result_status)
    rows = query.order_by(ManualPick.created_at.desc()).limit(limit).all()
    response: list[ManualPickResponse] = []
    for row in rows:
        home_team, away_team, league = _fixture_context(session, row.fixture_id)
        response.append(ManualPickResponse(
            id=row.id,
            fixture_id=row.fixture_id,
            home_team=home_team,
            away_team=away_team,
            league=league,
            market_type=row.market_type,
            selection=row.selection,
            line=row.line,
            decimal_odds=row.decimal_odds,
            american_odds=row.american_odds,
            stake_units=row.stake_units,
            bookmaker=row.bookmaker,
            notes=row.notes,
            result_status=row.result_status,
            profit_units=row.profit_units,
            graded_at=row.graded_at,
            created_at=row.created_at,
        ))
    return response


@router.get("/manual-picks/summary", response_model=list[ManualPickSummaryResponse])
def manual_pick_summary(session: Session = Depends(get_session)):
    rows = (
        session.query(ManualPick)
        .filter(ManualPick.result_status.in_(("win", "loss", "push")))
        .all()
    )
    summary: dict[tuple[str, int], dict] = {}
    for row in rows:
        fixture = session.query(Fixture).filter_by(id=row.fixture_id).first()
        league_id = fixture.league_id if fixture else -1
        bucket = summary.setdefault((row.market_type, league_id), {
            "settled_count": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "stake_sum": 0.0,
            "profit_sum": 0.0,
        })
        bucket["settled_count"] += 1
        if row.result_status == "win":
            bucket["wins"] += 1
        elif row.result_status == "loss":
            bucket["losses"] += 1
        else:
            bucket["pushes"] += 1
        bucket["stake_sum"] += row.stake_units or 0.0
        bucket["profit_sum"] += row.profit_units or 0.0

    response: list[ManualPickSummaryResponse] = []
    for (market_type, league_id), bucket in summary.items():
        league = session.query(League).filter_by(id=league_id).first() if league_id != -1 else None
        settled_count = bucket["settled_count"]
        stake_sum = bucket["stake_sum"]
        response.append(ManualPickSummaryResponse(
            market_type=market_type,
            league=league.name if league else "Unknown",
            settled_count=settled_count,
            wins=bucket["wins"],
            losses=bucket["losses"],
            pushes=bucket["pushes"],
            total_stake_units=stake_sum,
            profit_units=bucket["profit_sum"],
            win_rate=(
                bucket["wins"] / (bucket["wins"] + bucket["losses"])
                if (bucket["wins"] + bucket["losses"])
                else 0.0
            ),
            roi=(bucket["profit_sum"] / stake_sum) if stake_sum else 0.0,
        ))
    return sorted(response, key=lambda row: (row.market_type, row.league))


@router.get("/compare/manual-vs-models", response_model=list[ManualVsModelComparisonResponse])
def manual_vs_models(
    market_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    manual_query = session.query(ManualPick).filter(ManualPick.result_status.in_(("win", "loss", "push")))
    if market_type:
        manual_query = manual_query.filter(ManualPick.market_type == market_type)
    manual_rows = manual_query.order_by(ManualPick.graded_at.desc()).limit(limit).all()

    response: list[ManualVsModelComparisonResponse] = []
    for manual in manual_rows:
        matches = (
            session.query(PredictionOutcome)
            .filter(PredictionOutcome.fixture_id == manual.fixture_id)
            .filter(PredictionOutcome.market_type == manual.market_type)
            .filter(PredictionOutcome.selection == manual.selection)
            .filter(PredictionOutcome.result_status.in_(("win", "loss", "push")))
            .all()
        )
        filtered = [row for row in matches if _same_line(row.line, manual.line)]
        for row in filtered:
            mv = session.query(ModelVersion).filter_by(id=row.model_id).first()
            home_team, away_team, league = _fixture_context(session, manual.fixture_id)
            response.append(ManualVsModelComparisonResponse(
                fixture_id=manual.fixture_id,
                home_team=home_team,
                away_team=away_team,
                league=league,
                market_type=manual.market_type,
                selection=manual.selection,
                line=manual.line,
                manual_pick_id=manual.id,
                manual_result_status=manual.result_status,
                manual_profit_units=manual.profit_units,
                manual_stake_units=manual.stake_units,
                model_name=mv.name if mv else "unknown",
                version=mv.version if mv else "unknown",
                model_result_status=row.result_status,
                model_profit_units=row.profit_units,
                model_probability=row.model_probability,
                model_final_probability=row.final_probability,
                model_edge_pct=row.edge_pct,
                model_confidence_tier=row.confidence_tier,
                graded_at=manual.graded_at or row.graded_at,
            ))
    return response


@router.get("/compare/manual-vs-models/summary", response_model=list[ManualVsModelSummaryResponse])
def manual_vs_models_summary(session: Session = Depends(get_session)):
    comparisons = manual_vs_models(session=session, limit=1000)
    summary: dict[tuple[str, str, str, str], dict] = {}
    for row in comparisons:
        key = (row.model_name, row.version, row.market_type, row.league)
        bucket = summary.setdefault(key, {
            "compared_picks": 0,
            "manual_wins": 0,
            "model_wins": 0,
            "manual_profit_units": 0.0,
            "model_profit_units": 0.0,
            "manual_stake_units": 0.0,
        })
        bucket["compared_picks"] += 1
        if row.manual_result_status == "win":
            bucket["manual_wins"] += 1
        if row.model_result_status == "win":
            bucket["model_wins"] += 1
        bucket["manual_profit_units"] += row.manual_profit_units or 0.0
        bucket["model_profit_units"] += row.model_profit_units or 0.0
        bucket["manual_stake_units"] += row.manual_stake_units or 0.0

    response: list[ManualVsModelSummaryResponse] = []
    for (model_name, version, market_type, league), bucket in summary.items():
        compared = bucket["compared_picks"]
        response.append(ManualVsModelSummaryResponse(
            model_name=model_name,
            version=version,
            market_type=market_type,
            league=league,
            compared_picks=compared,
            manual_wins=bucket["manual_wins"],
            model_wins=bucket["model_wins"],
            manual_profit_units=bucket["manual_profit_units"],
            model_profit_units=bucket["model_profit_units"],
            manual_roi=(
                bucket["manual_profit_units"] / bucket["manual_stake_units"]
                if bucket["manual_stake_units"]
                else 0.0
            ),
            model_roi=(bucket["model_profit_units"] / compared) if compared else 0.0,
        ))
    return sorted(response, key=lambda row: (row.market_type, row.league, row.model_name, row.version))


@router.get("/compare/fixtures", response_model=list[FixtureManualComparisonResponse])
def manual_vs_models_by_fixture(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    manual_rows = (
        session.query(ManualPick)
        .filter(ManualPick.result_status.in_(("win", "loss", "push")))
        .order_by(ManualPick.graded_at.desc())
        .limit(limit)
        .all()
    )

    response: list[FixtureManualComparisonResponse] = []
    for manual in manual_rows:
        home_team, away_team, league = _fixture_context(session, manual.fixture_id)
        response.append(FixtureManualComparisonResponse(
            fixture_id=manual.fixture_id,
            home_team=home_team,
            away_team=away_team,
            league=league,
            manual_pick_id=manual.id,
            manual_market_type=manual.market_type,
            manual_selection=manual.selection,
            manual_line=manual.line,
            manual_result_status=manual.result_status,
            manual_profit_units=manual.profit_units,
            manual_stake_units=manual.stake_units,
            graded_at=manual.graded_at,
            compared_models=_best_model_picks_for_fixture(session, manual.fixture_id),
        ))
    return response
