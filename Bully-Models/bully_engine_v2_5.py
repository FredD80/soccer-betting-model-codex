"""
Bully Engine V2.5 — target-hit-rate Elo gate calibrated per league.

DESIGN NOTES (for review)
-------------------------
V2.5 is a minimal fork of V2 with one substantive change: the `elo_gap` filter
is no longer a fixed absolute threshold (V2's 120). Instead, the gate threshold
is computed PER LEAGUE from historical fixture data as the `elo_gap` cutoff
that delivered a target hit rate in the backtest window. The target hit rate
is expressed as "X percentage points over breakeven at your average SGP odds":

    target_hit_rate = (1.0 / assumed_avg_odds) + target_margin_over_breakeven

Example: at 1.55 average odds, breakeven is 64.5%. A 10% margin target = 74.5%.
The engine then looks up the per-league elo_gap cutoff that historically
produced >= 74.5% hit rate among fixtures above that cutoff.

WHY THIS MATTERS
----------------
The cross-league backtest (La Liga, Serie A, EPL, Bundesliga, Ligue 1,
2025-26 season) showed:
  1. Elo delta is a meaningfully stronger correlate of SGP hit rate than xG
     delta across all five leagues.
  2. The magnitude of the Elo signal varies widely: La Liga's hit-avg Elo gap
     is 147, Ligue 1's is 94. A single absolute threshold over-filters some
     leagues and under-filters others.
  3. xG delta correlations ranged from -0.029 (EPL) to 0.142 (La Liga) —
     mostly noise. xG is kept as a lambda-input (it feeds p_joint) but NOT as
     a separate filter gate. The data doesn't support that.

V2 (absolute `elo_gap >= 120`) rejects fixtures inconsistently across leagues.
V2.5 rejects a ROUGHLY EQUAL SHARE of fixtures from each league — whatever
share is needed to clear the target hit rate.

WHAT V2.5 DOES NOT CHANGE FROM V2
---------------------------------
  - Dixon-Coles score matrix as single source of truth
  - Lambda estimation via sqrt(attack * defense) with sample-weighted shrinkage
  - p_joint as the staking target
  - lambda_fav / lambda_und / p_joint gates retain V2's thresholds as defaults
  - JointProbabilityCalibrator interface (isotonic regression skeleton)
  - kelly_fraction helper
  - The engine remains stateless with respect to DB

NEW IN V2.5
-----------
  - LeagueEloHistory dataclass: carries the (elo_gap, hit) pairs per league
    needed to compute the target-hit-rate cutoff. Populated by the backtester
    from historical fixtures with graded outcomes.
  - BullyV2_5Engine constructor accepts:
      * target_margin_over_breakeven (default 0.10)
      * assumed_avg_odds (default 1.55)
      * min_elo_gap_absolute (floor regardless of target, default 120)
      * insufficient_history_policy ("block" | "fallback" | "use_absolute")
  - Prediction reports the computed per-league cutoff and which policy path
    was taken, for auditability.

REFERENCES
----------
Dixon, M.J. & Coles, S.G. (1997). JRSS-C 46(2).
Maher (1982). The Statistician 31(2).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np

from app.dixon_coles import build_score_matrix, moneyline_probability_dc

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Constants (V2 defaults retained; new V2.5 defaults added)
# -----------------------------------------------------------------------------

BASE_ELO = 1500.0
DEFAULT_K_FACTOR = 24.0
MAX_GOALS_GRID = 10

DEFAULT_RHO = -0.13
MIN_RHO = -0.20
MAX_RHO = -0.05

FORM_LOOKBACK_MATCHES = 10
FORM_DECAY_HALFLIFE_MATCHES = 5.0

GENERIC_HOME_GOALS = 1.52
GENERIC_AWAY_GOALS = 1.18
LEAGUE_FIT_FULL_WEIGHT_SAMPLES = 200

TEAM_FIT_FULL_WEIGHT_MATCHES = 15

# V2 absolute gates. Retained as floors / defaults for the non-Elo gates.
MIN_FAVORITE_LAMBDA = 1.70
MAX_OPPONENT_LAMBDA = 1.30
MIN_JOINT_PROBABILITY = 0.38

# V2.5 NEW: target-hit-rate gate parameters.
DEFAULT_TARGET_MARGIN_OVER_BREAKEVEN = 0.10  # 10 percentage points over breakeven
DEFAULT_ASSUMED_AVG_ODDS = 1.55              # typical SGP price in your current data
MIN_ELO_GAP_ABSOLUTE_FLOOR = 120.0           # never go below V2's original threshold
MIN_HISTORY_FIXTURES_FOR_CALIBRATION = 30    # need at least this many fixtures in the
                                             # league's history to trust a target-hit-rate
                                             # cutoff. Fewer = fall back.
MIN_CANDIDATES_ABOVE_CUTOFF = 20             # once we've walked past this few fixtures,
                                             # we can start checking hit rate. Prevents
                                             # tiny-sample false positives (e.g. "top 5
                                             # fixtures all hit, so cutoff there" — 5 is
                                             # noise, not signal).


InsufficientHistoryPolicy = Literal["block", "fallback_absolute", "fallback_percentile"]


# -----------------------------------------------------------------------------
# Dataclasses
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class FormSnapshot:
    """Recent form summary for one team, from kickoff's point of view."""
    xg_for_avg: Optional[float]
    xg_against_avg: Optional[float]
    matches_used: int
    source: str

    @property
    def is_reliable(self) -> bool:
        return self.source == "understat" and self.matches_used >= 5


