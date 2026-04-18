from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.collector.understat import LEAGUE_UNDERSTAT_KEYS, UnderstatClient
from app.db.models import EloFormPrediction, Fixture, League, Result, Team
from sqlalchemy import and_

logger = logging.getLogger(__name__)

BASE_ELO = 1500.0
DEFAULT_HOME_ADVANTAGE_ELO = 60.0
DEFAULT_K_FACTOR = 24.0
BASE_DRAW_PROBABILITY = 0.27
MIN_DRAW_PROBABILITY = 0.18
MAX_TREND_SHIFT = 0.06
TREND_SCALE = 0.35
LOOKBACK_MATCHES = 5
BASE_TOTAL_GOALS = 2.6
MIN_EXPECTED_GOALS = 0.2
MAX_EXPECTED_GOALS = 3.6


@dataclass
class XGFormSnapshot:
    avg_xg_diff: float | None
    trend: float | None
    matches_used: int


@dataclass
class GoalProjection:
    home_expected_goals: float
    away_expected_goals: float
    home_two_plus_probability: float
    away_two_plus_probability: float
    home_clean_sheet_probability: float
    away_clean_sheet_probability: float


def _normalize_team_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _parse_understat_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _trend_slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    x_mean = (len(values) - 1) / 2.0
    y_mean = sum(values) / len(values)
    numerator = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(values))
    denominator = sum((idx - x_mean) ** 2 for idx in range(len(values)))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _poisson_zero_probability(expected_goals: float) -> float:
    return math.exp(-expected_goals)


def _poisson_two_plus_probability(expected_goals: float) -> float:
    # P(X >= 2) for a Poisson process = 1 - e^-lambda * (1 + lambda)
    return 1.0 - (_poisson_zero_probability(expected_goals) * (1.0 + expected_goals))


def project_match_goal_probs(
    *,
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    home_xg_diff_avg: float | None,
    away_xg_diff_avg: float | None,
    home_xg_trend: float | None,
    away_xg_trend: float | None,
) -> GoalProjection:
    strength_signal = _clamp(home_probability - away_probability, -0.75, 0.75)
    trend_signal = _clamp((home_xg_trend or 0.0) - (away_xg_trend or 0.0), -0.4, 0.4)
    form_signal = _clamp((home_xg_diff_avg or 0.0) - (away_xg_diff_avg or 0.0), -2.0, 2.0)
    total_signal = _clamp((home_xg_diff_avg or 0.0) + (away_xg_diff_avg or 0.0), -2.0, 2.0)

    total_goals = _clamp(
        BASE_TOTAL_GOALS + (0.12 * total_signal) + (0.18 * abs(trend_signal)),
        1.8,
        3.8,
    )
    home_share = _clamp(
        0.5 + (0.42 * strength_signal) + (0.08 * form_signal) + (0.20 * trend_signal),
        0.18,
        0.82,
    )

    # Draw-heavy matches suppress both team's scoring projections slightly.
    draw_drag = _clamp((draw_probability - 0.22) * 0.6, 0.0, 0.08)
    home_expected_goals = _clamp((total_goals * home_share) - draw_drag, MIN_EXPECTED_GOALS, MAX_EXPECTED_GOALS)
    away_expected_goals = _clamp(total_goals - home_expected_goals - draw_drag, MIN_EXPECTED_GOALS, MAX_EXPECTED_GOALS)

    return GoalProjection(
        home_expected_goals=home_expected_goals,
        away_expected_goals=away_expected_goals,
        home_two_plus_probability=_poisson_two_plus_probability(home_expected_goals),
        away_two_plus_probability=_poisson_two_plus_probability(away_expected_goals),
        home_clean_sheet_probability=_poisson_zero_probability(away_expected_goals),
        away_clean_sheet_probability=_poisson_zero_probability(home_expected_goals),
    )


