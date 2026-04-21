from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import numpy as np
from sqlalchemy import and_, or_

from app.db.models import EloFormPrediction, Fixture, FormCache, League, Result, Team

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
GENERIC_HOME_GOALS = 1.52
GENERIC_AWAY_GOALS = 1.18
MIN_EXPECTED_GOALS = 0.2
MAX_EXPECTED_GOALS = 3.6
LEAGUE_BULLY_XG_DELTA_THRESHOLDS: dict[str, float] = {
    "eng.1": 2.0,
    "esp.1": 1.3,
    "ita.1": 1.4,
    "ger.1": 0.9,
    "fra.1": 1.1,
}

MAX_GOALS_GRID = 10
DEFAULT_RHO = -0.13
MIN_RHO = -0.20
MAX_RHO = -0.05
TEAM_FIT_FULL_WEIGHT_MATCHES = 12
LEAGUE_FIT_FULL_WEIGHT_SAMPLES = 200
MIN_LAMBDA = 0.25
MAX_LAMBDA = 3.50
MIN_ELO_GAP = 120.0
MIN_FAVORITE_LAMBDA = 1.70
MAX_OPPONENT_LAMBDA = 1.30
MIN_JOINT_PROBABILITY = 0.42
MIN_BULLY_SCORE = 60.0
FLOOR_JOINT_PROBABILITY = 0.38
PREFERRED_JOINT_PROBABILITY = 0.50
DEFAULT_LAMBDA_ALPHA = 0.60
DEFAULT_KELLY_FRACTION = 0.25
MIN_SGP_SAMPLES_FOR_CALIBRATION = 100


@dataclass(frozen=True)
class XGFormSnapshot:
    avg_for: float | None
    avg_against: float | None
    avg_xg_diff: float | None
    trend: float | None
    matches_used: int
    source: str = "none"


@dataclass(frozen=True)
class GoalProjection:
    home_expected_goals: float
    away_expected_goals: float
    home_two_plus_probability: float
    away_two_plus_probability: float
    home_clean_sheet_probability: float
    away_clean_sheet_probability: float


@dataclass(frozen=True)
class TeamForm:
    team_name: str
    xg_for: Optional[float] = None
    xg_against: Optional[float] = None
    goals_for: Optional[float] = None
    goals_against: Optional[float] = None
    shots_for: Optional[float] = None
    shots_against: Optional[float] = None
    big_chances_for: Optional[float] = None
    big_chances_against: Optional[float] = None
    matches_used: int = 0
    source: str = "none"


@dataclass(frozen=True)
class LeagueFit:
    league_name: str
    home_advantage_elo: float
    draw_intercept: float
    draw_slope: float
    draw_baseline_probability: float
    avg_home_goals: float
    avg_away_goals: float
    avg_total_goals: float
    rho: float
    samples_used: int


@dataclass(frozen=True)
class MarketLine:
    decimal_odds_joint: Optional[float] = None
    decimal_odds_joint_complement: Optional[float] = None
    moneyline_favorite_odds: Optional[float] = None
    moneyline_opposite_odds: Optional[float] = None
    team_total_over_1_5_odds: Optional[float] = None
    team_total_under_1_5_odds: Optional[float] = None


@dataclass(frozen=True)
class V3Prediction:
    favorite_side: str
    favorite_team: str
    underdog_team: str
    elo_gap: float
    lambda_favorite: float
    lambda_underdog: float
    lambda_form: str
    p_favorite_win: float
    p_draw: float
    p_underdog_win: float
    p_favorite_2plus: float
    p_favorite_clean_sheet: float
    p_joint_raw: float
    p_joint_after_residual: float
    p_joint: float
    calibrated: bool
    residual_applied: bool
    bully_score: float
    attack_score: float
    control_score: float
    volatility_score: float
    fair_odds_joint_decimal: float
    market_prob_vig_free: Optional[float]
    market_source: str
    edge_vs_market: Optional[float]
    kelly_stake_fraction: Optional[float]
    kelly_stake_flat: Optional[float]
    is_bully_candidate: bool
    is_bet_candidate: bool
    confidence_tier: str
    data_quality: str
    gate_reasons: tuple[str, ...]
    gate_summary: dict[str, object]
    research_mode_active: bool
    reduced_confidence: bool
    league: LeagueFit


@dataclass(frozen=True)
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
    v3: V3Prediction


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
    probability = _clamp(probability, 1e-4, 1.0 - 1e-4)
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


def _dc_tau(h: int, a: int, lam_h: float, lam_a: float, rho: float) -> float:
    if h == 0 and a == 0:
        return 1.0 - lam_h * lam_a * rho
    if h == 1 and a == 0:
        return 1.0 + lam_a * rho
    if h == 0 and a == 1:
        return 1.0 + lam_h * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def build_dc_score_matrix(
    lambda_home: float,
    lambda_away: float,
    rho: float = DEFAULT_RHO,
    max_goals: int = MAX_GOALS_GRID,
) -> np.ndarray:
    n = max_goals + 1
    matrix = np.zeros((n, n))
    for h in range(n):
        for a in range(n):
            pmf = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
            matrix[h, a] = _dc_tau(h, a, lambda_home, lambda_away, rho) * pmf
    total = matrix.sum()
    if total > 0:
        matrix /= total
    return matrix