@dataclass(frozen=True)
class LeagueFit:
    """Per-league fitted parameters with sample counts for auditability."""
    avg_home_goals: float
    avg_away_goals: float
    rho: float
    home_advantage_elo: float
    samples_used: int


@dataclass(frozen=True)
class LeagueEloHistory:
    """
    V2.5 NEW: historical (elo_gap, hit) pairs for a league, used to compute
    the target-hit-rate Elo cutoff.

    Populated by the backtester from graded fixtures. `hits` is the outcome
    of the "favorite wins AND scores 2+" event — NOT moneyline-only.
    """
    league_name: str
    elo_gaps: tuple[float, ...]        # one per historical fixture
    hits: tuple[bool, ...]             # aligned with elo_gaps
    window_start: str                  # ISO date, for audit trail
    window_end: str                    # ISO date, for audit trail

    def __post_init__(self):
        # dataclass(frozen=True) doesn't run __post_init__ auto-validation,
        # but we need the invariant.
        if len(self.elo_gaps) != len(self.hits):
            raise ValueError(
                f"LeagueEloHistory({self.league_name}): elo_gaps length "
                f"{len(self.elo_gaps)} != hits length {len(self.hits)}"
            )

    @property
    def n_fixtures(self) -> int:
        return len(self.elo_gaps)

    @property
    def overall_hit_rate(self) -> float:
        if not self.hits:
            return 0.0
        return sum(1 for h in self.hits if h) / len(self.hits)


@dataclass(frozen=True)
class BullyV2_5Prediction:
    """
    V2.5 prediction output. Extends V2's fields with the target-hit-rate
    calibration diagnostics so the operator can audit WHY a spot did or
    didn't qualify.
    """
    # Identification
    favorite_side: str
    elo_gap: float

    # Scoring rates (unchanged from V2)
    lambda_favorite: float
    lambda_underdog: float

    # Derived probabilities (unchanged from V2)
    p_favorite_win: float
    p_draw: float
    p_underdog_win: float
    p_favorite_2plus: float
    p_favorite_clean_sheet: float
    p_joint: float

    # Spot classification
    is_bully_spot: bool
    bully_filter_reasons: tuple[str, ...]

    # Provenance
    form_source_home: str
    form_source_away: str
    reduced_confidence: bool
    league_fit: LeagueFit

    # V2.5 NEW: target-hit-rate gate diagnostics
    target_hit_rate: float              # computed from margin + odds
    elo_gap_threshold_used: float       # the actual threshold this prediction saw
    elo_gap_threshold_source: str       # "target_hit_rate" | "absolute_floor" |
                                        # "insufficient_history_blocked" |
                                        # "insufficient_history_fallback"
    league_history_n_fixtures: int      # how many fixtures fed the calibration


# -----------------------------------------------------------------------------
# V2.5 NEW: target-hit-rate cutoff computation
# -----------------------------------------------------------------------------

def compute_target_hit_rate(
    margin_over_breakeven: float,
    assumed_avg_odds: float,
) -> float:
    """
    Translate a 'X percentage points over breakeven' target into an absolute
    hit rate. Additive, not multiplicative — i.e. 0.10 margin at 1.55 odds
    (breakeven 0.645) produces 0.745, not 0.710.
    """
    if assumed_avg_odds <= 1.0:
        raise ValueError(f"assumed_avg_odds must be > 1.0, got {assumed_avg_odds}")
    breakeven = 1.0 / assumed_avg_odds
    target = breakeven + margin_over_breakeven
    if not 0.0 < target < 1.0:
        raise ValueError(
            f"Computed target_hit_rate {target} is outside (0, 1); "
            f"check margin_over_breakeven={margin_over_breakeven} "
            f"and assumed_avg_odds={assumed_avg_odds}"
        )
    return target


