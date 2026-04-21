#!/usr/bin/env python3
"""
Multi-model bully backtest — compares V1, V3.1, and V3.2 variants.

All models are graded on SGP outcome: favorite wins AND scores >= 2 goals.
V1 is graded on its own is_bully_spot gate. V3.x is graded on is_bully_candidate.

Usage:
    DATABASE_URL=postgresql://... ODDS_API_KEY=x .venv/bin/python3 scripts/bully_backtest_compare.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Bully-Models"))

os.environ.setdefault("ODDS_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "postgresql://betuser:betpass@127.0.0.1:5433/sbmdb")

from app.db.connection import get_session
from app.db.models import Fixture, League, OddsSnapshot, Result, Team
from app.bully_engine import (
    DEFAULT_BULLY_GAP_THRESHOLD,
    EloFormPredictor,
    _as_utc,
)

# ---------------------------------------------------------------------------
# Load V3.1 and V3.2 engine modules
# ---------------------------------------------------------------------------
_HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Bully-Models")


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # must be registered before exec so __module__ lookups resolve
    spec.loader.exec_module(mod)
    return mod


v31 = _load_module("v31", "bully_engine_v3_1_cl_gpt.py")
v32 = _load_module("v32", "bully_engine_v3_2_cl_gpt.py")
v325 = _load_module("v325", "bully_engine_v3_2_5GPT.py")
v33gpt = _load_module("v33gpt", "bully_engine_v3_3GPT.py")

BullyEngineV31 = v31.BullyEngineV3
BullyEngineV32 = v32.BullyEngineV3
BullyEngineV325 = v325.BullyEngineV325GPT
TeamForm = v32.TeamForm
LeagueFit = v32.LeagueFit
MarketLine = v32.MarketLine

V33GPT_GATES = [0.20, 0.30, 0.35, 0.40, 0.45, 0.50]  # sweep thresholds
DEFAULT_RHO = v32.DEFAULT_RHO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _v1form_to_teamform(snapshot, team_name: str) -> TeamForm:
    """Map a V1 XGFormSnapshot to a V3.x TeamForm."""
    if snapshot.source == "understat":
        src = "xg"
        xg_for = snapshot.avg_for
        xg_against = snapshot.avg_against
        goals_for = None
        goals_against = None
    else:
        src = "goals_proxy" if snapshot.source != "none" else "none"
        xg_for = None
        xg_against = None
        goals_for = snapshot.avg_for
        goals_against = snapshot.avg_against

    return TeamForm(
        team_name=team_name,
        xg_for=xg_for,
        xg_against=xg_against,
        goals_for=goals_for,
        goals_against=goals_against,
        matches_used=snapshot.matches_used,
        source=src,
    )


def _v1league_to_leaguefit(v1_fit, league_name: str) -> LeagueFit:
    return LeagueFit(
        league_name=league_name,
        avg_home_goals=v1_fit.avg_home_goals,
        avg_away_goals=v1_fit.avg_away_goals,
        avg_total_goals=v1_fit.avg_home_goals + v1_fit.avg_away_goals,
        rho=DEFAULT_RHO,
        home_advantage_elo=v1_fit.home_advantage_elo,
        samples_used=v1_fit.samples_used,
    )


def _v1form_to_v325_teamform(snapshot, team_name: str):
    """Map V1 form to V3.2.5 TeamForm (same field names as V3.2, extra shot fields are optional)."""
    if snapshot.source == "understat":
        return v325.TeamForm(
            team_name=team_name,
            xg_for=snapshot.avg_for,
            xg_against=snapshot.avg_against,
            matches_used=snapshot.matches_used,
            source="xg",
        )
    return v325.TeamForm(
        team_name=team_name,
        goals_for=snapshot.avg_for,
        goals_against=snapshot.avg_against,
        matches_used=snapshot.matches_used,
        source="goals_proxy" if snapshot.source != "none" else "none",
    )


def _v1league_to_v325_leaguefit(v1_fit, league_name: str):
    return v325.LeagueFit(
        league_name=league_name,
        avg_home_goals=v1_fit.avg_home_goals,
        avg_away_goals=v1_fit.avg_away_goals,
        avg_total_goals=v1_fit.avg_home_goals + v1_fit.avg_away_goals,
        rho=DEFAULT_RHO,
        home_advantage_elo=v1_fit.home_advantage_elo,
        samples_used=v1_fit.samples_used,
    )


def _v1form_to_v33gpt_teamform(snapshot, team_name: str):
    """Map a V1 XGFormSnapshot to V3.3GPT's TeamForm (different field names, adds xg_trend)."""
    if snapshot.source == "understat":
        xg_for = snapshot.avg_for
        xg_against = snapshot.avg_against
    else:
        xg_for = snapshot.avg_for
        xg_against = snapshot.avg_against
    return v33gpt.TeamForm(
        team=team_name,
        xg_for=xg_for,
        xg_against=xg_against,
        goals_for=snapshot.avg_for,
        goals_against=snapshot.avg_against,
        xg_trend=0.0,
        matches=snapshot.matches_used,
    )


