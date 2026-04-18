from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from app.bully_engine import EloFormPredictor
from app.db.models import Fixture, Result, Team


DEFAULT_SGP_BANDS: tuple[tuple[float, float], ...] = (
    (0.00, 0.40),
    (0.40, 0.45),
    (0.45, 0.50),
    (0.50, 0.55),
    (0.55, 0.60),
    (0.60, 1.01),
)

DEFAULT_SGP_THRESHOLDS: tuple[float, ...] = (0.40, 0.45, 0.50, 0.55, 0.60)


@dataclass(frozen=True)
class BullySgpReplayRow:
    fixture_id: int
    kickoff_at: datetime
    favorite_team: str
    underdog_team: str
    favorite_side: str
    favorite_probability: float
    favorite_two_plus_probability: float
    sgp_lens: float
    favorite_win: bool
    sgp_hit: bool
    favorite_goals: int
    underdog_goals: int
    favorite_expected_goals: float
    expected_goals_delta: float
    elo_gap: float


@dataclass(frozen=True)
class SgpBandSummary:
    low: float
    high: float
    total: int
    win_rate: float | None
    sgp_hit_rate: float | None


@dataclass(frozen=True)
class SgpThresholdSummary:
    threshold: float
    total: int
    win_rate: float | None
    sgp_hit_rate: float | None


def replay_bully_sgp_rows(
    session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int | None = None,
    max_checked: int | None = None,
    enable_understat_fetch: bool = False,
) -> list[BullySgpReplayRow]:
    predictor = EloFormPredictor(session, enable_understat_fetch=enable_understat_fetch)
    query = session.query(Fixture).filter(Fixture.status == "completed")
    if date_from is not None:
        query = query.filter(Fixture.kickoff_at >= date_from)
    if date_to is not None:
        query = query.filter(Fixture.kickoff_at <= date_to)
    fixtures = query.order_by(Fixture.kickoff_at.desc(), Fixture.id.desc()).all()

    team_names = {team.id: team.name for team in session.query(Team).all()}

    rows: list[BullySgpReplayRow] = []
    checked = 0
    for fixture in fixtures:
        result = session.query(Result).filter_by(fixture_id=fixture.id).first()
        if (
            result is None
            or result.outcome is None
            or result.home_score is None
            or result.away_score is None
        ):
            continue

        checked += 1
        prediction = predictor.predict_fixture(fixture, as_of=fixture.kickoff_at)
        if prediction is None or not prediction.is_bully_spot:
            if max_checked is not None and checked >= max_checked:
                break
            continue

        favorite_is_home = prediction.favorite_side == "home"
        favorite_probability = prediction.probabilities[prediction.favorite_side]
        favorite_two_plus_probability = (
            prediction.goals.home_two_plus_probability
            if favorite_is_home
            else prediction.goals.away_two_plus_probability
        )
        favorite_goals = result.home_score if favorite_is_home else result.away_score
        underdog_goals = result.away_score if favorite_is_home else result.home_score

        rows.append(
            BullySgpReplayRow(
                fixture_id=fixture.id,
                kickoff_at=fixture.kickoff_at,
                favorite_team=team_names.get(
                    fixture.home_team_id if favorite_is_home else fixture.away_team_id,
                    str(fixture.home_team_id if favorite_is_home else fixture.away_team_id),
                ),
                underdog_team=team_names.get(
                    fixture.away_team_id if favorite_is_home else fixture.home_team_id,
                    str(fixture.away_team_id if favorite_is_home else fixture.home_team_id),
                ),
                favorite_side=prediction.favorite_side,
                favorite_probability=favorite_probability,
                favorite_two_plus_probability=favorite_two_plus_probability,
                sgp_lens=favorite_probability * favorite_two_plus_probability,
                favorite_win=result.outcome == prediction.favorite_side,
                sgp_hit=(result.outcome == prediction.favorite_side) and favorite_goals >= 2,
                favorite_goals=favorite_goals,
                underdog_goals=underdog_goals,
                favorite_expected_goals=(
                    prediction.goals.home_expected_goals
                    if favorite_is_home
                    else prediction.goals.away_expected_goals
                ),
                expected_goals_delta=abs(
                    prediction.goals.home_expected_goals - prediction.goals.away_expected_goals
                ),
                elo_gap=prediction.elo_gap,
            )
        )

        if limit is not None and len(rows) >= limit:
            break
        if max_checked is not None and checked >= max_checked:
            break

    return rows


def summarize_sgp_bands(
    rows: Sequence[BullySgpReplayRow],
    bands: Iterable[tuple[float, float]] = DEFAULT_SGP_BANDS,
) -> list[SgpBandSummary]:
    summaries: list[SgpBandSummary] = []
    for low, high in bands:
        band_rows = [row for row in rows if low <= row.sgp_lens < high]
        summaries.append(
            SgpBandSummary(
                low=low,
                high=high,
                total=len(band_rows),
                win_rate=_rate(row.favorite_win for row in band_rows),
                sgp_hit_rate=_rate(row.sgp_hit for row in band_rows),
            )
        )
    return summaries


def summarize_sgp_thresholds(
    rows: Sequence[BullySgpReplayRow],
    thresholds: Iterable[float] = DEFAULT_SGP_THRESHOLDS,
) -> list[SgpThresholdSummary]:
    summaries: list[SgpThresholdSummary] = []
    for threshold in thresholds:
        subset = [row for row in rows if row.sgp_lens >= threshold]
        summaries.append(
            SgpThresholdSummary(
                threshold=threshold,
                total=len(subset),
                win_rate=_rate(row.favorite_win for row in subset),
                sgp_hit_rate=_rate(row.sgp_hit for row in subset),
            )
        )
    return summaries


def _rate(values: Iterable[bool]) -> float | None:
    items = list(values)
    if not items:
        return None
    return sum(1.0 if item else 0.0 for item in items) / len(items)
