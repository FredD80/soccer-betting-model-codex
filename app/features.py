"""
Per-fixture feature vector assembly for the ML λ predictor.

This module is stateless and deterministic given DB state. It must be used
identically at training time (over historical fixtures) and serving time
(over upcoming fixtures) — any drift between these two paths corrupts the
learned model.

Missing joins → np.nan; XGBoost handles NaN natively without imputation.
"""
import numpy as np
from app.db.models import (
    FormCache, TacticalProfile, ManagerProfile, PlayerImpact,
    DrawPropensity, OddsSnapshot, League, Result,
)


FEATURE_NAMES: list[str] = [
    # Form (8)
    "home_goals_scored_avg",
    "home_goals_conceded_avg",
    "away_goals_scored_avg",
    "away_goals_conceded_avg",
    "home_ou_25_rate",
    "away_ou_25_rate",
    "home_spread_cover_rate",
    "away_spread_cover_rate",
    # xG (4)
    "home_xg_scored_avg",
    "home_xg_conceded_avg",
    "away_xg_scored_avg",
    "away_xg_conceded_avg",
    # Tactical (6)
    "home_ppda",
    "away_ppda",
    "home_press_resistance",
    "away_press_resistance",
    "home_set_piece_pct",
    "home_aerial_win_rate",
    # Manager (2)
    "home_mgr_draw_tendency",
    "away_mgr_draw_tendency",
    # Player impact (2)
    "home_absent_xg_pct",
    "away_absent_xg_pct",
    # Draw propensity (1)
    "draw_propensity_score",
    # Market (2)
    "pinnacle_implied_home",
    "pinnacle_implied_away",
    # League context (1)
    "league_avg_goals",
    # Derived interactions (5)
    "home_xg_diff",              # home_xg_scored - away_xg_conceded
    "away_xg_diff",              # away_xg_scored - home_xg_conceded
    "goals_scored_diff",         # home - away
    "form_momentum",             # home_cover_rate - away_cover_rate
    "is_top_league",             # 1 if league ∈ top-5 else 0
]

N_FEATURES: int = len(FEATURE_NAMES)

TOP_LEAGUES = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}


def _get_form(session, team_id: int, is_home: bool) -> FormCache | None:
    return session.query(FormCache).filter_by(team_id=team_id, is_home=is_home).first()


def _get_tactical(session, team_id: int) -> TacticalProfile | None:
    return (
        session.query(TacticalProfile)
        .filter_by(team_id=team_id)
        .order_by(TacticalProfile.season.desc())
        .first()
    )


def _get_manager(session, team_id: int) -> ManagerProfile | None:
    return (
        session.query(ManagerProfile)
        .filter_by(team_id=team_id)
        .order_by(ManagerProfile.tenure_games.desc())
        .first()
    )


def _absent_xg_pct(session, fixture_id: int, team_id: int) -> float:
    rows = (
        session.query(PlayerImpact)
        .filter_by(fixture_id=fixture_id, team_id=team_id, is_absent=True)
        .all()
    )
    if not rows:
        return np.nan
    return float(sum((r.xg_contribution_pct or 0.0) for r in rows))


def _pinnacle_implied(session, fixture_id: int) -> tuple[float, float]:
    snap = (
        session.query(OddsSnapshot)
        .filter_by(fixture_id=fixture_id, bookmaker="pinnacle")
        .order_by(OddsSnapshot.captured_at.desc())
        .first()
    )
    if snap is None or not snap.home_odds or not snap.away_odds:
        return np.nan, np.nan
    return 1.0 / snap.home_odds, 1.0 / snap.away_odds


def _league_avg_goals(session, league_id: int) -> float:
    """Historical mean total_goals for completed fixtures in this league."""
    from app.db.models import Fixture
    rows = (
        session.query(Result.total_goals)
        .join(Fixture, Result.fixture_id == Fixture.id)
        .filter(Fixture.league_id == league_id)
        .filter(Result.total_goals.isnot(None))
        .limit(500)
        .all()
    )
    if not rows:
        return np.nan
    return float(np.mean([r[0] for r in rows]))


def build_feature_vector(session, fixture) -> np.ndarray:
    """
    Build a 1D numpy array of length N_FEATURES from DB state as-of
    kickoff. Only reads pre-kickoff information. Missing → np.nan.
    """
    home_form = _get_form(session, fixture.home_team_id, is_home=True)
    away_form = _get_form(session, fixture.away_team_id, is_home=False)
    home_tac = _get_tactical(session, fixture.home_team_id)
    away_tac = _get_tactical(session, fixture.away_team_id)
    home_mgr = _get_manager(session, fixture.home_team_id)
    away_mgr = _get_manager(session, fixture.away_team_id)

    draw = (
        session.query(DrawPropensity)
        .filter_by(fixture_id=fixture.id)
        .first()
    )
    imp_home, imp_away = _pinnacle_implied(session, fixture.id)
    abs_home = _absent_xg_pct(session, fixture.id, fixture.home_team_id)
    abs_away = _absent_xg_pct(session, fixture.id, fixture.away_team_id)
    league_avg = _league_avg_goals(session, fixture.league_id)
    league = session.query(League).filter_by(id=fixture.league_id).first()
    is_top = 1.0 if (league and league.espn_id in TOP_LEAGUES) else 0.0

    g = lambda obj, attr: getattr(obj, attr, None) if obj else None
    f = lambda v: float(v) if v is not None else np.nan

    hgs = f(g(home_form, "goals_scored_avg"))
    hgc = f(g(home_form, "goals_conceded_avg"))
    ags = f(g(away_form, "goals_scored_avg"))
    agc = f(g(away_form, "goals_conceded_avg"))
    hcr = f(g(home_form, "spread_cover_rate"))
    acr = f(g(away_form, "spread_cover_rate"))
    hxs = f(g(home_form, "xg_scored_avg"))
    hxc = f(g(home_form, "xg_conceded_avg"))
    axs = f(g(away_form, "xg_scored_avg"))
    axc = f(g(away_form, "xg_conceded_avg"))

    vec = np.array([
        hgs, hgc, ags, agc,
        f(g(home_form, "ou_hit_rate_25")), f(g(away_form, "ou_hit_rate_25")),
        hcr, acr,
        hxs, hxc, axs, axc,
        f(g(home_tac, "ppda")), f(g(away_tac, "ppda")),
        f(g(home_tac, "press_resistance")), f(g(away_tac, "press_resistance")),
        f(g(home_tac, "set_piece_pct_scored")), f(g(home_tac, "aerial_win_rate")),
        f(g(home_mgr, "draw_tendency_underdog")), f(g(away_mgr, "draw_tendency_underdog")),
        abs_home, abs_away,
        f(g(draw, "score")),
        imp_home, imp_away,
        league_avg,
        # Derived interactions
        (hxs - axc) if not (np.isnan(hxs) or np.isnan(axc)) else np.nan,
        (axs - hxc) if not (np.isnan(axs) or np.isnan(hxc)) else np.nan,
        (hgs - ags) if not (np.isnan(hgs) or np.isnan(ags)) else np.nan,
        (hcr - acr) if not (np.isnan(hcr) or np.isnan(acr)) else np.nan,
        is_top,
    ], dtype=np.float64)

    assert vec.shape == (N_FEATURES,), f"Vector shape {vec.shape} != ({N_FEATURES},)"
    return vec