def _v1league_to_v33gpt_league(v1_fit):
    return v33gpt.League(
        home_goals=v1_fit.avg_home_goals,
        away_goals=v1_fit.avg_away_goals,
        rho=DEFAULT_RHO,
    )


def _market_line(session, fixture_id: int, cutoff, fav_side: str) -> Optional[MarketLine]:
    snap = (
        session.query(OddsSnapshot)
        .filter(OddsSnapshot.fixture_id == fixture_id)
        .filter(OddsSnapshot.captured_at <= cutoff)
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )
    if snap is None:
        return None
    fav_odds = snap.home_odds if fav_side == "home" else snap.away_odds
    opp_odds = snap.away_odds if fav_side == "home" else snap.home_odds
    if not fav_odds or not opp_odds:
        return None
    return MarketLine(
        moneyline_favorite_odds=fav_odds,
        moneyline_opposite_odds=opp_odds,
    )


def _fav_ml_odds(session, fixture_id: int, cutoff, fav_side: str) -> Optional[float]:
    snap = (
        session.query(OddsSnapshot)
        .filter(OddsSnapshot.fixture_id == fixture_id)
        .filter(OddsSnapshot.captured_at <= cutoff)
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )
    if snap is None:
        return None
    return snap.home_odds if fav_side == "home" else snap.away_odds


# ---------------------------------------------------------------------------
# Accumulator
# ---------------------------------------------------------------------------

import math
import random as _random
from dataclasses import field