def compute_elo_gap_cutoff_for_target_hit_rate(
    history: LeagueEloHistory,
    target_hit_rate: float,
    min_candidates_above_cutoff: int = MIN_CANDIDATES_ABOVE_CUTOFF,
) -> Optional[float]:
    """
    Given a league's historical (elo_gap, hit) pairs, find the elo_gap cutoff
    such that the hit rate AMONG fixtures with gap >= cutoff is >= target.

    Algorithm: sort fixtures by elo_gap descending, walk down, tracking
    running hit rate. The cutoff is the SMALLEST gap at which the running
    hit rate is still >= target AND at least min_candidates_above_cutoff
    fixtures have been seen (so we don't get fooled by 3-fixture runs of
    coincidental hits at the top of the distribution).

    Returns None if no cutoff satisfies both conditions — the league's Elo
    signal is too weak to achieve the target at any threshold.
    """
    if history.n_fixtures < min_candidates_above_cutoff:
        return None

    # Sort by elo_gap descending, with hit aligned.
    paired = sorted(
        zip(history.elo_gaps, history.hits),
        key=lambda x: x[0],
        reverse=True,
    )

    # Walk down, tracking running hit rate. The "candidate cutoff" at index i
    # means "admit all fixtures with gap >= paired[i][0]". Running hit rate is
    # computed over paired[0..i] inclusive.
    running_hits = 0
    last_valid_cutoff: Optional[float] = None

    for i, (gap, hit) in enumerate(paired):
        if hit:
            running_hits += 1
        n_so_far = i + 1
        running_hit_rate = running_hits / n_so_far

        if n_so_far < min_candidates_above_cutoff:
            continue  # sample too small to trust, keep looking for more fixtures

        if running_hit_rate >= target_hit_rate:
            last_valid_cutoff = gap
            # keep walking — we might find an even lower cutoff that still clears
        else:
            # hit rate has fallen below target; can't go lower without missing it
            break

    return last_valid_cutoff


# -----------------------------------------------------------------------------
# Shrinkage and lambda estimation (unchanged from V2)
# -----------------------------------------------------------------------------

def _shrink_toward_prior(
    team_value: float,
    prior: float,
    n_matches: int,
    full_weight_n: int = TEAM_FIT_FULL_WEIGHT_MATCHES,
) -> float:
    if n_matches <= 0:
        return prior
    weight = min(1.0, n_matches / full_weight_n)
    return (weight * team_value) + ((1.0 - weight) * prior)


def _estimate_team_lambdas(
    favorite_form: FormSnapshot,
    underdog_form: FormSnapshot,
    *,
    favorite_is_home: bool,
    league_fit: LeagueFit,
) -> tuple[float, float]:
    """
    Unchanged from V2. Kept in-file for self-containment.
    See V2 docstring for derivation of the sqrt form and venue rescale.
    """
    league_h = league_fit.avg_home_goals
    league_a = league_fit.avg_away_goals

    if favorite_is_home:
        fav_offense_prior = league_h
        fav_defense_prior = league_a
        und_offense_prior = league_a
        und_defense_prior = league_h
    else:
        fav_offense_prior = league_a
        fav_defense_prior = league_h
        und_offense_prior = league_h
        und_defense_prior = league_a

    fav_off = _shrink_toward_prior(
        favorite_form.xg_for_avg if favorite_form.xg_for_avg is not None else fav_offense_prior,
        fav_offense_prior,
        favorite_form.matches_used,
    )
    fav_def = _shrink_toward_prior(
        favorite_form.xg_against_avg if favorite_form.xg_against_avg is not None else fav_defense_prior,
        fav_defense_prior,
        favorite_form.matches_used,
    )
    und_off = _shrink_toward_prior(
        underdog_form.xg_for_avg if underdog_form.xg_for_avg is not None else und_offense_prior,
        und_offense_prior,
        underdog_form.matches_used,
    )
    und_def = _shrink_toward_prior(
        underdog_form.xg_against_avg if underdog_form.xg_against_avg is not None else und_defense_prior,
        und_defense_prior,
        underdog_form.matches_used,
    )

    fav_baseline = fav_offense_prior
    und_baseline = und_offense_prior

    lambda_fav = math.sqrt(max(fav_off, 0.2) * max(und_def, 0.2))
    lambda_und = math.sqrt(max(und_off, 0.2) * max(fav_def, 0.2))

    expected_fav_at_avg = math.sqrt(fav_baseline * und_baseline)
    expected_und_at_avg = math.sqrt(und_baseline * fav_baseline)
    if expected_fav_at_avg > 0:
        lambda_fav *= fav_baseline / expected_fav_at_avg
    if expected_und_at_avg > 0:
        lambda_und *= und_baseline / expected_und_at_avg

    lambda_fav = max(0.2, min(3.5, lambda_fav))
    lambda_und = max(0.2, min(3.5, lambda_und))

    return lambda_fav, lambda_und