def _probabilities_from_matrix(matrix: np.ndarray, favorite_is_home: bool) -> dict[str, float]:
    n = matrix.shape[0]
    p_home = p_draw = p_away = 0.0
    p_fav_2plus = 0.0
    p_fav_clean_sheet = 0.0
    p_joint = 0.0

    for h in range(n):
        for a in range(n):
            p = float(matrix[h, a])
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p

            if favorite_is_home:
                fav_g, und_g, fav_wins = h, a, h > a
            else:
                fav_g, und_g, fav_wins = a, h, a > h

            if fav_g >= 2:
                p_fav_2plus += p
                if fav_wins:
                    p_joint += p
            if und_g == 0:
                p_fav_clean_sheet += p

    return {
        "p_home_win": p_home,
        "p_draw": p_draw,
        "p_away_win": p_away,
        "p_favorite_win": p_home if favorite_is_home else p_away,
        "p_underdog_win": p_away if favorite_is_home else p_home,
        "p_favorite_2plus": p_fav_2plus,
        "p_favorite_clean_sheet": p_fav_clean_sheet,
        "p_joint": p_joint,
    }


def _goal_projection_from_matrix(matrix: np.ndarray, lambda_home: float, lambda_away: float) -> GoalProjection:
    return GoalProjection(
        home_expected_goals=lambda_home,
        away_expected_goals=lambda_away,
        home_two_plus_probability=float(matrix[2:, :].sum()),
        away_two_plus_probability=float(matrix[:, 2:].sum()),
        home_clean_sheet_probability=float(matrix[:, 0].sum()),
        away_clean_sheet_probability=float(matrix[0, :].sum()),
    )


def goal_projection_from_lambdas(
    *,
    favorite_side: str,
    lambda_favorite: float,
    lambda_underdog: float,
    rho: float = DEFAULT_RHO,
    max_goals: int = MAX_GOALS_GRID,
) -> GoalProjection:
    lambda_home = lambda_favorite if favorite_side == "home" else lambda_underdog
    lambda_away = lambda_underdog if favorite_side == "home" else lambda_favorite
    matrix = build_dc_score_matrix(lambda_home=lambda_home, lambda_away=lambda_away, rho=rho, max_goals=max_goals)
    return _goal_projection_from_matrix(matrix, lambda_home, lambda_away)


def _safe(value: Optional[float], default: float) -> float:
    return default if value is None else float(value)


def _shrink(observed: float, prior: float, n_matches: int) -> float:
    if n_matches <= 0:
        return prior
    weight = min(1.0, n_matches / TEAM_FIT_FULL_WEIGHT_MATCHES)
    return weight * observed + (1.0 - weight) * prior


def _estimate_lambdas(
    favorite: TeamForm,
    underdog: TeamForm,
    *,
    favorite_is_home: bool,
    league: LeagueFit,
    form: str = "symmetric",
    alpha: float = DEFAULT_LAMBDA_ALPHA,
) -> tuple[float, float]:
    if favorite_is_home:
        fav_off_prior = league.avg_home_goals
        fav_def_prior = league.avg_away_goals
        und_off_prior = league.avg_away_goals
        und_def_prior = league.avg_home_goals
    else:
        fav_off_prior = league.avg_away_goals
        fav_def_prior = league.avg_home_goals
        und_off_prior = league.avg_home_goals
        und_def_prior = league.avg_away_goals

    fav_off_obs = _safe(favorite.xg_for, _safe(favorite.goals_for, fav_off_prior))
    fav_def_obs = _safe(favorite.xg_against, _safe(favorite.goals_against, fav_def_prior))
    und_off_obs = _safe(underdog.xg_for, _safe(underdog.goals_for, und_off_prior))
    und_def_obs = _safe(underdog.xg_against, _safe(underdog.goals_against, und_def_prior))

    fav_off = _shrink(fav_off_obs, fav_off_prior, favorite.matches_used)
    fav_def = _shrink(fav_def_obs, fav_def_prior, favorite.matches_used)
    und_off = _shrink(und_off_obs, und_off_prior, underdog.matches_used)
    und_def = _shrink(und_def_obs, und_def_prior, underdog.matches_used)

    fav_off_safe = max(fav_off, 0.2)
    fav_def_safe = max(fav_def, 0.2)
    und_off_safe = max(und_off, 0.2)
    und_def_safe = max(und_def, 0.2)

    if form == "attack_weighted":
        alpha_eff = _clamp(alpha, 0.30, 0.80)
        lam_fav = (fav_off_safe ** alpha_eff) * (und_def_safe ** (1.0 - alpha_eff))
    elif form == "symmetric":
        alpha_eff = 0.50
        lam_fav = math.sqrt(fav_off_safe * und_def_safe)
    else:
        raise ValueError(f"Unknown lambda form: {form!r}")

    lam_und = math.sqrt(und_off_safe * fav_def_safe)

    if form == "attack_weighted":
        baseline_fav = (fav_off_prior ** alpha_eff) * (und_def_prior ** (1.0 - alpha_eff))
    else:
        baseline_fav = math.sqrt(fav_off_prior * und_def_prior)
    baseline_und = math.sqrt(und_off_prior * fav_def_prior)

    if baseline_fav > 0:
        lam_fav *= fav_off_prior / baseline_fav
    if baseline_und > 0:
        lam_und *= und_off_prior / baseline_und

    return _clamp(lam_fav, MIN_LAMBDA, MAX_LAMBDA), _clamp(lam_und, MIN_LAMBDA, MAX_LAMBDA)


