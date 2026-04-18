from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.db.models import EloFormPrediction, Fixture, FormCache, League, Result, Team
from sqlalchemy import and_, or_

if TYPE_CHECKING:
    from app.collector.understat import UnderstatClient

logger = logging.getLogger(__name__)


def _understat_league_key(league_espn_id: str) -> str | None:
    try:
        from app.collector.understat import LEAGUE_UNDERSTAT_KEYS
    except Exception:
        return None
    return LEAGUE_UNDERSTAT_KEYS.get(league_espn_id)

BASE_ELO = 1500.0
DEFAULT_BULLY_GAP_THRESHOLD = 120.0
DEFAULT_HOME_ADVANTAGE_ELO = 60.0
MIN_HOME_ADVANTAGE_ELO = 20.0
MAX_HOME_ADVANTAGE_ELO = 100.0
DEFAULT_K_FACTOR = 24.0
BASE_DRAW_PROBABILITY = 0.27
MIN_DRAW_PROBABILITY = 0.14
MAX_DRAW_PROBABILITY = 0.34
DEFAULT_DRAW_SLOPE = -0.22
MAX_TREND_SHIFT = 0.06
TREND_SCALE = 0.30
FORM_LOOKBACK_MATCHES = 8
TREND_SHORT_MATCHES = 3
FORM_DECAY = 0.72
GENERIC_HOME_GOALS = 1.45
GENERIC_AWAY_GOALS = 1.15
MIN_EXPECTED_GOALS = 0.2
MAX_EXPECTED_GOALS = 3.6
LEAGUE_BULLY_XG_DELTA_THRESHOLDS: dict[str, float] = {
    "eng.1": 2.0,
    "esp.1": 1.3,
    "ita.1": 1.4,
    "ger.1": 0.9,
    "fra.1": 1.1,
}


@dataclass
class XGFormSnapshot:
    avg_for: float | None
    avg_against: float | None
    avg_xg_diff: float | None
    trend: float | None
    matches_used: int
    source: str = "none"


@dataclass
class GoalProjection:
    home_expected_goals: float
    away_expected_goals: float
    home_two_plus_probability: float
    away_two_plus_probability: float
    home_clean_sheet_probability: float
    away_clean_sheet_probability: float


@dataclass
class LeagueFit:
    home_advantage_elo: float
    draw_intercept: float
    draw_slope: float
    draw_baseline_probability: float
    avg_home_goals: float
    avg_away_goals: float
    samples_used: int


@dataclass
class FixturePrediction:
    favorite_side: str
    elo_gap: float
    is_bully_spot: bool
    home_elo: float
    away_elo: float
    home_form: XGFormSnapshot
    away_form: XGFormSnapshot
    trend_adjustment: float
    probabilities: dict[str, float]
    goals: GoalProjection
    league_fit: LeagueFit


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


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp_v = math.exp(-value)
        return 1.0 / (1.0 + exp_v)
    exp_v = math.exp(value)
    return exp_v / (1.0 + exp_v)


def _logit(probability: float) -> float:
    probability = _clamp(probability, 1e-4, 1 - 1e-4)
    return math.log(probability / (1.0 - probability))


def _poisson_zero_probability(expected_goals: float) -> float:
    return math.exp(-expected_goals)


def _poisson_two_plus_probability(expected_goals: float) -> float:
    return 1.0 - (_poisson_zero_probability(expected_goals) * (1.0 + expected_goals))


def passes_bully_xg_overlay(
    league_espn_id: str,
    expected_goals_delta: float,
    *,
    enabled: bool,
) -> bool:
    if not enabled:
        return True

    threshold = LEAGUE_BULLY_XG_DELTA_THRESHOLDS.get(league_espn_id)
    if threshold is None:
        return True

    return abs(expected_goals_delta) >= threshold