@dataclass
class Acc:
    name: str
    candidates: int = 0
    sgp_hits: int = 0
    no_win: int = 0
    no_2plus: int = 0
    both_miss: int = 0
    roi_units: float = 0.0
    odds_available: int = 0
    p_joint_sum_hit: float = 0.0
    p_joint_sum_miss: float = 0.0
    # Per-pick trace for bootstrap / drawdown / streak analysis
    # Each entry: (fav_won, ml_odds or None) — ordered by fixture chronology
    picks: list = field(default_factory=list)
    odds_list: list = field(default_factory=list)

    def record(self, sgp_hit: bool, fav_won: bool, fav_goals: int, ml_odds: Optional[float], p_joint: Optional[float] = None):
        self.candidates += 1
        if sgp_hit:
            self.sgp_hits += 1
            if p_joint is not None:
                self.p_joint_sum_hit += p_joint
        else:
            if p_joint is not None:
                self.p_joint_sum_miss += p_joint
            if fav_won and fav_goals < 2:
                self.no_2plus += 1
            elif not fav_won and fav_goals >= 2:
                self.no_win += 1
            else:
                self.both_miss += 1

        if ml_odds is not None:
            self.odds_available += 1
            self.odds_list.append(ml_odds)
            self.picks.append((fav_won, ml_odds))
            if fav_won:
                self.roi_units += (ml_odds - 1.0)
            else:
                self.roi_units -= 1.0

    # ---- basic rates ----
    def hit_rate(self) -> float:
        return self.sgp_hits / self.candidates if self.candidates else 0.0

    def roi(self) -> float:
        return self.roi_units / self.odds_available if self.odds_available else float("nan")

    def avg_p_joint_hit(self) -> Optional[float]:
        return self.p_joint_sum_hit / self.sgp_hits if self.sgp_hits else None

    def avg_p_joint_miss(self) -> Optional[float]:
        misses = self.candidates - self.sgp_hits
        return self.p_joint_sum_miss / misses if misses else None

    # ---- deployment metrics ----
    def avg_odds(self) -> Optional[float]:
        return sum(self.odds_list) / len(self.odds_list) if self.odds_list else None

    def ml_win_rate(self) -> Optional[float]:
        """Moneyline win-rate (ignores the 2+ goals leg)."""
        if not self.picks:
            return None
        wins = sum(1 for won, _ in self.picks if won)
        return wins / len(self.picks)

    def implied_prob(self) -> Optional[float]:
        """Avg market-implied probability from the moneyline odds."""
        if not self.odds_list:
            return None
        return sum(1.0 / o for o in self.odds_list) / len(self.odds_list)

    def edge_vs_market(self) -> Optional[float]:
        """Observed ML win rate minus implied prob. >0 means we beat the market."""
        wr = self.ml_win_rate()
        ip = self.implied_prob()
        if wr is None or ip is None:
            return None
        return wr - ip

    def wilson_ci(self, z: float = 1.96) -> Optional[tuple]:
        """95% Wilson CI on SGP hit rate. Returns (lo, hi) or None."""
        n = self.candidates
        if n == 0:
            return None
        p = self.sgp_hits / n
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        return (max(0.0, center - half), min(1.0, center + half))

    def bootstrap_roi_ci(self, iters: int = 2000, seed: int = 42) -> Optional[tuple]:
        """95% bootstrap CI on moneyline ROI. Returns (lo, hi) or None."""
        if not self.picks:
            return None
        rng = _random.Random(seed)
        rois = []
        n = len(self.picks)
        for _ in range(iters):
            total = 0.0
            for _ in range(n):
                won, odds = self.picks[rng.randrange(n)]
                total += (odds - 1.0) if won else -1.0
            rois.append(total / n)
        rois.sort()
        return (rois[int(0.025 * iters)], rois[int(0.975 * iters)])

    def max_drawdown(self) -> float:
        """Largest peak-to-trough drawdown over the pick sequence (in units)."""
        if not self.picks:
            return 0.0
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for won, odds in self.picks:
            cum += (odds - 1.0) if won else -1.0
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)
        return max_dd

    def longest_losing_streak(self) -> int:
        if not self.picks:
            return 0
        cur = best = 0
        for won, _ in self.picks:
            if won:
                cur = 0
            else:
                cur += 1
                best = max(best, cur)
        return best

    def sharpe(self) -> Optional[float]:
        """ROI / std-dev per pick (risk-adjusted return)."""
        if len(self.picks) < 2:
            return None
        rets = [(o - 1.0) if w else -1.0 for w, o in self.picks]
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        return mu / sd if sd > 0 else None

    def kelly_stake(self) -> Optional[float]:
        """Kelly fraction using observed ML win rate vs avg odds. Negative ⇒ no bet."""
        wr = self.ml_win_rate()
        o = self.avg_odds()
        if wr is None or o is None or o <= 1.0:
            return None
        b = o - 1.0
        return (b * wr - (1 - wr)) / b


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    session = get_session()

    # Load teams lookup
    team_names = {t.id: t.name for t in session.query(Team).all()}

    # V1 predictor (no understat fetch for speed; uses form cache + results proxy)
    v1_predictor = EloFormPredictor(session, enable_understat_fetch=False)

    # V3.x engine variants
    engines = {
        "V3.1 (symmetric α=0.50)": BullyEngineV31(lambda_form="symmetric", lambda_alpha=0.50),
        "V3.2 (symmetric α=0.50)": BullyEngineV32(lambda_form="symmetric", lambda_alpha=0.50),
        "V3.2 (attack_w α=0.55)": BullyEngineV32(lambda_form="attack_weighted", lambda_alpha=0.55),
        "V3.2 (attack_w α=0.60)": BullyEngineV32(lambda_form="attack_weighted", lambda_alpha=0.60),
        "V3.2 (attack_w α=0.65)": BullyEngineV32(lambda_form="attack_weighted", lambda_alpha=0.65),
        # Unblinded V3.2 — relax all three structural gates to expose whether α matters
        "V3.2 (α=0.60, gates relaxed)": BullyEngineV32(
            lambda_form="attack_weighted",
            lambda_alpha=0.60,
            min_joint_probability=0.30,
            min_favorite_lambda=1.30,
            min_bully_score=30.0,
            min_elo_gap=60.0,
        ),
        "V3.2 (α=0.65, gates relaxed)": BullyEngineV32(
            lambda_form="attack_weighted",
            lambda_alpha=0.65,
            min_joint_probability=0.30,
            min_favorite_lambda=1.30,
            min_bully_score=30.0,
            min_elo_gap=60.0,
        ),
        "V3.2 (sym α=0.50, gates relaxed)": BullyEngineV32(
            lambda_form="symmetric",
            lambda_alpha=0.50,
            min_joint_probability=0.30,
            min_favorite_lambda=1.30,
            min_bully_score=30.0,
            min_elo_gap=60.0,
        ),
    }

    # V3.2.5 engines — separate because they use their own TeamForm/LeagueFit dataclasses
    engines_v325 = {
        "V3.2.5 (symmetric α=0.50)": BullyEngineV325(lambda_form="symmetric", lambda_alpha=0.50),
        "V3.2.5 (attack_w α=0.60)": BullyEngineV325(lambda_form="attack_weighted", lambda_alpha=0.60),
    }

    def _fresh_accs() -> dict[str, Acc]:
        return {
            "V1-legacy (elo_gap≥120)": Acc("V1-legacy (elo_gap≥120)"),
            "V1 (→V3 gate delegated)": Acc("V1 (→V3 gate delegated)"),
            **{name: Acc(name) for name in engines},
            **{name: Acc(name) for name in engines_v325},
            **{f"V3.3GPT (p_j≥{g:.2f})": Acc(f"V3.3GPT (p_j≥{g:.2f})") for g in V33GPT_GATES},
        }

    accumulators = _fresh_accs()
    league_accs: dict[str, dict[str, Acc]] = defaultdict(_fresh_accs)

    # Fetch all completed fixtures with results
    fixtures_with_results = (
        session.query(Fixture, Result)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(Result.home_score.isnot(None))
        .filter(Result.away_score.isnot(None))
        .filter(Result.outcome.isnot(None))
        .order_by(Fixture.kickoff_at.asc())
        .all()
    )

    leagues = {lg.id: lg for lg in session.query(League).all()}

    print(f"Backtesting {len(fixtures_with_results)} fixtures...\n")

    processed = 0
    skipped_no_league = 0
    skipped_no_v1_pred = 0

    for fixture, result in fixtures_with_results:
        league = leagues.get(fixture.league_id)
        if league is None:
            skipped_no_league += 1
            continue

        cutoff = _as_utc(fixture.kickoff_at)

        # --- V1 prediction ---
        v1_pred = v1_predictor.predict_fixture(fixture, as_of=fixture.kickoff_at)
        if v1_pred is None:
            skipped_no_v1_pred += 1
            continue

        fav_side = v1_pred.favorite_side
        fav_goals = result.home_score if fav_side == "home" else result.away_score
        und_goals = result.away_score if fav_side == "home" else result.home_score
        fav_won = (fav_side == result.outcome)
        sgp_hit = fav_won and fav_goals >= 2

        ml_odds = _fav_ml_odds(session, fixture.id, cutoff, fav_side)

        def _record(model_name: str, p_joint=None):
            accumulators[model_name].record(sgp_hit, fav_won, fav_goals, ml_odds, p_joint=p_joint)
            league_accs[league.name][model_name].record(
                sgp_hit, fav_won, fav_goals, ml_odds, p_joint=p_joint
            )

        # V1 (delegates to V3 gate in current bully_engine.py)
        if v1_pred.is_bully_spot:
            _record("V1 (→V3 gate delegated)")

        # V1-legacy: pre-refactor gate was elo_gap >= 120 (xG overlay dropped here — this is the
        # conservative moneyline-only baseline that produced 46 candidates in the original backtest)
        effective_home_elo = v1_pred.home_elo + v1_pred.league_fit.home_advantage_elo
        elo_gap = abs(effective_home_elo - v1_pred.away_elo)
        if elo_gap >= 120.0:
            _record("V1-legacy (elo_gap≥120)")

        # --- Build V3.x inputs from V1's computed form ---
        home_team_name = team_names.get(fixture.home_team_id, "Home")
        away_team_name = team_names.get(fixture.away_team_id, "Away")
        home_form_v3 = _v1form_to_teamform(v1_pred.home_form, home_team_name)
        away_form_v3 = _v1form_to_teamform(v1_pred.away_form, away_team_name)
        league_fit_v3 = _v1league_to_leaguefit(v1_pred.league_fit, league.name)
        market = _market_line(session, fixture.id, cutoff, fav_side)

        # --- V3.x predictions ---
        for engine_name, engine in engines.items():
            try:
                pred = engine.predict(
                    home_team=home_form_v3,
                    away_team=away_form_v3,
                    home_elo=v1_pred.home_elo,
                    away_elo=v1_pred.away_elo,
                    league=league_fit_v3,
                    market=market,
                )
            except Exception as exc:
                continue

            if pred.is_bully_candidate:
                _record(engine_name, p_joint=pred.p_joint)

        # --- V3.2.5 predictions ---
        home_form_v325 = _v1form_to_v325_teamform(v1_pred.home_form, home_team_name)
        away_form_v325 = _v1form_to_v325_teamform(v1_pred.away_form, away_team_name)
        league_fit_v325 = _v1league_to_v325_leaguefit(v1_pred.league_fit, league.name)
        market_v325 = v325.MarketLine(
            moneyline_favorite_odds=market.moneyline_favorite_odds if market else None,
            moneyline_opposite_odds=market.moneyline_opposite_odds if market else None,
        )

        for engine_name, engine in engines_v325.items():
            try:
                pred = engine.predict(
                    home_team=home_form_v325,
                    away_team=away_form_v325,
                    home_elo=v1_pred.home_elo,
                    away_elo=v1_pred.away_elo,
                    league=league_fit_v325,
                    market=market_v325,
                )
            except Exception:
                continue
            if pred.is_bully_candidate:
                _record(engine_name, p_joint=pred.p_joint)

        # --- V3.3GPT prediction ---
        try:
            home_v33 = _v1form_to_v33gpt_teamform(v1_pred.home_form, home_team_name)
            away_v33 = _v1form_to_v33gpt_teamform(v1_pred.away_form, away_team_name)
            league_v33 = _v1league_to_v33gpt_league(v1_pred.league_fit)
            # V3.3GPT hard-codes fav=arg1, dog=arg2 — pass Elo-favorite first
            if fav_side == "home":
                fav_v33, dog_v33 = home_v33, away_v33
            else:
                fav_v33, dog_v33 = away_v33, home_v33
            pred_v33 = v33gpt.predict(fav_v33, dog_v33, league_v33)
            for gate in V33GPT_GATES:
                if pred_v33["p_joint"] >= gate:
                    _record(f"V3.3GPT (p_j≥{gate:.2f})", p_joint=pred_v33["p_joint"])
        except Exception:
            pass

        processed += 1
        if processed % 100 == 0:
            print(f"  ...{processed} fixtures processed", end="\r")

    print(f"\nProcessed: {processed}  |  Skipped (no league): {skipped_no_league}  |  Skipped (no V1 pred): {skipped_no_v1_pred}\n")

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------
    def print_table(title: str, accs: dict[str, Acc], fixture_count: Optional[int] = None):
        header = (
            f"{'Model':<34}  {'Cand':>4}  {'Hit%':>6}  {'Hit 95%CI':>13}  "
            f"{'ML%':>5}  {'AvgO':>5}  {'Edge':>6}  "
            f"{'ROI':>7}  {'ROI 95%CI':>16}  {'Sharpe':>6}  "
            f"{'Kelly':>6}  {'MaxDD':>6}  {'LStk':>4}  {'p_j':>5}"
        )
        suffix = f" ({fixture_count} fixtures)" if fixture_count is not None else ""
        print(f"\n=== {title}{suffix} ===")
        print(header)
        print("-" * len(header))
        for name, acc in accs.items():
            def fmt(val, spec, na="  n/a"):
                return format(val, spec) if val is not None else na

            wilson = acc.wilson_ci()
            boot = acc.bootstrap_roi_ci() if acc.candidates >= 5 else None
            hit_ci = f"{wilson[0]:.2f}-{wilson[1]:.2f}" if wilson else "     n/a     "
            roi_ci = f"{boot[0]:+.2f}/{boot[1]:+.2f}" if boot else "      n/a       "
            roi_str = f"{acc.roi():+.3f}" if acc.odds_available else "  n/a "
            edge = acc.edge_vs_market()
            edge_str = f"{edge:+.3f}" if edge is not None else "  n/a"
            avg_odds = acc.avg_odds()
            avg_odds_str = f"{avg_odds:.2f}" if avg_odds else " n/a"
            ml_wr = acc.ml_win_rate()
            ml_wr_str = f"{ml_wr:.0%}" if ml_wr is not None else " n/a"
            sharpe = acc.sharpe()
            sharpe_str = f"{sharpe:+.2f}" if sharpe is not None else "  n/a"
            kelly = acc.kelly_stake()
            kelly_str = f"{kelly:+.2f}" if kelly is not None else "  n/a"
            p_hit = acc.avg_p_joint_hit()
            p_hit_str = f"{p_hit:.2f}" if p_hit is not None else " n/a"
            print(
                f"{name:<34}  {acc.candidates:>4}  {acc.hit_rate():>5.1%}  "
                f"{hit_ci:>13}  {ml_wr_str:>5}  {avg_odds_str:>5}  {edge_str:>6}  "
                f"{roi_str:>7}  {roi_ci:>16}  {sharpe_str:>6}  "
                f"{kelly_str:>6}  {acc.max_drawdown():>6.1f}  {acc.longest_losing_streak():>4}  "
                f"{p_hit_str:>5}"
            )

    # Aggregate table
    print_table("AGGREGATE (all leagues)", accumulators, fixture_count=processed)

    # Per-league fixture counts for context
    league_counts: dict[str, int] = defaultdict(int)
    for fixture, _result in fixtures_with_results:
        lg = leagues.get(fixture.league_id)
        if lg is not None:
            league_counts[lg.name] += 1

    # Per-league tables, ordered by fixture volume
    for lg_name in sorted(league_accs.keys(), key=lambda n: -league_counts[n]):
        print_table(lg_name, league_accs[lg_name], fixture_count=league_counts[lg_name])

    print("\nNotes:")
    print("  Hit%  = SGP hit-rate (fav wins AND scores 2+). 95%CI is Wilson.")
    print("  ML%   = moneyline-only win-rate (ignores 2+ leg).")
    print("  AvgO  = avg ML odds on picks with odds data.")
    print("  Edge  = ML% − avg implied prob (>0 = beat market on moneyline).")
    print("  ROI   = ML ROI per unit staked (flat stakes). 95%CI is bootstrap (2000 iters).")
    print("  Sharpe= mean return / std per pick (risk-adjusted ROI).")
    print("  Kelly = optimal stake fraction using observed ML% and AvgO (negative ⇒ no bet).")
    print("  MaxDD = peak-to-trough drawdown in units across the pick sequence.")
    print("  LStk  = longest losing streak (ML losses).")
    print("  p_j   = avg p_joint at hits (V3.x only).")
    print("  ROI is moneyline proxy — true SGP ROI requires combined SGP pricing.")

    session.close()


if __name__ == "__main__":
    run()