def _bully_score(favorite: TeamForm, underdog: TeamForm, elo_gap: float) -> float:
    fav_xgd = _safe(favorite.xg_for, _safe(favorite.goals_for, 1.2)) - _safe(
        favorite.xg_against, _safe(favorite.goals_against, 1.2)
    )
    dog_xgd = _safe(underdog.xg_for, _safe(underdog.goals_for, 1.0)) - _safe(
        underdog.xg_against, _safe(underdog.goals_against, 1.3)
    )
    xgd_gap = fav_xgd - dog_xgd

    fav_attack = _safe(favorite.xg_for, _safe(favorite.goals_for, 1.2))
    dog_concede = _safe(underdog.xg_against, _safe(underdog.goals_against, 1.3))
    attack_gap = fav_attack - dog_concede

    fav_def = _safe(favorite.xg_against, _safe(favorite.goals_against, 1.1))
    dog_attack = _safe(underdog.xg_for, _safe(underdog.goals_for, 1.0))
    defense_edge = dog_attack - fav_def

    elo_comp = 100.0 * _clamp(elo_gap / 250.0, 0.0, 1.0)
    xgd_comp = 100.0 * _sigmoid(1.15 * xgd_gap)
    attack_comp = 100.0 * _sigmoid(1.10 * attack_gap)
    defense_comp = 100.0 * _sigmoid(-1.10 * defense_edge)

    return _clamp(
        0.32 * elo_comp + 0.28 * xgd_comp + 0.25 * attack_comp + 0.15 * defense_comp,
        0.0,
        100.0,
    )


def _attack_score(favorite: TeamForm, underdog: TeamForm) -> float:
    fav_xgf = _safe(favorite.xg_for, _safe(favorite.goals_for, 1.2))
    dog_xga = _safe(underdog.xg_against, _safe(underdog.goals_against, 1.3))
    shots_for = _safe(favorite.shots_for, 12.0)
    big_for = _safe(favorite.big_chances_for, 1.5)

    xg_s = 100.0 * _sigmoid((fav_xgf - 1.35) * 1.6)
    opp_f = 100.0 * _sigmoid((dog_xga - 1.35) * 1.6)
    shots_s = 100.0 * _sigmoid((shots_for - 12.5) * 0.22)
    big_s = 100.0 * _sigmoid((big_for - 1.6) * 0.9)

    return _clamp(0.42 * xg_s + 0.28 * opp_f + 0.18 * shots_s + 0.12 * big_s, 0.0, 100.0)


def _control_score(favorite: TeamForm, underdog: TeamForm) -> float:
    fav_xga = _safe(favorite.xg_against, _safe(favorite.goals_against, 1.1))
    dog_xgf = _safe(underdog.xg_for, _safe(underdog.goals_for, 1.0))
    dog_shots = _safe(underdog.shots_for, 10.5)
    dog_big = _safe(underdog.big_chances_for, 1.2)

    s1 = 100.0 * _sigmoid((1.10 - fav_xga) * 1.7)
    s2 = 100.0 * _sigmoid((1.10 - dog_xgf) * 1.7)
    s3 = 100.0 * _sigmoid((11.0 - dog_shots) * 0.20)
    s4 = 100.0 * _sigmoid((1.25 - dog_big) * 0.90)

    return _clamp(0.38 * s1 + 0.30 * s2 + 0.18 * s3 + 0.14 * s4, 0.0, 100.0)


def _volatility_score(favorite: TeamForm, underdog: TeamForm, league: LeagueFit) -> float:
    fav_xga = _safe(favorite.xg_against, _safe(favorite.goals_against, 1.1))
    dog_xgf = _safe(underdog.xg_for, _safe(underdog.goals_for, 1.0))
    lg_tot = league.avg_total_goals

    c1 = 100.0 * _sigmoid((fav_xga - 1.15) * 1.4)
    c2 = 100.0 * _sigmoid((dog_xgf - 1.10) * 1.4)
    c3 = 100.0 * _sigmoid((lg_tot - 2.85) * 1.6)

    return _clamp(0.42 * c1 + 0.33 * c2 + 0.25 * c3, 0.0, 100.0)