def fit_league_goal_rates(session, league_id: int, as_of: datetime | None = None) -> tuple[float, float, int]:
    query = (
        session.query(Result.home_score, Result.away_score)
        .join(Fixture, Fixture.id == Result.fixture_id)
        .filter(Fixture.league_id == league_id)
        .filter(Result.home_score.isnot(None))
        .filter(Result.away_score.isnot(None))
    )
    if as_of is not None:
        query = query.filter(Fixture.kickoff_at < _as_utc(as_of))

    rows = query.all()
    total = len(rows)
    if total <= 0:
        return GENERIC_HOME_GOALS, GENERIC_AWAY_GOALS, 0

    empirical_home = sum(float(home_score) for home_score, _ in rows) / total
    empirical_away = sum(float(away_score) for _, away_score in rows) / total
    sample_weight = min(1.0, total / 120.0)
    avg_home = ((1.0 - sample_weight) * GENERIC_HOME_GOALS) + (sample_weight * empirical_home)
    avg_away = ((1.0 - sample_weight) * GENERIC_AWAY_GOALS) + (sample_weight * empirical_away)
    return avg_home, avg_away, total


def project_match_goal_probs(
    *,
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    home_form_for_avg: float | None,
    home_form_against_avg: float | None,
    away_form_for_avg: float | None,
    away_form_against_avg: float | None,
    home_xg_diff_avg: float | None,
    away_xg_diff_avg: float | None,
    home_xg_trend: float | None,
    away_xg_trend: float | None,
    league_avg_home_goals: float = GENERIC_HOME_GOALS,
    league_avg_away_goals: float = GENERIC_AWAY_GOALS,
) -> GoalProjection:
    home_for = home_form_for_avg if home_form_for_avg is not None else league_avg_home_goals
    home_against = home_form_against_avg if home_form_against_avg is not None else league_avg_away_goals
    away_for = away_form_for_avg if away_form_for_avg is not None else league_avg_away_goals
    away_against = away_form_against_avg if away_form_against_avg is not None else league_avg_home_goals

    home_base = (0.55 * league_avg_home_goals) + (0.45 * math.sqrt(max(home_for, 0.2) * max(away_against, 0.2)))
    away_base = (0.55 * league_avg_away_goals) + (0.45 * math.sqrt(max(away_for, 0.2) * max(home_against, 0.2)))

    strength_signal = _clamp(home_probability - away_probability, -0.75, 0.75)
    trend_signal = _clamp((home_xg_trend or 0.0) - (away_xg_trend or 0.0), -0.4, 0.4)
    form_signal = _clamp((home_xg_diff_avg or 0.0) - (away_xg_diff_avg or 0.0), -2.0, 2.0)

    draw_drag = _clamp((draw_probability - BASE_DRAW_PROBABILITY) * 0.25, 0.0, 0.05)
    home_multiplier = 1.0 + (0.22 * strength_signal) + (0.07 * form_signal) + (0.12 * trend_signal)
    away_multiplier = 1.0 - (0.22 * strength_signal) - (0.07 * form_signal) - (0.12 * trend_signal)

    home_expected_goals = _clamp((home_base * home_multiplier) - draw_drag, MIN_EXPECTED_GOALS, MAX_EXPECTED_GOALS)
    away_expected_goals = _clamp((away_base * away_multiplier) - draw_drag, MIN_EXPECTED_GOALS, MAX_EXPECTED_GOALS)

    return GoalProjection(
        home_expected_goals=home_expected_goals,
        away_expected_goals=away_expected_goals,
        home_two_plus_probability=_poisson_two_plus_probability(home_expected_goals),
        away_two_plus_probability=_poisson_two_plus_probability(away_expected_goals),
        home_clean_sheet_probability=_poisson_zero_probability(away_expected_goals),
        away_clean_sheet_probability=_poisson_zero_probability(home_expected_goals),
    )


