#!/usr/bin/env python3
"""
Season-split bully backtest across every executable engine in Bully-Models.

Outputs:
- stdout summary tables by season plus an overall aggregate
- CSV with one row per season/model plus an aggregate row
- optional per-candidate CSV with raw favorite ML, favorite team-total 1.5,
  and synthesized joint market pricing when available

Notes:
- ROI is priced off favorite moneyline odds because the repo does not persist
  native SGP prices for the joint "favorite wins and scores 2+" event.
- The V3-family files expose both "bully candidate" and "bet candidate". This
  runner uses the broader recommendation flag already used by the existing
  research comparer so untrained/live-market safety rails do not collapse the
  historical sample to zero picks.
- `bully_engine_v3_3GPT.py` exposes only a raw `p_joint`, not a native gate.
  This runner applies an inferred `p_joint >= 0.42` gate to keep it comparable
  to the rest of the V3 family.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "Bully-Models"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MODELS_DIR))

os.environ.setdefault("ODDS_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "postgresql://betuser:betpass@127.0.0.1:5433/sbmdb")

from app.bully_engine import (
    EloFormPredictor,
    MarketLine as AppMarketLine,
    _as_utc,
    _market_joint_prob_vig_free as app_market_joint_prob_vig_free,
)
from app.db.connection import get_session
from app.db.models import Fixture, League, OddsSnapshot, Result, Team


SEASON_WINDOWS: dict[str, tuple[datetime, datetime]] = {
    "2023-24": (datetime(2023, 8, 1), datetime(2024, 8, 1)),
    "2024-25": (datetime(2024, 8, 1), datetime(2025, 8, 1)),
    "2025-26": (datetime(2025, 8, 1), datetime(2026, 8, 1)),
}

SEASON_ORDER = ("2023-24", "2024-25", "2025-26")
V33_MIN_P_JOINT = 0.42


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MODELS_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


v2 = _load_module("bully_v2", "bully_engine_v2.py")
v2_gpt = _load_module("bully_v2_gpt", "bully_engine_v2_gpt.py")
v3 = _load_module("bully_v3", "bully_engine_v3_cl_gpt.py")
v31 = _load_module("bully_v31", "bully_engine_v3_1_cl_gpt.py")
v32 = _load_module("bully_v32", "bully_engine_v3_2_cl_gpt.py")
v325 = _load_module("bully_v325", "bully_engine_v3_2_5GPT.py")
v33 = _load_module("bully_v33", "bully_engine_v3_3GPT.py")


@dataclass(frozen=True)
class ModelMeta:
    name: str
    source_file: str
    selection_rule: str


@dataclass
class Acc:
    name: str
    source_file: str
    selection_rule: str
    candidates: int = 0
    priced: int = 0
    sgp_hits: int = 0
    ml_wins: int = 0
    roi_units: float = 0.0
    picks: list[tuple[bool, float]] = field(default_factory=list)
    odds_list: list[float] = field(default_factory=list)
    p_joint_hits: list[float] = field(default_factory=list)
    p_joint_misses: list[float] = field(default_factory=list)

    def record(
        self,
        *,
        sgp_hit: bool,
        ml_win: bool,
        ml_odds: Optional[float],
        p_joint: Optional[float],
    ) -> None:
        self.candidates += 1
        if sgp_hit:
            self.sgp_hits += 1
            if p_joint is not None:
                self.p_joint_hits.append(p_joint)
        else:
            if p_joint is not None:
                self.p_joint_misses.append(p_joint)
        if ml_win:
            self.ml_wins += 1
        if ml_odds is not None:
            self.priced += 1
            self.odds_list.append(ml_odds)
            self.picks.append((ml_win, ml_odds))
            self.roi_units += (ml_odds - 1.0) if ml_win else -1.0

    def hit_rate(self) -> float:
        return self.sgp_hits / self.candidates if self.candidates else 0.0

    def ml_win_rate(self) -> Optional[float]:
        return self.ml_wins / self.candidates if self.candidates else None

    def avg_odds(self) -> Optional[float]:
        return (sum(self.odds_list) / len(self.odds_list)) if self.odds_list else None

    def avg_implied_prob(self) -> Optional[float]:
        if not self.odds_list:
            return None
        return sum(1.0 / odd for odd in self.odds_list) / len(self.odds_list)

    def edge_vs_market(self) -> Optional[float]:
        ml_wr = self.ml_win_rate()
        implied = self.avg_implied_prob()
        if ml_wr is None or implied is None:
            return None
        return ml_wr - implied

    def roi(self) -> Optional[float]:
        return (self.roi_units / self.priced) if self.priced else None

    def max_drawdown(self) -> float:
        if not self.picks:
            return 0.0
        peak = 0.0
        cum = 0.0
        max_dd = 0.0
        for won, odds in self.picks:
            cum += (odds - 1.0) if won else -1.0
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)
        return max_dd

    def longest_losing_streak(self) -> int:
        best = 0
        current = 0
        for won, _odds in self.picks:
            if won:
                current = 0
            else:
                current += 1
                best = max(best, current)
        return best

    def avg_p_joint_hit(self) -> Optional[float]:
        return (sum(self.p_joint_hits) / len(self.p_joint_hits)) if self.p_joint_hits else None

    def avg_p_joint_miss(self) -> Optional[float]:
        return (sum(self.p_joint_misses) / len(self.p_joint_misses)) if self.p_joint_misses else None

    def to_row(self, season: str, fixtures_processed: int) -> dict[str, object]:
        return {
            "season": season,
            "model": self.name,
            "source_file": self.source_file,
            "selection_rule": self.selection_rule,
            "fixtures_processed": fixtures_processed,
            "candidates": self.candidates,
            "priced": self.priced,
            "sgp_hits": self.sgp_hits,
            "sgp_hit_rate": round(self.hit_rate(), 6),
            "ml_wins": self.ml_wins,
            "ml_win_rate": round(self.ml_win_rate(), 6) if self.ml_win_rate() is not None else "",
            "avg_ml_odds": round(self.avg_odds(), 6) if self.avg_odds() is not None else "",
            "avg_implied_prob": round(self.avg_implied_prob(), 6) if self.avg_implied_prob() is not None else "",
            "edge_vs_market": round(self.edge_vs_market(), 6) if self.edge_vs_market() is not None else "",
            "roi_units": round(self.roi_units, 6),
            "roi": round(self.roi(), 6) if self.roi() is not None else "",
            "max_drawdown": round(self.max_drawdown(), 6),
            "longest_losing_streak": self.longest_losing_streak(),
            "avg_p_joint_hit": round(self.avg_p_joint_hit(), 6) if self.avg_p_joint_hit() is not None else "",
            "avg_p_joint_miss": round(self.avg_p_joint_miss(), 6) if self.avg_p_joint_miss() is not None else "",
        }


def _model_meta(min_elo_gap: float | None) -> tuple[ModelMeta, ...]:
    suffix = f" & elo_gap >= {min_elo_gap:.0f}" if min_elo_gap is not None else ""
    return (
        ModelMeta("V2", "bully_engine_v2.py", f"is_bully_spot{suffix}"),
        ModelMeta("GPT V2", "bully_engine_v2_gpt.py", f"is_bully_candidate{suffix}"),
        ModelMeta("V3", "bully_engine_v3_cl_gpt.py", f"is_bully_candidate{suffix}"),
        ModelMeta("V3.1", "bully_engine_v3_1_cl_gpt.py", f"is_bully_candidate{suffix}"),
        ModelMeta("V3.2", "bully_engine_v3_2_cl_gpt.py", f"is_bully_candidate{suffix}"),
        ModelMeta("V3.2.5", "bully_engine_v3_2_5GPT.py", f"is_bully_candidate{suffix}"),
        ModelMeta(
            "V3.3GPT",
            "bully_engine_v3_3GPT.py",
            f"p_joint >= {V33_MIN_P_JOINT:.2f}{suffix}",
        ),
    )


def _build_engines(min_elo_gap: float | None) -> dict[str, object]:
    kwargs = {}
    if min_elo_gap is not None:
        kwargs["min_elo_gap"] = min_elo_gap
    return {
        "V2": v2.BullyV2Engine(**kwargs),
        "GPT V2": v2_gpt.GPTBullyEngineV2(**kwargs),
        "V3": v3.BullyEngineV3(**kwargs),
        "V3.1": v31.BullyEngineV3(**kwargs),
        "V3.2": v32.BullyEngineV3(**kwargs),
        "V3.2.5": v325.BullyEngineV325GPT(**kwargs),
    }


def _fresh_accs(model_meta: tuple[ModelMeta, ...]) -> dict[str, Acc]:
    return {
        meta.name: Acc(
            name=meta.name,
            source_file=meta.source_file,
            selection_rule=meta.selection_rule,
        )
        for meta in model_meta
    }


def _season_for(kickoff_at: datetime, selected: tuple[str, ...]) -> Optional[str]:
    for season in selected:
        start, end = SEASON_WINDOWS[season]
        if start <= kickoff_at < end:
            return season
    return None


def _v1_source_name(source: str) -> str:
    if source == "understat":
        return "understat"
    if source == "none":
        return "none"
    return "results_proxy"


def _v1_form_to_v2(snapshot):
    return v2.FormSnapshot(
        xg_for_avg=snapshot.avg_for,
        xg_against_avg=snapshot.avg_against,
        matches_used=snapshot.matches_used,
        source=_v1_source_name(snapshot.source),
    )


def _v1_league_to_v2(v1_fit):
    return v2.LeagueFit(
        avg_home_goals=v1_fit.avg_home_goals,
        avg_away_goals=v1_fit.avg_away_goals,
        rho=v2.DEFAULT_RHO,
        home_advantage_elo=v1_fit.home_advantage_elo,
        samples_used=v1_fit.samples_used,
    )


def _v1_form_to_v2_gpt(snapshot, team_name: str):
    if snapshot.source == "understat":
        return v2_gpt.TeamForm(
            team_name=team_name,
            xg_for=snapshot.avg_for,
            xg_against=snapshot.avg_against,
            goals_for=snapshot.avg_for,
            goals_against=snapshot.avg_against,
            matches_used=snapshot.matches_used,
            source="xg",
        )
    return v2_gpt.TeamForm(
        team_name=team_name,
        xg_for=None,
        xg_against=None,
        goals_for=snapshot.avg_for,
        goals_against=snapshot.avg_against,
        matches_used=snapshot.matches_used,
        source="proxy" if snapshot.source != "none" else "none",
    )


def _v1_league_to_v2_gpt(v1_fit, league_name: str):
    return v2_gpt.LeagueContext(
        league_name=league_name,
        avg_home_goals=v1_fit.avg_home_goals,
        avg_away_goals=v1_fit.avg_away_goals,
        avg_total_goals=v1_fit.avg_home_goals + v1_fit.avg_away_goals,
        home_advantage_elo=v1_fit.home_advantage_elo,
        samples_used=v1_fit.samples_used,
    )


def _v1_form_to_v3(snapshot, team_name: str, module):
    if snapshot.source == "understat":
        return module.TeamForm(
            team_name=team_name,
            xg_for=snapshot.avg_for,
            xg_against=snapshot.avg_against,
            matches_used=snapshot.matches_used,
            source="xg",
        )
    return module.TeamForm(
        team_name=team_name,
        goals_for=snapshot.avg_for,
        goals_against=snapshot.avg_against,
        matches_used=snapshot.matches_used,
        source="goals_proxy" if snapshot.source != "none" else "none",
    )


def _v1_league_to_v3(v1_fit, league_name: str, module):
    return module.LeagueFit(
        league_name=league_name,
        avg_home_goals=v1_fit.avg_home_goals,
        avg_away_goals=v1_fit.avg_away_goals,
        avg_total_goals=v1_fit.avg_home_goals + v1_fit.avg_away_goals,
        rho=getattr(module, "DEFAULT_RHO", -0.13),
        home_advantage_elo=v1_fit.home_advantage_elo,
        samples_used=v1_fit.samples_used,
    )


def _v1_form_to_v33(snapshot, team_name: str):
    return v33.TeamForm(
        team=team_name,
        xg_for=snapshot.avg_for,
        xg_against=snapshot.avg_against,
        goals_for=snapshot.avg_for,
        goals_against=snapshot.avg_against,
        xg_trend=0.0,
        matches=snapshot.matches_used,
    )


def _v1_league_to_v33(v1_fit):
    return v33.League(
        home_goals=v1_fit.avg_home_goals,
        away_goals=v1_fit.avg_away_goals,
        rho=-0.13,
    )


def _latest_odds_snapshot(session, fixture_id: int, cutoff: datetime) -> OddsSnapshot | None:
    return (
        session.query(OddsSnapshot)
        .filter(OddsSnapshot.fixture_id == fixture_id)
        .filter(OddsSnapshot.captured_at <= cutoff)
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )


def _favorite_odds(snapshot: OddsSnapshot | None, favorite_side: str) -> Optional[float]:
    if snapshot is None:
        return None
    return snapshot.home_odds if favorite_side == "home" else snapshot.away_odds


def _opposite_odds(snapshot: OddsSnapshot | None, favorite_side: str) -> Optional[float]:
    if snapshot is None:
        return None
    return snapshot.away_odds if favorite_side == "home" else snapshot.home_odds


def _favorite_team_total_1_5_odds(snapshot: OddsSnapshot | None, favorite_side: str) -> tuple[Optional[float], Optional[float]]:
    if snapshot is None:
        return None, None
    if favorite_side == "home":
        return snapshot.home_team_total_1_5_over_odds, snapshot.home_team_total_1_5_under_odds
    return snapshot.away_team_total_1_5_over_odds, snapshot.away_team_total_1_5_under_odds


def _market_line(snapshot: OddsSnapshot | None, favorite_side: str, module):
    fav_odds = _favorite_odds(snapshot, favorite_side)
    opp_odds = _opposite_odds(snapshot, favorite_side)
    team_total_over, team_total_under = _favorite_team_total_1_5_odds(snapshot, favorite_side)
    return module.MarketLine(
        moneyline_favorite_odds=fav_odds,
        moneyline_opposite_odds=opp_odds,
        team_total_over_1_5_odds=team_total_over,
        team_total_under_1_5_odds=team_total_under,
    )


def _market_prob_vig_free(snapshot: OddsSnapshot | None, favorite_side: str) -> tuple[Optional[float], str]:
    fav_odds = _favorite_odds(snapshot, favorite_side)
    opp_odds = _opposite_odds(snapshot, favorite_side)
    team_total_over, team_total_under = _favorite_team_total_1_5_odds(snapshot, favorite_side)
    market = AppMarketLine(
        moneyline_favorite_odds=fav_odds,
        moneyline_opposite_odds=opp_odds,
        team_total_over_1_5_odds=team_total_over,
        team_total_under_1_5_odds=team_total_under,
    )
    return app_market_joint_prob_vig_free(
        market,
        favorite_side == "home",
    )


def _fmt_pct(value: Optional[float]) -> str:
    return f"{value:>5.1%}" if value is not None else "  n/a"


def _fmt_num(value: Optional[float], spec: str, na: str = "  n/a") -> str:
    return format(value, spec) if value is not None else na


def _print_table(
    title: str,
    accs: dict[str, Acc],
    fixtures_processed: int,
    model_meta: tuple[ModelMeta, ...],
) -> None:
    header = (
        f"{'Model':<10}  {'Cand':>5}  {'Priced':>6}  {'Hit%':>6}  "
        f"{'ML%':>6}  {'AvgO':>6}  {'Edge':>7}  {'ROI':>7}  {'MaxDD':>6}"
    )
    print(f"\n=== {title} ({fixtures_processed} fixtures) ===")
    print(header)
    print("-" * len(header))
    for meta in model_meta:
        acc = accs[meta.name]
        print(
            f"{acc.name:<10}  {acc.candidates:>5}  {acc.priced:>6}  "
            f"{_fmt_pct(acc.hit_rate()):>6}  {_fmt_pct(acc.ml_win_rate()):>6}  "
            f"{_fmt_num(acc.avg_odds(), '6.2f'):>6}  {_fmt_num(acc.edge_vs_market(), '+7.3f'):>7}  "
            f"{_fmt_num(acc.roi(), '+7.3f'):>7}  {acc.max_drawdown():>6.1f}"
        )


def _write_csv(csv_path: Path, rows: list[dict[str, object]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "season",
        "model",
        "source_file",
        "selection_rule",
        "fixtures_processed",
        "candidates",
        "priced",
        "sgp_hits",
        "sgp_hit_rate",
        "ml_wins",
        "ml_win_rate",
        "avg_ml_odds",
        "avg_implied_prob",
        "edge_vs_market",
        "roi_units",
        "roi",
        "max_drawdown",
        "longest_losing_streak",
        "avg_p_joint_hit",
        "avg_p_joint_miss",
    ]
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_candidate_details_csv(csv_path: Path, rows: list[dict[str, object]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "season",
        "fixture_id",
        "kickoff_at",
        "league",
        "home_team",
        "away_team",
        "model",
        "source_file",
        "selection_rule",
        "favorite_side",
        "favorite_team",
        "underdog_team",
        "elo_gap",
        "sgp_hit",
        "ml_win",
        "model_p_joint",
        "model_fair_odds",
        "market_source",
        "market_prob_vig_free",
        "market_fair_odds",
        "moneyline_favorite_odds",
        "moneyline_opposite_odds",
        "team_total_over_1_5_odds",
        "team_total_under_1_5_odds",
    ]
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--season",
        dest="seasons",
        action="append",
        choices=SEASON_ORDER,
        help="Season(s) to run. Defaults to 2023-24, 2024-25, and 2025-26.",
    )
    parser.add_argument(
        "--csv-out",
        default=str(ROOT / "data" / "bully_backtest_all_models_ml_odds.csv"),
        help="CSV output path.",
    )
    parser.add_argument(
        "--min-elo-gap",
        type=float,
        default=None,
        help="Override the Elo gate for every configurable model.",
    )
    parser.add_argument(
        "--candidate-details-csv",
        default=None,
        help="Optional CSV path for one row per flagged candidate with SGP pricing inputs.",
    )
    return parser.parse_args()


def run(
    seasons: tuple[str, ...],
    csv_out: Path,
    min_elo_gap: float | None = None,
    candidate_details_csv: Path | None = None,
) -> None:
    session = get_session()
    predictor = EloFormPredictor(session, enable_understat_fetch=False)
    model_meta = _model_meta(min_elo_gap)
    model_meta_by_name = {meta.name: meta for meta in model_meta}
    engines = _build_engines(min_elo_gap)

    team_names = {row.id: row.name for row in session.query(Team).all()}
    leagues = {row.id: row for row in session.query(League).all()}

    first_start = min(SEASON_WINDOWS[season][0] for season in seasons)
    last_end = max(SEASON_WINDOWS[season][1] for season in seasons)

    fixtures_with_results = (
        session.query(Fixture, Result)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(Fixture.status == "completed")
        .filter(Fixture.kickoff_at >= first_start)
        .filter(Fixture.kickoff_at < last_end)
        .filter(Result.home_score.isnot(None))
        .filter(Result.away_score.isnot(None))
        .filter(Result.outcome.isnot(None))
        .order_by(Fixture.kickoff_at.asc())
        .all()
    )

    season_accs = {season: _fresh_accs(model_meta) for season in seasons}
    overall_accs = _fresh_accs(model_meta)
    season_fixture_counts = defaultdict(int)
    error_counts = defaultdict(int)
    skipped_no_league = 0
    skipped_no_v1_pred = 0
    detail_rows: list[dict[str, object]] = []

    print(f"Running comprehensive Bully backtest over {len(fixtures_with_results)} completed fixtures...")

    for idx, (fixture, result) in enumerate(fixtures_with_results, start=1):
        season = _season_for(fixture.kickoff_at, seasons)
        if season is None:
            continue

        league = leagues.get(fixture.league_id)
        if league is None:
            skipped_no_league += 1
            continue

        v1_pred = predictor.predict_fixture(fixture, as_of=fixture.kickoff_at)
        if v1_pred is None:
            skipped_no_v1_pred += 1
            continue

        season_fixture_counts[season] += 1

        favorite_side = v1_pred.favorite_side
        favorite_goals = result.home_score if favorite_side == "home" else result.away_score
        favorite_win = favorite_side == result.outcome
        sgp_hit = favorite_win and favorite_goals >= 2

        cutoff = _as_utc(fixture.kickoff_at)
        snapshot = _latest_odds_snapshot(session, fixture.id, cutoff)
        ml_odds = _favorite_odds(snapshot, favorite_side)
        opposite_ml_odds = _opposite_odds(snapshot, favorite_side)
        team_total_over_odds, team_total_under_odds = _favorite_team_total_1_5_odds(snapshot, favorite_side)
        market_prob, market_source = _market_prob_vig_free(snapshot, favorite_side)
        market_fair_odds = (1.0 / market_prob) if market_prob else None

        home_team_name = team_names.get(fixture.home_team_id, "Home")
        away_team_name = team_names.get(fixture.away_team_id, "Away")
        favorite_team_name = home_team_name if favorite_side == "home" else away_team_name
        underdog_team_name = away_team_name if favorite_side == "home" else home_team_name

        def record(model_name: str, p_joint: Optional[float]) -> None:
            season_accs[season][model_name].record(
                sgp_hit=sgp_hit,
                ml_win=favorite_win,
                ml_odds=ml_odds,
                p_joint=p_joint,
            )
            overall_accs[model_name].record(
                sgp_hit=sgp_hit,
                ml_win=favorite_win,
                ml_odds=ml_odds,
                p_joint=p_joint,
            )
            if candidate_details_csv is None:
                return
            meta = model_meta_by_name[model_name]
            detail_rows.append(
                {
                    "season": season,
                    "fixture_id": fixture.id,
                    "kickoff_at": fixture.kickoff_at.isoformat(),
                    "league": league.name,
                    "home_team": home_team_name,
                    "away_team": away_team_name,
                    "model": model_name,
                    "source_file": meta.source_file,
                    "selection_rule": meta.selection_rule,
                    "favorite_side": favorite_side,
                    "favorite_team": favorite_team_name,
                    "underdog_team": underdog_team_name,
                    "elo_gap": round(v1_pred.elo_gap, 6),
                    "sgp_hit": int(sgp_hit),
                    "ml_win": int(favorite_win),
                    "model_p_joint": round(p_joint, 6) if p_joint is not None else "",
                    "model_fair_odds": round(1.0 / p_joint, 6) if p_joint else "",
                    "market_source": market_source,
                    "market_prob_vig_free": round(market_prob, 6) if market_prob is not None else "",
                    "market_fair_odds": round(market_fair_odds, 6) if market_fair_odds is not None else "",
                    "moneyline_favorite_odds": round(ml_odds, 6) if ml_odds is not None else "",
                    "moneyline_opposite_odds": round(opposite_ml_odds, 6) if opposite_ml_odds is not None else "",
                    "team_total_over_1_5_odds": round(team_total_over_odds, 6) if team_total_over_odds is not None else "",
                    "team_total_under_1_5_odds": round(team_total_under_odds, 6) if team_total_under_odds is not None else "",
                }
            )

        try:
            pred_v2 = engines["V2"].predict(
                home_elo=v1_pred.home_elo,
                away_elo=v1_pred.away_elo,
                home_form=_v1_form_to_v2(v1_pred.home_form),
                away_form=_v1_form_to_v2(v1_pred.away_form),
                league_fit=_v1_league_to_v2(v1_pred.league_fit),
            )
            if pred_v2.is_bully_spot:
                record("V2", pred_v2.p_joint)
        except Exception:
            error_counts["V2"] += 1

        try:
            pred_v2_gpt = engines["GPT V2"].predict(
                home_team=_v1_form_to_v2_gpt(v1_pred.home_form, home_team_name),
                away_team=_v1_form_to_v2_gpt(v1_pred.away_form, away_team_name),
                home_elo=v1_pred.home_elo,
                away_elo=v1_pred.away_elo,
                league=_v1_league_to_v2_gpt(v1_pred.league_fit, league.name),
                market=None,
            )
            if pred_v2_gpt.is_bully_candidate:
                record("GPT V2", pred_v2_gpt.p_joint)
        except Exception:
            error_counts["GPT V2"] += 1

        try:
            pred_v3 = engines["V3"].predict(
                home_team=_v1_form_to_v3(v1_pred.home_form, home_team_name, v3),
                away_team=_v1_form_to_v3(v1_pred.away_form, away_team_name, v3),
                home_elo=v1_pred.home_elo,
                away_elo=v1_pred.away_elo,
                league=_v1_league_to_v3(v1_pred.league_fit, league.name, v3),
                market=_market_line(snapshot, favorite_side, v3),
            )
            if pred_v3.is_bully_candidate:
                record("V3", pred_v3.p_joint)
        except Exception:
            error_counts["V3"] += 1

        try:
            pred_v31 = engines["V3.1"].predict(
                home_team=_v1_form_to_v3(v1_pred.home_form, home_team_name, v31),
                away_team=_v1_form_to_v3(v1_pred.away_form, away_team_name, v31),
                home_elo=v1_pred.home_elo,
                away_elo=v1_pred.away_elo,
                league=_v1_league_to_v3(v1_pred.league_fit, league.name, v31),
                market=_market_line(snapshot, favorite_side, v31),
            )
            if pred_v31.is_bully_candidate:
                record("V3.1", pred_v31.p_joint)
        except Exception:
            error_counts["V3.1"] += 1

        try:
            pred_v32 = engines["V3.2"].predict(
                home_team=_v1_form_to_v3(v1_pred.home_form, home_team_name, v32),
                away_team=_v1_form_to_v3(v1_pred.away_form, away_team_name, v32),
                home_elo=v1_pred.home_elo,
                away_elo=v1_pred.away_elo,
                league=_v1_league_to_v3(v1_pred.league_fit, league.name, v32),
                market=_market_line(snapshot, favorite_side, v32),
            )
            if pred_v32.is_bully_candidate:
                record("V3.2", pred_v32.p_joint)
        except Exception:
            error_counts["V3.2"] += 1

        try:
            pred_v325 = engines["V3.2.5"].predict(
                home_team=_v1_form_to_v3(v1_pred.home_form, home_team_name, v325),
                away_team=_v1_form_to_v3(v1_pred.away_form, away_team_name, v325),
                home_elo=v1_pred.home_elo,
                away_elo=v1_pred.away_elo,
                league=_v1_league_to_v3(v1_pred.league_fit, league.name, v325),
                market=_market_line(snapshot, favorite_side, v325),
            )
            if pred_v325.is_bully_candidate:
                record("V3.2.5", pred_v325.p_joint)
        except Exception:
            error_counts["V3.2.5"] += 1

        try:
            home_v33 = _v1_form_to_v33(v1_pred.home_form, home_team_name)
            away_v33 = _v1_form_to_v33(v1_pred.away_form, away_team_name)
            fav_v33, dog_v33 = (home_v33, away_v33) if favorite_side == "home" else (away_v33, home_v33)
            pred_v33 = v33.predict(fav_v33, dog_v33, _v1_league_to_v33(v1_pred.league_fit))
            if pred_v33["p_joint"] >= V33_MIN_P_JOINT and (
                min_elo_gap is None or v1_pred.elo_gap >= min_elo_gap
            ):
                record("V3.3GPT", float(pred_v33["p_joint"]))
        except Exception:
            error_counts["V3.3GPT"] += 1

        if idx % 250 == 0:
            print(f"  processed {idx}/{len(fixtures_with_results)} fixtures...")

    rows: list[dict[str, object]] = []
    for season in seasons:
        _print_table(season, season_accs[season], season_fixture_counts[season], model_meta)
        for meta in model_meta:
            rows.append(season_accs[season][meta.name].to_row(season, season_fixture_counts[season]))

    total_processed = sum(season_fixture_counts.values())
    _print_table("AGGREGATE", overall_accs, total_processed, model_meta)
    for meta in model_meta:
        rows.append(overall_accs[meta.name].to_row("aggregate", total_processed))

    _write_csv(csv_out, rows)
    if candidate_details_csv is not None:
        _write_candidate_details_csv(candidate_details_csv, detail_rows)

    latest_kickoff = max(fixture.kickoff_at for fixture, _result in fixtures_with_results)
    print("\nRun details:")
    print(f"  Processed fixtures: {total_processed}")
    print(f"  Skipped (missing league): {skipped_no_league}")
    print(f"  Skipped (no V1 feature snapshot): {skipped_no_v1_pred}")
    print(f"  Latest fixture in queried data: {latest_kickoff}")
    if min_elo_gap is not None:
        print(f"  Elo gate override: {min_elo_gap:.0f}")
    print(f"  CSV written to: {csv_out}")
    if candidate_details_csv is not None:
        print(f"  Candidate pricing CSV written to: {candidate_details_csv}")
    print("  ROI uses favorite moneyline odds as a pricing proxy.")
    print("  Candidate pricing CSV surfaces favorite team-total 1.5 odds and synthesized joint fair odds when available.")
    print("  V3.3GPT uses an inferred p_joint >= 0.42 gate because the source file has no native candidate flag.")
    nonzero_errors = {name: count for name, count in error_counts.items() if count}
    if nonzero_errors:
        print(f"  Model exceptions encountered: {nonzero_errors}")

    session.close()


if __name__ == "__main__":
    args = parse_args()
    seasons = tuple(args.seasons or SEASON_ORDER)
    run(
        seasons=seasons,
        csv_out=Path(args.csv_out),
        min_elo_gap=args.min_elo_gap,
        candidate_details_csv=Path(args.candidate_details_csv) if args.candidate_details_csv else None,
    )