def _devig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
    if odds_a <= 1.0 or odds_b <= 1.0:
        raise ValueError("odds must be > 1.0")
    imp_a = 1.0 / odds_a
    imp_b = 1.0 / odds_b
    overround = imp_a + imp_b
    return imp_a / overround, imp_b / overround


def _market_joint_prob_vig_free(
    market: MarketLine,
    favorite_is_home: bool,
    sgp_calibrator: Optional["SGPCorrelationCalibrator"] = None,
) -> tuple[Optional[float], str]:
    if market.decimal_odds_joint and market.decimal_odds_joint_complement:
        p_joint, _ = _devig_two_way(market.decimal_odds_joint, market.decimal_odds_joint_complement)
        return p_joint, "direct_two_sided"

    if market.decimal_odds_joint:
        return (1.0 / market.decimal_odds_joint) / 1.04, "direct_one_sided"

    have_ml = market.moneyline_favorite_odds and market.moneyline_opposite_odds
    have_tt = market.team_total_over_1_5_odds and market.team_total_under_1_5_odds
    if have_ml and have_tt:
        p_win_fair, _ = _devig_two_way(market.moneyline_favorite_odds, market.moneyline_opposite_odds)
        p_over_fair, _ = _devig_two_way(market.team_total_over_1_5_odds, market.team_total_under_1_5_odds)
        naive_product = p_win_fair * p_over_fair
        factor = sgp_calibrator.factor if sgp_calibrator is not None else 0.75
        return _clamp(naive_product / factor, 0.0, 0.99), "synthesized"

    return None, "unavailable"


def _kelly_with_confidence_discount(
    probability: float,
    decimal_odds: float,
    kelly_fraction: float,
    *,
    floor: float = FLOOR_JOINT_PROBABILITY,
    preferred: float = PREFERRED_JOINT_PROBABILITY,
) -> float:
    if decimal_odds <= 1.0 or not (0.0 < probability < 1.0):
        return 0.0

    b = decimal_odds - 1.0
    edge = b * probability - (1.0 - probability)
    if edge <= 0:
        return 0.0

    base_stake = (edge / b) * kelly_fraction
    if probability >= preferred:
        return base_stake
    if probability <= floor:
        return 0.0

    ramp = (probability - floor) / (preferred - floor)
    return base_stake * ramp


def kelly_fraction_v3(probability: float, decimal_odds: float, fraction: float = DEFAULT_KELLY_FRACTION) -> float:
    if decimal_odds <= 1.0 or not (0.0 < probability < 1.0):
        return 0.0
    b = decimal_odds - 1.0
    edge = b * probability - (1.0 - probability)
    if edge <= 0:
        return 0.0
    return (edge / b) * fraction


class JointProbabilityCalibrator:
    def __init__(self):
        self._iso = None
        self._trained = False

    def fit(self, raw_probs: np.ndarray, outcomes: np.ndarray) -> None:
        from sklearn.isotonic import IsotonicRegression

        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_probs, outcomes)
        self._iso = iso
        self._trained = True

    def transform(self, raw_prob: float) -> float:
        if not self._trained:
            return raw_prob
        return float(self._iso.transform([raw_prob])[0])

    @property
    def is_trained(self) -> bool:
        return self._trained


class ResidualProbabilityHead:
    def __init__(self):
        self._coef = None
        self._intercept = 0.0
        self._logit_raw_coef = 1.0
        self._trained = False

    def fit(
        self,
        raw_probs: np.ndarray,
        feature_matrix: np.ndarray,
        outcomes: np.ndarray,
        *,
        l2_regularization: float = 1.0,
    ) -> None:
        from sklearn.linear_model import LogisticRegression

        if feature_matrix.shape[1] != 4:
            raise ValueError(f"expected 4 features, got {feature_matrix.shape[1]}")
        if len(raw_probs) < 50:
            raise ValueError(f"need at least 50 training samples, got {len(raw_probs)}")

        clipped = np.clip(raw_probs, 1e-4, 1.0 - 1e-4)
        logit_raw = np.log(clipped / (1.0 - clipped))
        x = (feature_matrix - 50.0) / 50.0
        x_aug = np.column_stack([x, logit_raw])

        lr = LogisticRegression(
            C=1.0 / max(l2_regularization, 1e-6),
            fit_intercept=True,
            solver="lbfgs",
            max_iter=500,
        )
        lr.fit(x_aug, outcomes)
        self._coef = lr.coef_[0][:4].copy()
        self._logit_raw_coef = float(lr.coef_[0][4])
        self._intercept = float(lr.intercept_[0])
        self._trained = True

    def transform(
        self,
        raw_prob: float,
        bully_score: float,
        attack_score: float,
        control_score: float,
        volatility_score: float,
    ) -> float:
        if not self._trained:
            return raw_prob

        clipped = max(1e-4, min(1.0 - 1e-4, raw_prob))
        logit_raw = math.log(clipped / (1.0 - clipped))
        features = np.array([bully_score, attack_score, control_score, volatility_score])
        x = (features - 50.0) / 50.0
        logit_adj = self._intercept + self._logit_raw_coef * logit_raw + float(np.dot(self._coef, x))
        return _sigmoid(logit_adj)

    @property
    def is_trained(self) -> bool:
        return self._trained