class EloFormPredictor:
    def __init__(
        self,
        session,
        lead_hours: int | None = None,
        understat_client: UnderstatClient | None = None,
        enable_understat_fetch: bool = True,
        home_advantage_elo: float = DEFAULT_HOME_ADVANTAGE_ELO,
        k_factor: float = DEFAULT_K_FACTOR,
        max_trend_shift: float = MAX_TREND_SHIFT,
        trend_scale: float = TREND_SCALE,
        bully_gap_threshold: float = DEFAULT_BULLY_GAP_THRESHOLD,
        bully_xg_overlay_enabled: bool | None = None,
    ):
        self.session = session
        self._lead_hours = lead_hours
        self._understat = understat_client
        if self._understat is None and enable_understat_fetch:
            try:
                from app.collector.understat import UnderstatClient as _UnderstatClient

                self._understat = _UnderstatClient()
            except Exception:
                self._understat = None
        self._default_home_advantage_elo = home_advantage_elo
        self._k_factor = k_factor
        self._max_trend_shift = max_trend_shift
        self._trend_scale = trend_scale
        self._bully_gap_threshold = bully_gap_threshold
        if bully_xg_overlay_enabled is None:
            try:
                from app.config import settings

                bully_xg_overlay_enabled = settings.bully_xg_overlay_enabled
            except Exception:
                bully_xg_overlay_enabled = True
        self._bully_xg_overlay_enabled = bully_xg_overlay_enabled
        self._elo_cache: dict[tuple[int, str | None, int], dict[int, float]] = {}
        self._league_match_cache: dict[tuple[str, int], list[dict]] = {}
        self._team_name_cache: dict[int, str] = {}
        self._league_fit_cache: dict[tuple[int, str | None], LeagueFit] = {}
        self._global_draw_fit_cache: dict[str | None, tuple[float, float, float]] = {}
        self._team_form_cache: dict[tuple[int, int, str | None], XGFormSnapshot] = {}

    def run(self, model_id: int) -> None:
        for fixture in self._get_upcoming_fixtures():
            prediction = self.predict_fixture(fixture)
            if prediction is None:
                continue
            self._upsert(model_id, fixture.id, prediction)
        self.session.commit()

    def predict_fixture(self, fixture: Fixture, *, as_of: datetime | None = None) -> FixturePrediction | None:
        league = self.session.query(League).filter_by(id=fixture.league_id).first()
        if league is None:
            return None

        cutoff = _as_utc(as_of or fixture.kickoff_at)
        league_fit = self._league_fit(league.id, cutoff)
        ratings = self._ratings_for_league(league.id, cutoff, league_fit.home_advantage_elo)
        home_elo = ratings.get(fixture.home_team_id, BASE_ELO)
        away_elo = ratings.get(fixture.away_team_id, BASE_ELO)
        elo_gap = abs((home_elo + league_fit.home_advantage_elo) - away_elo)
        favorite_side = "home" if (home_elo + league_fit.home_advantage_elo) >= away_elo else "away"
        base_probs = self._elo_probabilities(home_elo, away_elo, league_fit)

        home_form = self._recent_xg_form(league, fixture, fixture.home_team_id, cutoff)
        away_form = self._recent_xg_form(league, fixture, fixture.away_team_id, cutoff)
        adjusted_probs, home_shift = self._apply_xg_context(base_probs, home_form=home_form, away_form=away_form)
        goals = project_match_goal_probs(
            home_probability=adjusted_probs["home"],
            draw_probability=adjusted_probs["draw"],
            away_probability=adjusted_probs["away"],
            home_form_for_avg=home_form.avg_for,
            home_form_against_avg=home_form.avg_against,
            away_form_for_avg=away_form.avg_for,
            away_form_against_avg=away_form.avg_against,
            home_xg_diff_avg=home_form.avg_xg_diff,
            away_xg_diff_avg=away_form.avg_xg_diff,
            home_xg_trend=home_form.trend,
            away_xg_trend=away_form.trend,
            league_avg_home_goals=league_fit.avg_home_goals,
            league_avg_away_goals=league_fit.avg_away_goals,
        )
        is_bully_spot = (elo_gap >= self._bully_gap_threshold) and passes_bully_xg_overlay(
            league.espn_id,
            goals.home_expected_goals - goals.away_expected_goals,
            enabled=self._bully_xg_overlay_enabled,
        )

        return FixturePrediction(
            favorite_side=favorite_side,
            elo_gap=elo_gap,
            is_bully_spot=is_bully_spot,
            home_elo=home_elo,
            away_elo=away_elo,
            home_form=home_form,
            away_form=away_form,
            trend_adjustment=home_shift,
            probabilities=adjusted_probs,
            goals=goals,
            league_fit=league_fit,
        )


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

    def _cache_key(self, cutoff: datetime | None) -> str | None:
        return cutoff.isoformat() if cutoff is not None else None

    def _league_fit(self, league_id: int, cutoff: datetime | None) -> LeagueFit:
        key = (league_id, self._cache_key(cutoff))
        cached = self._league_fit_cache.get(key)
        if cached is not None:
            return cached

        rows = self._historical_rows(league_id, cutoff)
        home_advantage_elo = self._fit_home_advantage_elo(rows)
        global_draw_intercept, global_draw_slope, global_draw_baseline = self._global_draw_fit(cutoff)
        draw_intercept, draw_slope, draw_baseline_probability = self._fit_draw_model(
            rows,
            home_advantage_elo,
            prior_intercept=global_draw_intercept,
            prior_slope=global_draw_slope,
            prior_draw_rate=global_draw_baseline,
        )
        avg_home_goals, avg_away_goals, goal_samples = fit_league_goal_rates(self.session, league_id, cutoff)
        fit = LeagueFit(
            home_advantage_elo=home_advantage_elo,
            draw_intercept=draw_intercept,
            draw_slope=draw_slope,
            draw_baseline_probability=draw_baseline_probability,
            avg_home_goals=avg_home_goals,
            avg_away_goals=avg_away_goals,
            samples_used=max(len(rows), goal_samples),
        )
        self._league_fit_cache[key] = fit
        return fit

    def _historical_rows(self, league_id: int, cutoff: datetime | None) -> list[tuple[Fixture, Result]]:
        query = (
            self.session.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(Fixture.league_id == league_id)
            .filter(Result.outcome.in_(("home", "draw", "away")))
            .filter(and_(Result.home_score.isnot(None), Result.away_score.isnot(None)))
        )
        if cutoff is not None:
            query = query.filter(Fixture.kickoff_at < cutoff)
        return query.order_by(Fixture.kickoff_at.asc(), Fixture.id.asc()).all()

    def _fit_home_advantage_elo(self, rows: list[tuple[Fixture, Result]]) -> float:
        total = len(rows)
        if total <= 0:
            return self._default_home_advantage_elo

        home_score_share = sum(
            1.0 if result.outcome == "home" else 0.5 if result.outcome == "draw" else 0.0
            for _, result in rows
        ) / total
        fitted = 400.0 * math.log10(_clamp(home_score_share, 0.05, 0.95) / (1.0 - _clamp(home_score_share, 0.05, 0.95)))
        sample_weight = min(1.0, total / 200.0)
        blended = ((1.0 - sample_weight) * self._default_home_advantage_elo) + (sample_weight * fitted)
        return _clamp(blended, MIN_HOME_ADVANTAGE_ELO, MAX_HOME_ADVANTAGE_ELO)

    def _fit_draw_model(
        self,
        rows: list[tuple[Fixture, Result]],
        home_advantage_elo: float,
        *,
        prior_intercept: float,
        prior_slope: float,
        prior_draw_rate: float,
    ) -> tuple[float, float, float]:
        if not rows:
            return prior_intercept, min(prior_slope, -0.01), prior_draw_rate

        examples = self._draw_examples(rows, home_advantage_elo)
        return self._fit_draw_examples(
            examples,
            prior_intercept=prior_intercept,
            prior_slope=prior_slope,
            prior_draw_rate=prior_draw_rate,
        )

    def _draw_examples(
        self,
        rows: list[tuple[Fixture, Result]],
        home_advantage_elo: float,
    ) -> list[tuple[float, float]]:
        examples: list[tuple[float, float]] = []
        ratings: dict[int, float] = {}
        for fixture, result in rows:
            home_elo = ratings.get(fixture.home_team_id, BASE_ELO)
            away_elo = ratings.get(fixture.away_team_id, BASE_ELO)
            abs_gap = abs((home_elo + home_advantage_elo) - away_elo)
            examples.append((abs_gap / 100.0, 1.0 if result.outcome == "draw" else 0.0))

            expected_home = self._expected_home_score(home_elo, away_elo, home_advantage_elo)
            actual_home = {"home": 1.0, "draw": 0.5, "away": 0.0}[result.outcome]
            delta = self._k_factor * (actual_home - expected_home)
            ratings[fixture.home_team_id] = home_elo + delta
            ratings[fixture.away_team_id] = away_elo - delta
        return examples

    def _fit_draw_examples(
        self,
        examples: list[tuple[float, float]],
        *,
        prior_intercept: float,
        prior_slope: float,
        prior_draw_rate: float,
    ) -> tuple[float, float, float]:
        if not examples:
            return prior_intercept, min(prior_slope, -0.01), prior_draw_rate

        empirical_draw_rate = sum(target for _, target in examples) / len(examples)
        sample_weight = min(1.0, len(examples) / 150.0)
        blended_draw_rate = ((1.0 - sample_weight) * prior_draw_rate) + (sample_weight * empirical_draw_rate)
        intercept = _logit(blended_draw_rate)
        slope = prior_slope

        if len(examples) < 30:
            return intercept, min(slope, -0.01), blended_draw_rate

        init_intercept = intercept
        init_slope = slope
        learning_rate = 0.025
        regularization = 0.08
        for _ in range(250):
            grad_intercept = 0.0
            grad_slope = 0.0
            for gap_scaled, target in examples:
                predicted = _sigmoid(intercept + (slope * gap_scaled))
                error = predicted - target
                grad_intercept += error
                grad_slope += error * gap_scaled

            grad_intercept = (grad_intercept / len(examples)) + (regularization * (intercept - init_intercept))
            grad_slope = (grad_slope / len(examples)) + (regularization * (slope - init_slope))
            intercept -= learning_rate * grad_intercept
            slope -= learning_rate * grad_slope

        shrink_weight = min(1.0, len(examples) / 220.0)
        return (
            ((1.0 - shrink_weight) * prior_intercept) + (shrink_weight * intercept),
            min(((1.0 - shrink_weight) * prior_slope) + (shrink_weight * slope), -0.01),
            ((1.0 - shrink_weight) * prior_draw_rate) + (shrink_weight * empirical_draw_rate),
        )

    def _global_draw_fit(self, cutoff: datetime | None) -> tuple[float, float, float]:
        key = self._cache_key(cutoff)
        cached = self._global_draw_fit_cache.get(key)
        if cached is not None:
            return cached

        query = (
            self.session.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(Result.outcome.in_(("home", "draw", "away")))
            .filter(and_(Result.home_score.isnot(None), Result.away_score.isnot(None)))
            .order_by(Fixture.league_id.asc(), Fixture.kickoff_at.asc(), Fixture.id.asc())
        )
        if cutoff is not None:
            query = query.filter(Fixture.kickoff_at < cutoff)
        rows = query.all()
        if not rows:
            fit = (_logit(BASE_DRAW_PROBABILITY), DEFAULT_DRAW_SLOPE, BASE_DRAW_PROBABILITY)
            self._global_draw_fit_cache[key] = fit
            return fit

        rows_by_league: dict[int, list[tuple[Fixture, Result]]] = {}
        for fixture, result in rows:
            rows_by_league.setdefault(fixture.league_id, []).append((fixture, result))

        examples: list[tuple[float, float]] = []
        for league_rows in rows_by_league.values():
            league_home_advantage = self._fit_home_advantage_elo(league_rows)
            examples.extend(self._draw_examples(league_rows, league_home_advantage))

        fit = self._fit_draw_examples(
            examples,
            prior_intercept=_logit(BASE_DRAW_PROBABILITY),
            prior_slope=DEFAULT_DRAW_SLOPE,
            prior_draw_rate=BASE_DRAW_PROBABILITY,
        )
        self._global_draw_fit_cache[key] = fit
        return fit

    def _ratings_for_league(
        self,
        league_id: int,
        cutoff: datetime | None,
        home_advantage_elo: float,
    ) -> dict[int, float]:
        key = (league_id, self._cache_key(cutoff), int(round(home_advantage_elo * 10)))
        cached = self._elo_cache.get(key)
        if cached is not None:
            return cached

        ratings: dict[int, float] = {}
        for fixture, result in self._historical_rows(league_id, cutoff):
            home_elo = ratings.get(fixture.home_team_id, BASE_ELO)
            away_elo = ratings.get(fixture.away_team_id, BASE_ELO)
            expected_home = self._expected_home_score(home_elo, away_elo, home_advantage_elo)
            actual_home = {"home": 1.0, "draw": 0.5, "away": 0.0}[result.outcome]
            delta = self._k_factor * (actual_home - expected_home)
            ratings[fixture.home_team_id] = home_elo + delta
            ratings[fixture.away_team_id] = away_elo - delta

        self._elo_cache[key] = ratings
        return ratings

    def _elo_probabilities(self, home_elo: float, away_elo: float, league_fit: LeagueFit) -> dict[str, float]:
        diff = (home_elo + league_fit.home_advantage_elo) - away_elo
        home_share = self._expected_home_score(home_elo, away_elo, league_fit.home_advantage_elo)
        draw_prob = _clamp(
            _sigmoid(league_fit.draw_intercept + (league_fit.draw_slope * (abs(diff) / 100.0))),
            MIN_DRAW_PROBABILITY,
            MAX_DRAW_PROBABILITY,
        )
        decisive_mass = 1.0 - draw_prob
        return {
            "home": decisive_mass * home_share,
            "draw": draw_prob,
            "away": decisive_mass * (1.0 - home_share),
        }

    def _expected_home_score(self, home_elo: float, away_elo: float, home_advantage_elo: float) -> float:
        diff = (home_elo + home_advantage_elo) - away_elo
        return 1.0 / (1.0 + math.pow(10.0, -diff / 400.0))

    def _recent_xg_form(
        self,
        league: League,
        fixture: Fixture,
        team_id: int,
        cutoff: datetime,
    ) -> XGFormSnapshot:
        key = (league.id, team_id, self._cache_key(cutoff))
        cached = self._team_form_cache.get(key)
        if cached is not None:
            return cached

        observations = self._understat_observations(league, cutoff, team_id)
        source = "understat"
        if not observations:
            observations = self._result_proxy_observations(team_id, cutoff)
            source = "results_proxy"

        if not observations:
            snapshot = self._form_cache_proxy(team_id, fixture.home_team_id == team_id)
            self._team_form_cache[key] = snapshot
            return snapshot

        values_for = [value_for for _, value_for, _ in observations]
        values_against = [value_against for _, _, value_against in observations]
        diffs = [value_for - value_against for value_for, value_against in zip(values_for, values_against)]

        snapshot = XGFormSnapshot(
            avg_for=self._exp_weighted_average(values_for),
            avg_against=self._exp_weighted_average(values_against),
            avg_xg_diff=self._exp_weighted_average(diffs),
            trend=self._stable_trend_signal(diffs),
            matches_used=len(observations),
            source=source,
        )
        self._team_form_cache[key] = snapshot
        return snapshot

    def _understat_observations(
        self,
        league: League,
        cutoff: datetime,
        team_id: int,
    ) -> list[tuple[datetime, float, float]]:
        understat_key = _understat_league_key(league.espn_id)
        if understat_key is None:
            return []

        team_name = self._team_name(team_id)
        normalized_team = _normalize_team_name(team_name)
        observations: list[tuple[datetime, float, float]] = []
        for match in self._load_league_matches(league.espn_id, cutoff):
            kickoff_at = _parse_understat_datetime(match.get("datetime"))
            if kickoff_at is None or kickoff_at >= cutoff:
                continue

            home = match.get("h") or {}
            away = match.get("a") or {}
            home_name = str(home.get("title") or "")
            away_name = str(away.get("title") or "")
            if _normalize_team_name(home_name) == normalized_team:
                observations.append((kickoff_at, float(home["xG"]), float(away["xG"])))
            elif _normalize_team_name(away_name) == normalized_team:
                observations.append((kickoff_at, float(away["xG"]), float(home["xG"])))

        observations.sort(key=lambda row: row[0], reverse=True)
        return list(reversed(observations[:FORM_LOOKBACK_MATCHES]))

    def _result_proxy_observations(self, team_id: int, cutoff: datetime) -> list[tuple[datetime, float, float]]:
        rows = (
            self.session.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id))
            .filter(Fixture.kickoff_at < cutoff)
            .filter(Result.home_score.isnot(None))
            .filter(Result.away_score.isnot(None))
            .order_by(Fixture.kickoff_at.desc(), Fixture.id.desc())
            .limit(FORM_LOOKBACK_MATCHES)
            .all()
        )
        observations: list[tuple[datetime, float, float]] = []
        for fixture, result in reversed(rows):
            if fixture.home_team_id == team_id:
                observations.append((fixture.kickoff_at, float(result.home_score), float(result.away_score)))
            else:
                observations.append((fixture.kickoff_at, float(result.away_score), float(result.home_score)))
        return observations

    def _form_cache_proxy(self, team_id: int, is_home: bool) -> XGFormSnapshot:
        cache = self.session.query(FormCache).filter_by(team_id=team_id, is_home=is_home).first()
        if cache is None:
            return XGFormSnapshot(avg_for=None, avg_against=None, avg_xg_diff=None, trend=None, matches_used=0, source="none")

        avg_for = cache.xg_scored_avg if cache.xg_scored_avg is not None else cache.goals_scored_avg
        avg_against = cache.xg_conceded_avg if cache.xg_conceded_avg is not None else cache.goals_conceded_avg
        avg_diff = None if avg_for is None or avg_against is None else avg_for - avg_against
        return XGFormSnapshot(
            avg_for=avg_for,
            avg_against=avg_against,
            avg_xg_diff=avg_diff,
            trend=0.0 if avg_diff is not None else None,
            matches_used=cache.matches_count or 0,
            source="form_cache",
        )

    def _exp_weighted_average(self, values: list[float]) -> float | None:
        if not values:
            return None
        weights = [FORM_DECAY ** (len(values) - idx - 1) for idx in range(len(values))]
        total_weight = sum(weights)
        return sum(weight * value for weight, value in zip(weights, values)) / total_weight

    def _stable_trend_signal(self, diffs: list[float]) -> float | None:
        if len(diffs) < 2:
            return None
        long_avg = self._exp_weighted_average(diffs)
        short_avg = self._exp_weighted_average(diffs[-min(TREND_SHORT_MATCHES, len(diffs)):])
        if long_avg is None or short_avg is None:
            return None
        return short_avg - long_avg

    def _load_league_matches(self, league_espn_id: str, cutoff: datetime) -> list[dict]:
        understat_key = _understat_league_key(league_espn_id)
        if understat_key is None or self._understat is None:
            return []

        current_season = cutoff.year if cutoff.month >= 7 else cutoff.year - 1
        combined: list[dict] = []
        for season in (current_season, current_season - 1):
            cache_key = (understat_key, season)
            if cache_key not in self._league_match_cache:
                try:
                    self._league_match_cache[cache_key] = self._understat.fetch_league_matches(understat_key, season)
                except Exception as exc:
                    logger.warning(
                        "Bully engine: unable to fetch Understat matches for %s %s: %s",
                        understat_key,
                        season,
                        exc,
                    )
                    self._league_match_cache[cache_key] = []
            combined.extend(self._league_match_cache[cache_key])
        return combined

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
        home_form: XGFormSnapshot,
        away_form: XGFormSnapshot,
    ) -> tuple[dict[str, float], float]:
        trend_signal = (home_form.trend or 0.0) - (away_form.trend or 0.0)
        form_signal = (home_form.avg_xg_diff or 0.0) - (away_form.avg_xg_diff or 0.0)

        if home_form.trend is None and away_form.trend is None and home_form.avg_xg_diff is None and away_form.avg_xg_diff is None:
            return base_probs, 0.0

        normalized_trend = trend_signal / self._trend_scale if self._trend_scale > 0 else 0.0
        normalized_form = form_signal / 1.5
        composite_signal = _clamp(normalized_trend + (0.25 * normalized_form), -1.0, 1.0)
        shift = composite_signal * self._max_trend_shift
        shift = _clamp(shift, -base_probs["home"], base_probs["away"])

        return (
            {
                "home": base_probs["home"] + shift,
                "draw": base_probs["draw"],
                "away": base_probs["away"] - shift,
            },
            shift,
        )

    def _upsert(self, model_id: int, fixture_id: int, prediction: FixturePrediction) -> None:
        existing = self.session.query(EloFormPrediction).filter_by(model_id=model_id, fixture_id=fixture_id).first()
        payload = {
            "favorite_side": prediction.favorite_side,
            "elo_gap": prediction.elo_gap,
            "is_bully_spot": prediction.is_bully_spot,
            "home_elo": prediction.home_elo,
            "away_elo": prediction.away_elo,
            "home_form_for_avg": prediction.home_form.avg_for,
            "home_form_against_avg": prediction.home_form.avg_against,
            "away_form_for_avg": prediction.away_form.avg_for,
            "away_form_against_avg": prediction.away_form.avg_against,
            "home_xg_diff_avg": prediction.home_form.avg_xg_diff,
            "away_xg_diff_avg": prediction.away_form.avg_xg_diff,
            "home_xg_trend": prediction.home_form.trend,
            "away_xg_trend": prediction.away_form.trend,
            "home_xg_matches_used": prediction.home_form.matches_used,
            "away_xg_matches_used": prediction.away_form.matches_used,
            "trend_adjustment": prediction.trend_adjustment,
            "home_probability": prediction.probabilities["home"],
            "draw_probability": prediction.probabilities["draw"],
            "away_probability": prediction.probabilities["away"],
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