def _compute_probabilities_from_matrix(
    score_matrix: np.ndarray,
    favorite_is_home: bool,
) -> dict:
    """Unchanged from V2."""
    n = score_matrix.shape[0]
    home_win = draw = away_win = 0.0
    fav_win_and_2plus = 0.0
    fav_2plus = 0.0
    fav_clean_sheet = 0.0

    for h in range(n):
        for a in range(n):
            p = float(score_matrix[h, a])
            if h > a:
                home_win += p
            elif h == a:
                draw += p
            else:
                away_win += p
            if favorite_is_home:
                fav_goals, und_goals, fav_wins = h, a, h > a
            else:
                fav_goals, und_goals, fav_wins = a, h, a > h
            if fav_goals >= 2:
                fav_2plus += p
                if fav_wins:
                    fav_win_and_2plus += p
            if und_goals == 0:
                fav_clean_sheet += p

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "fav_win": home_win if favorite_is_home else away_win,
        "und_win": away_win if favorite_is_home else home_win,
        "fav_2plus": fav_2plus,
        "fav_clean_sheet": fav_clean_sheet,
        "fav_win_and_2plus": fav_win_and_2plus,
    }


# -----------------------------------------------------------------------------
# The engine
# -----------------------------------------------------------------------------

class BullyV2_5Engine:
    """
    V2.5 predictor. Same stateless contract as V2, with one additional
    required input: a `league_history: LeagueEloHistory` that provides the
    (elo_gap, hit) pairs needed to compute the per-league Elo cutoff.

    The engine computes target_hit_rate at construction from
    (margin_over_breakeven, assumed_avg_odds) and then computes the per-league
    elo_gap cutoff from `league_history` on each `predict()` call. Cutoffs
    are memoized by league_history identity for efficiency — pass the same
    history object for fixtures in the same league.

    Insufficient-history policies:
      - "block": if history has <min_history_fixtures, the gate rejects the
        fixture outright (never bet a league with too little backtest data).
      - "fallback_absolute": fall back to the V2 absolute threshold
        (min_elo_gap_absolute).
      - "fallback_percentile": fall back to a simple top-quartile cutoff
        computed from whatever history we have.
    """

    def __init__(
        self,
        *,
        # V2.5 NEW: target-hit-rate calibration
        target_margin_over_breakeven: float = DEFAULT_TARGET_MARGIN_OVER_BREAKEVEN,
        assumed_avg_odds: float = DEFAULT_ASSUMED_AVG_ODDS,
        min_elo_gap_absolute: float = MIN_ELO_GAP_ABSOLUTE_FLOOR,
        min_history_fixtures: int = MIN_HISTORY_FIXTURES_FOR_CALIBRATION,
        insufficient_history_policy: InsufficientHistoryPolicy = "block",
        # V2 gates retained
        min_favorite_lambda: float = MIN_FAVORITE_LAMBDA,
        max_opponent_lambda: float = MAX_OPPONENT_LAMBDA,
        min_joint_probability: float = MIN_JOINT_PROBABILITY,
        max_goals_grid: int = MAX_GOALS_GRID,
    ):
        self.target_hit_rate = compute_target_hit_rate(
            target_margin_over_breakeven, assumed_avg_odds,
        )
        self.target_margin = target_margin_over_breakeven
        self.assumed_avg_odds = assumed_avg_odds
        self.min_elo_gap_absolute = min_elo_gap_absolute
        self.min_history_fixtures = min_history_fixtures
        self.insufficient_history_policy = insufficient_history_policy

        self.min_favorite_lambda = min_favorite_lambda
        self.max_opponent_lambda = max_opponent_lambda
        self.min_joint_probability = min_joint_probability
        self.max_goals_grid = max_goals_grid

        # Memoize computed cutoffs per-league-history object id. Since
        # LeagueEloHistory is frozen we could hash by content too, but id()
        # is faster and sufficient for typical caller patterns (build one
        # history object per league, reuse).
        self._cutoff_cache: dict[int, tuple[Optional[float], str]] = {}

    # -- Elo cutoff resolution ------------------------------------------------

    def resolve_elo_cutoff(
        self,
        history: LeagueEloHistory,
    ) -> tuple[float, str]:
        """
        Compute the effective elo_gap cutoff for a league's history, applying
        the insufficient-history policy and absolute floor. Returns
        (cutoff, source_tag) where source_tag explains which branch was taken.

        Returns cutoff=math.inf if the policy is "block" and history is thin
        or no threshold clears the target — this guarantees the gate fails
        for every fixture in that league.
        """
        cache_key = id(history)
        if cache_key in self._cutoff_cache:
            cached_cutoff, cached_source = self._cutoff_cache[cache_key]
            return (cached_cutoff if cached_cutoff is not None else math.inf, cached_source)

        # Insufficient history check.
        if history.n_fixtures < self.min_history_fixtures:
            result = self._handle_insufficient_history(history)
            self._cutoff_cache[cache_key] = result
            cutoff, source = result
            return (cutoff if cutoff is not None else math.inf, source)

        # Try the target-hit-rate cutoff.
        computed = compute_elo_gap_cutoff_for_target_hit_rate(
            history, self.target_hit_rate,
        )

        if computed is not None:
            # Enforce absolute floor — even if the target says "gap 80 works",
            # V2's original 120 is a sanity floor (a league where an 80-point
            # gap historically cleared 74.5% is almost certainly a small-sample
            # artifact, and we don't want to bet on it).
            effective = max(computed, self.min_elo_gap_absolute)
            if effective == computed:
                source = "target_hit_rate"
            else:
                source = "target_hit_rate_floored"
            self._cutoff_cache[cache_key] = (effective, source)
            return (effective, source)

        # No cutoff in the league's data clears the target hit rate.
        # This is the "Ligue 1 too weak" case.
        result = self._handle_no_cutoff_clears_target(history)
        self._cutoff_cache[cache_key] = result
        cutoff, source = result
        return (cutoff if cutoff is not None else math.inf, source)

    def _handle_insufficient_history(
        self,
        history: LeagueEloHistory,
    ) -> tuple[Optional[float], str]:
        """Apply the insufficient-history policy when n_fixtures is below threshold."""
        policy = self.insufficient_history_policy
        if policy == "block":
            return (None, "insufficient_history_blocked")
        if policy == "fallback_absolute":
            return (self.min_elo_gap_absolute, "insufficient_history_fallback_absolute")
        if policy == "fallback_percentile":
            # Top-quartile of whatever history exists.
            if history.n_fixtures == 0:
                return (self.min_elo_gap_absolute, "insufficient_history_fallback_absolute")
            p75 = float(np.percentile(np.array(history.elo_gaps), 75))
            effective = max(p75, self.min_elo_gap_absolute)
            return (effective, "insufficient_history_fallback_percentile")
        raise ValueError(f"Unknown insufficient_history_policy: {policy}")

    def _handle_no_cutoff_clears_target(
        self,
        history: LeagueEloHistory,
    ) -> tuple[Optional[float], str]:
        """
        Apply policy when the league has enough fixtures but no cutoff clears
        the target hit rate. Same semantics as insufficient history: we can
        block, fall back to absolute, or fall back to percentile.
        """
        policy = self.insufficient_history_policy
        if policy == "block":
            return (None, "no_cutoff_clears_target_blocked")
        if policy == "fallback_absolute":
            return (self.min_elo_gap_absolute, "no_cutoff_clears_target_fallback_absolute")
        if policy == "fallback_percentile":
            p75 = float(np.percentile(np.array(history.elo_gaps), 75))
            effective = max(p75, self.min_elo_gap_absolute)
            return (effective, "no_cutoff_clears_target_fallback_percentile")
        raise ValueError(f"Unknown insufficient_history_policy: {policy}")

    # -- Prediction -----------------------------------------------------------

    def predict(
        self,
        *,
        home_elo: float,
        away_elo: float,
        home_form: FormSnapshot,
        away_form: FormSnapshot,
        league_fit: LeagueFit,
        league_history: LeagueEloHistory,
    ) -> BullyV2_5Prediction:
        # Step 1: identify favorite via Elo plus the league's fitted home advantage.
        effective_home_elo = home_elo + league_fit.home_advantage_elo
        elo_gap = abs(effective_home_elo - away_elo)
        favorite_is_home = effective_home_elo >= away_elo
        favorite_side = "home" if favorite_is_home else "away"

        # Step 2: estimate λ for both teams (unchanged from V2).
        favorite_form = home_form if favorite_is_home else away_form
        underdog_form = away_form if favorite_is_home else home_form
        lambda_fav, lambda_und = _estimate_team_lambdas(
            favorite_form,
            underdog_form,
            favorite_is_home=favorite_is_home,
            league_fit=league_fit,
        )

        lambda_home = lambda_fav if favorite_is_home else lambda_und
        lambda_away = lambda_und if favorite_is_home else lambda_fav

        # Step 3: build DC score matrix, derive probabilities (unchanged from V2).
        matrix = build_score_matrix(
            lambda_home=lambda_home,
            lambda_away=lambda_away,
            rho=league_fit.rho,
            max_goals=self.max_goals_grid,
        )
        probs = _compute_probabilities_from_matrix(matrix, favorite_is_home)

        # Step 4: resolve the per-league elo_gap cutoff for this prediction.
        elo_cutoff, cutoff_source = self.resolve_elo_cutoff(league_history)

        # Step 5: apply filter gates. The only change from V2 is that the
        # elo_gap gate uses the per-league cutoff instead of a fixed threshold.
        reasons: list[str] = []
        if elo_gap < elo_cutoff:
            if math.isinf(elo_cutoff):
                reasons.append(
                    f"elo_gate_blocked ({cutoff_source}, "
                    f"history_n={league_history.n_fixtures})"
                )
            else:
                reasons.append(
                    f"elo_gap {elo_gap:.0f} < {elo_cutoff:.0f} "
                    f"(target_hit_rate={self.target_hit_rate:.3f}, "
                    f"source={cutoff_source})"
                )
        if lambda_fav < self.min_favorite_lambda:
            reasons.append(
                f"lambda_fav {lambda_fav:.2f} < {self.min_favorite_lambda:.2f}"
            )
        if lambda_und > self.max_opponent_lambda:
            reasons.append(
                f"lambda_und {lambda_und:.2f} > {self.max_opponent_lambda:.2f}"
            )
        if probs["fav_win_and_2plus"] < self.min_joint_probability:
            reasons.append(
                f"p_joint {probs['fav_win_and_2plus']:.3f} "
                f"< {self.min_joint_probability:.3f}"
            )

        is_bully_spot = len(reasons) == 0

        reduced_confidence = (
            home_form.source != "understat"
            or away_form.source != "understat"
            or home_form.matches_used < 5
            or away_form.matches_used < 5
            or league_fit.samples_used < LEAGUE_FIT_FULL_WEIGHT_SAMPLES
            or league_history.n_fixtures < self.min_history_fixtures
        )

        return BullyV2_5Prediction(
            favorite_side=favorite_side,
            elo_gap=elo_gap,
            lambda_favorite=lambda_fav,
            lambda_underdog=lambda_und,
            p_favorite_win=probs["fav_win"],
            p_draw=probs["draw"],
            p_underdog_win=probs["und_win"],
            p_favorite_2plus=probs["fav_2plus"],
            p_favorite_clean_sheet=probs["fav_clean_sheet"],
            p_joint=probs["fav_win_and_2plus"],
            is_bully_spot=is_bully_spot,
            bully_filter_reasons=tuple(reasons),
            form_source_home=home_form.source,
            form_source_away=away_form.source,
            reduced_confidence=reduced_confidence,
            league_fit=league_fit,
            target_hit_rate=self.target_hit_rate,
            elo_gap_threshold_used=elo_cutoff if not math.isinf(elo_cutoff) else -1.0,
            elo_gap_threshold_source=cutoff_source,
            league_history_n_fixtures=league_history.n_fixtures,
        )


# -----------------------------------------------------------------------------
# Calibration and staking (unchanged from V2)
# -----------------------------------------------------------------------------

class JointProbabilityCalibrator:
    """Isotonic regression calibrator (identical to V2)."""

    def __init__(self):
        self._trained = False
        self._iso = None

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


def kelly_fraction(probability: float, decimal_odds: float) -> float:
    """Full Kelly on the joint event (identical to V2)."""
    if decimal_odds <= 1.0 or not (0.0 < probability < 1.0):
        return 0.0
    b = decimal_odds - 1.0
    edge = (b * probability) - (1.0 - probability)
    if edge <= 0:
        return 0.0
    return edge / b