class SGPCorrelationCalibrator:
    def __init__(self, default_factor: float = 0.75):
        self._factor = default_factor
        self._trained = False
        self._samples_used = 0

    def fit(self, naive_products: np.ndarray, observed_joints: np.ndarray) -> None:
        if len(naive_products) != len(observed_joints):
            raise ValueError("length mismatch")
        if len(naive_products) < MIN_SGP_SAMPLES_FOR_CALIBRATION:
            raise ValueError(
                f"need at least {MIN_SGP_SAMPLES_FOR_CALIBRATION} samples, got {len(naive_products)}"
            )

        mask = (naive_products > 0) & (observed_joints > 0) & (observed_joints < 1)
        if mask.sum() < 20:
            raise ValueError("not enough valid samples after filtering")

        ratios = naive_products[mask] / observed_joints[mask]
        self._factor = float(np.median(ratios))
        self._trained = True
        self._samples_used = int(mask.sum())

    @property
    def factor(self) -> float:
        return self._factor

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def samples_used(self) -> int:
        return self._samples_used


class BullyEngineV3:
    def __init__(
        self,
        *,
        calibrator: Optional[JointProbabilityCalibrator] = None,
        residual_head: Optional[ResidualProbabilityHead] = None,
        sgp_calibrator: Optional[SGPCorrelationCalibrator] = None,
        lambda_form: str = "attack_weighted",
        lambda_alpha: float = DEFAULT_LAMBDA_ALPHA,
        max_goals: int = MAX_GOALS_GRID,
        min_elo_gap: float = MIN_ELO_GAP,
        min_favorite_lambda: float = MIN_FAVORITE_LAMBDA,
        max_opponent_lambda: float = MAX_OPPONENT_LAMBDA,
        min_joint_probability: float = MIN_JOINT_PROBABILITY,
        min_bully_score: float = MIN_BULLY_SCORE,
        floor_joint_probability: float = FLOOR_JOINT_PROBABILITY,
        preferred_joint_probability: float = PREFERRED_JOINT_PROBABILITY,
        kelly_fraction: float = DEFAULT_KELLY_FRACTION,
        require_trained_calibrator_for_tier_a: bool = True,
        block_bets_on_synthesized_sgp_without_calibration: bool = True,
        research_mode: bool = False,
    ):
        self.calibrator = calibrator or JointProbabilityCalibrator()
        self.residual_head = residual_head or ResidualProbabilityHead()
        self.sgp_calibrator = sgp_calibrator or SGPCorrelationCalibrator()

        if lambda_form not in ("symmetric", "attack_weighted"):
            raise ValueError(f"lambda_form must be 'symmetric' or 'attack_weighted', got {lambda_form!r}")
        self.lambda_form = lambda_form
        self.lambda_alpha = lambda_alpha
        self.max_goals = max_goals
        self.min_elo_gap = min_elo_gap
        self.min_favorite_lambda = min_favorite_lambda
        self.max_opponent_lambda = max_opponent_lambda
        self.min_joint_probability = min_joint_probability
        self.min_bully_score = min_bully_score
        self.floor_joint_probability = floor_joint_probability
        self.preferred_joint_probability = preferred_joint_probability
        self.kelly_fraction = kelly_fraction
        self.require_trained_calibrator_for_tier_a = require_trained_calibrator_for_tier_a
        self.block_synthesized_sgp = block_bets_on_synthesized_sgp_without_calibration
        self.research_mode = research_mode

    def predict(
        self,
        *,
        home_team: TeamForm,
        away_team: TeamForm,
        home_elo: float,
        away_elo: float,
        league: LeagueFit,
        market: Optional[MarketLine] = None,
    ) -> V3Prediction:
        effective_home_elo = home_elo + league.home_advantage_elo
        favorite_is_home = effective_home_elo >= away_elo
        favorite_side = "home" if favorite_is_home else "away"
        elo_gap = abs(effective_home_elo - away_elo)

        favorite = home_team if favorite_is_home else away_team
        underdog = away_team if favorite_is_home else home_team

        lambda_favorite, lambda_underdog = _estimate_lambdas(
            favorite,
            underdog,
            favorite_is_home=favorite_is_home,
            league=league,
            form=self.lambda_form,
            alpha=self.lambda_alpha,
        )
        lambda_home = lambda_favorite if favorite_is_home else lambda_underdog
        lambda_away = lambda_underdog if favorite_is_home else lambda_favorite

        matrix = build_dc_score_matrix(
            lambda_home=lambda_home,
            lambda_away=lambda_away,
            rho=_clamp(league.rho, MIN_RHO, MAX_RHO),
            max_goals=self.max_goals,
        )
        probs = _probabilities_from_matrix(matrix, favorite_is_home)
        p_joint_raw = probs["p_joint"]

        bully = _bully_score(favorite, underdog, elo_gap)
        attack = _attack_score(favorite, underdog)
        control = _control_score(favorite, underdog)
        volatility = _volatility_score(favorite, underdog, league)

        p_joint_after_residual = self.residual_head.transform(
            p_joint_raw,
            bully,
            attack,
            control,
            volatility,
        )
        residual_applied = self.residual_head.is_trained
        p_joint = self.calibrator.transform(p_joint_after_residual)

        data_quality = self._data_quality(favorite, underdog, league)
        fair_odds = 1.0 / max(p_joint, 1e-9)
        market_prob: Optional[float] = None
        market_source = "unavailable"
        edge: Optional[float] = None
        kelly_soft: Optional[float] = None
        kelly_flat: Optional[float] = None
        if market is not None:
            market_prob, market_source = _market_joint_prob_vig_free(
                market,
                favorite_is_home,
                self.sgp_calibrator,
            )
            if market_prob is not None:
                edge = p_joint - market_prob
                if market.decimal_odds_joint:
                    kelly_soft = _kelly_with_confidence_discount(
                        p_joint,
                        market.decimal_odds_joint,
                        self.kelly_fraction,
                        floor=self.floor_joint_probability,
                        preferred=self.preferred_joint_probability,
                    )
                    kelly_flat = kelly_fraction_v3(
                        p_joint,
                        market.decimal_odds_joint,
                        self.kelly_fraction,
                    )

        gates: dict[str, dict[str, object]] = {}
        gate_reasons: list[str] = []

        def _record(name: str, passed: bool | None, reason_if_failed: str) -> None:
            gates[name] = {"passed": passed, "reason": None if passed else reason_if_failed}
            if passed is False:
                gate_reasons.append(reason_if_failed)

        _record("bully_score", bully >= self.min_bully_score, f"bully_score {bully:.1f} < {self.min_bully_score:.1f}")
        _record("elo_gap", elo_gap >= self.min_elo_gap, f"elo_gap {elo_gap:.0f} < {self.min_elo_gap:.0f}")
        _record(
            "lambda_favorite",
            lambda_favorite >= self.min_favorite_lambda,
            f"lambda_favorite {lambda_favorite:.2f} < {self.min_favorite_lambda:.2f}",
        )
        _record(
            "lambda_underdog",
            lambda_underdog <= self.max_opponent_lambda,
            f"lambda_underdog {lambda_underdog:.2f} > {self.max_opponent_lambda:.2f}",
        )
        _record("p_joint", p_joint >= self.min_joint_probability, f"p_joint {p_joint:.3f} < {self.min_joint_probability:.3f}")
        _record("data_quality", data_quality != "low", "data_quality low")
        if edge is not None:
            _record("edge", edge > 0, f"edge {edge:+.3f} <= 0 vs vig-free market")
        else:
            gates["edge"] = {"passed": None, "reason": "no market data provided"}

        synth_block_active = (
            self.block_synthesized_sgp
            and market_source == "synthesized"
            and not self.sgp_calibrator.is_trained
        )
        _record(
            "sgp_synthesis",
            not synth_block_active,
            "synthesized SGP price without trained correlation calibrator",
        )

        gate_summary = {
            "total_gates": len(gates),
            "passed": sum(1 for gate in gates.values() if gate["passed"] is True),
            "failed": sum(1 for gate in gates.values() if gate["passed"] is False),
            "n_a": sum(1 for gate in gates.values() if gate["passed"] is None),
            "details": gates,
        }

        is_bully_candidate = bully >= self.min_bully_score and elo_gap >= self.min_elo_gap
        research_mode_active = bool(self.research_mode)
        is_bet_candidate = False if research_mode_active else len(gate_reasons) == 0

        confidence_tier = self._confidence_tier(
            p_joint=p_joint,
            bully_score=bully,
            volatility_score=volatility,
            data_quality=data_quality,
        )
        reduced_confidence = (
            data_quality != "high"
            or not self.calibrator.is_trained
            or favorite.matches_used < 5
            or underdog.matches_used < 5
        )

        return V3Prediction(
            favorite_side=favorite_side,
            favorite_team=favorite.team_name,
            underdog_team=underdog.team_name,
            elo_gap=elo_gap,
            lambda_favorite=lambda_favorite,
            lambda_underdog=lambda_underdog,
            lambda_form=self.lambda_form,
            p_favorite_win=probs["p_favorite_win"],
            p_draw=probs["p_draw"],
            p_underdog_win=probs["p_underdog_win"],
            p_favorite_2plus=probs["p_favorite_2plus"],
            p_favorite_clean_sheet=probs["p_favorite_clean_sheet"],
            p_joint_raw=p_joint_raw,
            p_joint_after_residual=p_joint_after_residual,
            p_joint=p_joint,
            calibrated=self.calibrator.is_trained,
            residual_applied=residual_applied,
            bully_score=bully,
            attack_score=attack,
            control_score=control,
            volatility_score=volatility,
            fair_odds_joint_decimal=fair_odds,
            market_prob_vig_free=market_prob,
            market_source=market_source,
            edge_vs_market=edge,
            kelly_stake_fraction=kelly_soft,
            kelly_stake_flat=kelly_flat,
            is_bully_candidate=is_bully_candidate,
            is_bet_candidate=is_bet_candidate,
            confidence_tier=confidence_tier,
            data_quality=data_quality,
            gate_reasons=tuple(gate_reasons),
            gate_summary=gate_summary,
            research_mode_active=research_mode_active,
            reduced_confidence=reduced_confidence,
            league=league,
        )

    def _data_quality(self, favorite: TeamForm, underdog: TeamForm, league: LeagueFit) -> str:
        if (
            favorite.source == "xg"
            and underdog.source == "xg"
            and favorite.matches_used >= 5
            and underdog.matches_used >= 5
            and league.samples_used >= LEAGUE_FIT_FULL_WEIGHT_SAMPLES
        ):
            return "high"
        if (
            favorite.source != "none"
            and underdog.source != "none"
            and favorite.matches_used >= 3
            and underdog.matches_used >= 3
        ):
            return "medium"
        return "low"

    def _confidence_tier(
        self,
        *,
        p_joint: float,
        bully_score: float,
        volatility_score: float,
        data_quality: str,
    ) -> str:
        if data_quality == "low":
            return "D"
        tier_a_eligible = (
            p_joint >= 0.52
            and bully_score >= 75
            and volatility_score <= 45
            and data_quality == "high"
            and (self.calibrator.is_trained or not self.require_trained_calibrator_for_tier_a)
        )
        if tier_a_eligible:
            return "A"
        if p_joint >= 0.45 and bully_score >= 65 and volatility_score <= 58:
            return "B"
        if p_joint >= 0.42 and bully_score >= 60:
            return "C"
        return "D"


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
        engine: BullyEngineV3 | None = None,
        lambda_form: str = "attack_weighted",
        lambda_alpha: float = DEFAULT_LAMBDA_ALPHA,
        research_mode: bool = False,
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
        self._bully_xg_overlay_enabled = bully_xg_overlay_enabled
        self._engine = engine or BullyEngineV3(
            lambda_form=lambda_form,
            lambda_alpha=lambda_alpha,
            research_mode=research_mode,
        )

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
        league_fit = self._league_fit(league, cutoff)
        ratings = self._ratings_for_league(league.id, cutoff, league_fit.home_advantage_elo)
        home_elo = ratings.get(fixture.home_team_id, BASE_ELO)
        away_elo = ratings.get(fixture.away_team_id, BASE_ELO)

        home_form = self._recent_xg_form(league, fixture, fixture.home_team_id, cutoff)
        away_form = self._recent_xg_form(league, fixture, fixture.away_team_id, cutoff)

        v3_prediction = self._engine.predict(
            home_team=self._team_form(fixture.home_team_id, home_form),
            away_team=self._team_form(fixture.away_team_id, away_form),
            home_elo=home_elo,
            away_elo=away_elo,
            league=league_fit,
            market=None,
        )
        goals = goal_projection_from_lambdas(
            favorite_side=v3_prediction.favorite_side,
            lambda_favorite=v3_prediction.lambda_favorite,
            lambda_underdog=v3_prediction.lambda_underdog,
            rho=league_fit.rho,
            max_goals=self._engine.max_goals,
        )

        return FixturePrediction(
            favorite_side=v3_prediction.favorite_side,
            elo_gap=v3_prediction.elo_gap,
            is_bully_spot=v3_prediction.is_bully_candidate,
            home_elo=home_elo,
            away_elo=away_elo,
            home_form=home_form,
            away_form=away_form,
            trend_adjustment=self._trend_adjustment(home_form, away_form),
            probabilities={
                "home": v3_prediction.p_favorite_win if v3_prediction.favorite_side == "home" else v3_prediction.p_underdog_win,
                "draw": v3_prediction.p_draw,
                "away": v3_prediction.p_favorite_win if v3_prediction.favorite_side == "away" else v3_prediction.p_underdog_win,
            },
            goals=goals,
            league_fit=league_fit,
            v3=v3_prediction,
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

    def _league_fit(self, league: League, cutoff: datetime | None) -> LeagueFit:
        key = (league.id, self._cache_key(cutoff))
        cached = self._league_fit_cache.get(key)
        if cached is not None:
            return cached

        rows = self._historical_rows(league.id, cutoff)
        home_advantage_elo = self._fit_home_advantage_elo(rows)
        global_draw_intercept, global_draw_slope, global_draw_baseline = self._global_draw_fit(cutoff)
        draw_intercept, draw_slope, draw_baseline_probability = self._fit_draw_model(
            rows,
            home_advantage_elo,
            prior_intercept=global_draw_intercept,
            prior_slope=global_draw_slope,
            prior_draw_rate=global_draw_baseline,
        )
        avg_home_goals, avg_away_goals, goal_samples = fit_league_goal_rates(self.session, league.id, cutoff)
        fit = LeagueFit(
            league_name=league.name,
            home_advantage_elo=home_advantage_elo,
            draw_intercept=draw_intercept,
            draw_slope=draw_slope,
            draw_baseline_probability=draw_baseline_probability,
            avg_home_goals=avg_home_goals,
            avg_away_goals=avg_away_goals,
            avg_total_goals=avg_home_goals + avg_away_goals,
            rho=DEFAULT_RHO,
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
        clipped_share = _clamp(home_score_share, 0.05, 0.95)
        fitted = 400.0 * math.log10(clipped_share / (1.0 - clipped_share))
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
        source = "xg"
        if not observations:
            observations = self._result_proxy_observations(team_id, cutoff)
            source = "goals_proxy"

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

        has_xg = cache.xg_scored_avg is not None and cache.xg_conceded_avg is not None
        avg_for = cache.xg_scored_avg if cache.xg_scored_avg is not None else cache.goals_scored_avg
        avg_against = cache.xg_conceded_avg if cache.xg_conceded_avg is not None else cache.goals_conceded_avg
        avg_diff = None if avg_for is None or avg_against is None else avg_for - avg_against
        return XGFormSnapshot(
            avg_for=avg_for,
            avg_against=avg_against,
            avg_xg_diff=avg_diff,
            trend=0.0 if avg_diff is not None else None,
            matches_used=cache.matches_count or 0,
            source="xg" if has_xg else "cache",
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

    def _team_form(self, team_id: int, snapshot: XGFormSnapshot) -> TeamForm:
        if snapshot.source == "xg":
            return TeamForm(
                team_name=self._team_name(team_id),
                xg_for=snapshot.avg_for,
                xg_against=snapshot.avg_against,
                goals_for=snapshot.avg_for,
                goals_against=snapshot.avg_against,
                matches_used=snapshot.matches_used,
                source="xg",
            )
        if snapshot.source == "goals_proxy":
            return TeamForm(
                team_name=self._team_name(team_id),
                goals_for=snapshot.avg_for,
                goals_against=snapshot.avg_against,
                matches_used=snapshot.matches_used,
                source="goals_proxy",
            )
        if snapshot.source == "cache":
            return TeamForm(
                team_name=self._team_name(team_id),
                goals_for=snapshot.avg_for,
                goals_against=snapshot.avg_against,
                matches_used=snapshot.matches_used,
                source="cache",
            )
        return TeamForm(team_name=self._team_name(team_id), matches_used=snapshot.matches_used, source="none")

    def _trend_adjustment(self, home_form: XGFormSnapshot, away_form: XGFormSnapshot) -> float:
        trend_signal = (home_form.trend or 0.0) - (away_form.trend or 0.0)
        form_signal = (home_form.avg_xg_diff or 0.0) - (away_form.avg_xg_diff or 0.0)
        if (
            home_form.trend is None
            and away_form.trend is None
            and home_form.avg_xg_diff is None
            and away_form.avg_xg_diff is None
        ):
            return 0.0
        normalized_trend = trend_signal / self._trend_scale if self._trend_scale > 0 else 0.0
        normalized_form = form_signal / 1.5
        composite_signal = _clamp(normalized_trend + (0.25 * normalized_form), -1.0, 1.0)
        return composite_signal * self._max_trend_shift

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
            "p_joint": prediction.v3.p_joint,
            "p_joint_raw": prediction.v3.p_joint_raw,
            "lambda_favorite": prediction.v3.lambda_favorite,
            "lambda_underdog": prediction.v3.lambda_underdog,
            "market_source": prediction.v3.market_source,
            "gate_summary": json.dumps(prediction.v3.gate_summary, sort_keys=True),
            "research_mode_active": prediction.v3.research_mode_active,
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


def prediction_model_probability(prediction: EloFormPrediction) -> float:
    if prediction.p_joint is not None:
        return prediction.p_joint
    return prediction.home_probability if prediction.favorite_side == "home" else prediction.away_probability


def goal_projection_from_prediction_row(prediction: EloFormPrediction) -> GoalProjection:
    if prediction.lambda_favorite is not None and prediction.lambda_underdog is not None:
        return goal_projection_from_lambdas(
            favorite_side=prediction.favorite_side,
            lambda_favorite=prediction.lambda_favorite,
            lambda_underdog=prediction.lambda_underdog,
        )
    return project_match_goal_probs(
        home_probability=prediction.home_probability,
        draw_probability=prediction.draw_probability,
        away_probability=prediction.away_probability,
        home_form_for_avg=prediction.home_form_for_avg,
        home_form_against_avg=prediction.home_form_against_avg,
        away_form_for_avg=prediction.away_form_for_avg,
        away_form_against_avg=prediction.away_form_against_avg,
        home_xg_diff_avg=prediction.home_xg_diff_avg,
        away_xg_diff_avg=prediction.away_xg_diff_avg,
        home_xg_trend=prediction.home_xg_trend,
        away_xg_trend=prediction.away_xg_trend,
    )