class EloFormPredictor:
    """
    Standalone match-outcome model:
    1. Build a pure Elo baseline from historical results.
    2. Adjust the home/away win split using each team's last-five xG-differential trend.

    This predictor is intentionally isolated from the existing moneyline models:
    it writes to its own table and does not participate in the shared pick flow.
    """

    def __init__(
        self,
        session,
        lead_hours: int | None = None,
        understat_client: UnderstatClient | None = None,
        home_advantage_elo: float = DEFAULT_HOME_ADVANTAGE_ELO,
        k_factor: float = DEFAULT_K_FACTOR,
        max_trend_shift: float = MAX_TREND_SHIFT,
        trend_scale: float = TREND_SCALE,
        bully_gap_threshold: float = 120.0,
    ):
        self.session = session
        self._lead_hours = lead_hours
        self._understat = understat_client or UnderstatClient()
        self._home_advantage_elo = home_advantage_elo
        self._k_factor = k_factor
        self._max_trend_shift = max_trend_shift
        self._trend_scale = trend_scale
        self._bully_gap_threshold = bully_gap_threshold
        self._elo_cache: dict[int, dict[int, float]] = {}
        self._league_match_cache: dict[tuple[str, int], list[dict]] = {}
        self._team_name_cache: dict[int, str] = {}

    def run(self, model_id: int) -> None:
        for fixture in self._get_upcoming_fixtures():
            league = self.session.query(League).filter_by(id=fixture.league_id).first()
            if league is None:
                continue

            ratings = self._ratings_for_league(league.id)
            home_elo = ratings.get(fixture.home_team_id, BASE_ELO)
            away_elo = ratings.get(fixture.away_team_id, BASE_ELO)
            elo_gap = abs((home_elo + self._home_advantage_elo) - away_elo)
            favorite_side = "home" if (home_elo + self._home_advantage_elo) >= away_elo else "away"
            base_probs = self._elo_probabilities(home_elo, away_elo)

            home_form = self._recent_xg_form(league, fixture, fixture.home_team_id)
            away_form = self._recent_xg_form(league, fixture, fixture.away_team_id)
            adjusted_probs, home_shift = self._apply_xg_context(
                base_probs,
                home_trend=home_form.trend,
                away_trend=away_form.trend,
            )

            self._upsert(
                model_id=model_id,
                fixture_id=fixture.id,
                favorite_side=favorite_side,
                elo_gap=elo_gap,
                is_bully_spot=elo_gap >= self._bully_gap_threshold,
                home_elo=home_elo,
                away_elo=away_elo,
                home_form=home_form,
                away_form=away_form,
                home_shift=home_shift,
                probabilities=adjusted_probs,
            )

        self.session.commit()

    def _get_upcoming_fixtures(self) -> list[Fixture]:
        if self._lead_hours is not None:
            lead = self._lead_hours
        else:
            try:
                from app.config import settings

                lead = settings.prediction_lead_hours
            except Exception:
                lead = 72
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=lead)
        return (
            self.session.query(Fixture)
            .filter(Fixture.status == "scheduled")
            .filter(Fixture.kickoff_at >= now)
            .filter(Fixture.kickoff_at <= cutoff)
            .all()
        )

    def _ratings_for_league(self, league_id: int) -> dict[int, float]:
        cached = self._elo_cache.get(league_id)
        if cached is not None:
            return cached

        ratings: dict[int, float] = {}
        rows = (
            self.session.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(Fixture.league_id == league_id)
            .filter(Result.outcome.in_(("home", "draw", "away")))
            .filter(
                and_(
                    Result.home_score.isnot(None),
                    Result.away_score.isnot(None),
                )
            )
            .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
            .all()
        )

        for fixture, result in rows:
            home_elo = ratings.get(fixture.home_team_id, BASE_ELO)
            away_elo = ratings.get(fixture.away_team_id, BASE_ELO)
            expected_home = self._expected_home_score(home_elo, away_elo)
            actual_home = {"home": 1.0, "draw": 0.5, "away": 0.0}[result.outcome]
            delta = self._k_factor * (actual_home - expected_home)
            ratings[fixture.home_team_id] = home_elo + delta
            ratings[fixture.away_team_id] = away_elo - delta

        self._elo_cache[league_id] = ratings
        return ratings

    def _elo_probabilities(self, home_elo: float, away_elo: float) -> dict[str, float]:
        diff = (home_elo + self._home_advantage_elo) - away_elo
        home_share = 1.0 / (1.0 + math.pow(10.0, -diff / 400.0))
        draw_prob = _clamp(
            BASE_DRAW_PROBABILITY - (0.10 * min(1.0, abs(diff) / 300.0)),
            MIN_DRAW_PROBABILITY,
            BASE_DRAW_PROBABILITY,
        )
        decisive_mass = 1.0 - draw_prob
        return {
            "home": decisive_mass * home_share,
            "draw": draw_prob,
            "away": decisive_mass * (1.0 - home_share),
        }

    def _expected_home_score(self, home_elo: float, away_elo: float) -> float:
        diff = (home_elo + self._home_advantage_elo) - away_elo
        return 1.0 / (1.0 + math.pow(10.0, -diff / 400.0))

    def _recent_xg_form(
        self,
        league: League,
        fixture: Fixture,
        team_id: int,
    ) -> XGFormSnapshot:
        understat_key = LEAGUE_UNDERSTAT_KEYS.get(league.espn_id)
        if understat_key is None:
            return XGFormSnapshot(avg_xg_diff=None, trend=None, matches_used=0)

        team_name = self._team_name(team_id)
        normalized_team = _normalize_team_name(team_name)
        fixture_kickoff = _as_utc(fixture.kickoff_at)
        relevant_matches: list[tuple[datetime, float]] = []

        for match in self._load_league_matches(league.espn_id, fixture.kickoff_at):
            kickoff_at = _parse_understat_datetime(match.get("datetime"))
            if kickoff_at is None or kickoff_at >= fixture_kickoff:
                continue

            home = match.get("h") or {}
            away = match.get("a") or {}
            home_name = str(home.get("title") or "")
            away_name = str(away.get("title") or "")
            if _normalize_team_name(home_name) == normalized_team:
                team_xg = float(home["xG"])
                opp_xg = float(away["xG"])
            elif _normalize_team_name(away_name) == normalized_team:
                team_xg = float(away["xG"])
                opp_xg = float(home["xG"])
            else:
                continue
            relevant_matches.append((kickoff_at, team_xg - opp_xg))

        if not relevant_matches:
            return XGFormSnapshot(avg_xg_diff=None, trend=None, matches_used=0)

        recent = sorted(relevant_matches, key=lambda row: row[0], reverse=True)[:LOOKBACK_MATCHES]
        values = [diff for _, diff in sorted(recent, key=lambda row: row[0])]
        return XGFormSnapshot(
            avg_xg_diff=sum(values) / len(values),
            trend=_trend_slope(values),
            matches_used=len(values),
        )

    def _load_league_matches(self, league_espn_id: str, kickoff_at: datetime) -> list[dict]:
        understat_key = LEAGUE_UNDERSTAT_KEYS.get(league_espn_id)
        if understat_key is None:
            return []

        current_season = self._season_start_year(kickoff_at)
        combined: list[dict] = []
        for season in (current_season, current_season - 1):
            cache_key = (understat_key, season)
            if cache_key not in self._league_match_cache:
                try:
                    self._league_match_cache[cache_key] = self._understat.fetch_league_matches(
                        understat_key, season
                    )
                except Exception as exc:
                    logger.warning(
                        "EloFormPredictor: unable to fetch Understat matches for %s %s: %s",
                        understat_key,
                        season,
                        exc,
                    )
                    self._league_match_cache[cache_key] = []
            combined.extend(self._league_match_cache[cache_key])
        return combined

    def _season_start_year(self, kickoff_at: datetime) -> int:
        return kickoff_at.year if kickoff_at.month >= 7 else kickoff_at.year - 1

    def _team_name(self, team_id: int) -> str:
        cached = self._team_name_cache.get(team_id)
        if cached is not None:
            return cached
        team = self.session.query(Team).filter_by(id=team_id).first()
        if team is None:
            return ""
        self._team_name_cache[team_id] = team.name
        return team.name

    def _apply_xg_context(
        self,
        base_probs: dict[str, float],
        *,
        home_trend: float | None,
        away_trend: float | None,
    ) -> tuple[dict[str, float], float]:
        if home_trend is None and away_trend is None:
            return base_probs, 0.0

        relative_trend = (home_trend or 0.0) - (away_trend or 0.0)
        normalized_signal = _clamp(relative_trend / self._trend_scale, -1.0, 1.0)
        shift = normalized_signal * self._max_trend_shift
        shift = _clamp(shift, -base_probs["home"], base_probs["away"])

        return (
            {
                "home": base_probs["home"] + shift,
                "draw": base_probs["draw"],
                "away": base_probs["away"] - shift,
            },
            shift,
        )

    def _upsert(
        self,
        *,
        model_id: int,
        fixture_id: int,
        favorite_side: str,
        elo_gap: float,
        is_bully_spot: bool,
        home_elo: float,
        away_elo: float,
        home_form: XGFormSnapshot,
        away_form: XGFormSnapshot,
        home_shift: float,
        probabilities: dict[str, float],
    ) -> None:
        existing = (
            self.session.query(EloFormPrediction)
            .filter_by(model_id=model_id, fixture_id=fixture_id)
            .first()
        )
        payload = {
            "favorite_side": favorite_side,
            "elo_gap": elo_gap,
            "is_bully_spot": is_bully_spot,
            "home_elo": home_elo,
            "away_elo": away_elo,
            "home_xg_diff_avg": home_form.avg_xg_diff,
            "away_xg_diff_avg": away_form.avg_xg_diff,
            "home_xg_trend": home_form.trend,
            "away_xg_trend": away_form.trend,
            "home_xg_matches_used": home_form.matches_used,
            "away_xg_matches_used": away_form.matches_used,
            "trend_adjustment": home_shift,
            "home_probability": probabilities["home"],
            "draw_probability": probabilities["draw"],
            "away_probability": probabilities["away"],
        }
        if existing is not None:
            for key, value in payload.items():
                setattr(existing, key, value)
            return

        self.session.add(
            EloFormPrediction(
                model_id=model_id,
                fixture_id=fixture_id,
                created_at=datetime.now(timezone.utc),
                **payload,
            )
        )


from app.bully_engine import (  # noqa: E402,F401
    BASE_ELO,
    DEFAULT_HOME_ADVANTAGE_ELO,
    DEFAULT_K_FACTOR,
    MAX_TREND_SHIFT,
    TREND_SCALE,
    XGFormSnapshot,
    GoalProjection,
    LeagueFit,
    FixturePrediction,
    fit_league_goal_rates,
    project_match_goal_probs,
    EloFormPredictor,
)
