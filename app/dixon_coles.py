"""
Dixon-Coles bivariate Poisson model.

Reference: Dixon & Coles (1997), "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market", JRSS-C 46(2): 265–280.

The tau (τ) correction adjusts for the systematic over-representation of
low-scoring outcomes (0-0, 1-0, 0-1, 1-1) relative to independent Poisson.
rho < 0 is the empirically fitted correlation parameter (typically -0.10 to -0.16).
"""
import math
import numpy as np


def tau(
    home_goals: int,
    away_goals: int,
    lambda_home: float,
    lambda_away: float,
    rho: float,
) -> float:
    """
    Dixon-Coles low-score correlation correction factor (τ).

    rho < 0 increases probability of 0-0, 1-0, 0-1 and decreases 1-1.
    rho == 0 reduces to independent Poisson (τ == 1 everywhere).

    Applied only for h, a in {0, 1}; returns 1.0 for all other scorelines.
    """
    if home_goals == 0 and away_goals == 0:
        return 1.0 - lambda_home * lambda_away * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + lambda_away * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + lambda_home * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def dixon_coles_pmf(
    home_goals: int,
    away_goals: int,
    lambda_home: float,
    lambda_away: float,
    rho: float = -0.13,
) -> float:
    """
    P(home=h, away=a) under Dixon-Coles bivariate Poisson.

    = τ(h, a) × Poisson(h; λ_home) × Poisson(a; λ_away)
    """
    p_home = (lambda_home ** home_goals) * math.exp(-lambda_home) / math.factorial(home_goals)
    p_away = (lambda_away ** away_goals) * math.exp(-lambda_away) / math.factorial(away_goals)
    return tau(home_goals, away_goals, lambda_home, lambda_away, rho) * p_home * p_away


def build_score_matrix(
    lambda_home: float,
    lambda_away: float,
    rho: float = -0.13,
    max_goals: int = 10,
) -> np.ndarray:
    """
    Build an (max_goals+1) × (max_goals+1) matrix M where
    M[h, a] = P(home_goals=h, away_goals=a).

    Rows index home goals (0..max_goals), columns index away goals.
    Normalised to sum to 1 after tau correction.
    """
    n = max_goals + 1
    matrix = np.zeros((n, n))
    for h in range(n):
        for a in range(n):
            matrix[h, a] = dixon_coles_pmf(h, a, lambda_home, lambda_away, rho)
    total = matrix.sum()
    if total > 0:
        matrix /= total
    return matrix


def cover_probability_dc(
    score_matrix: np.ndarray,
    line: float,
) -> tuple[float, float]:
    """
    Cover probability for a goal-line spread bet using a DC score matrix.

    line < 0 → home spread  (home must win by more than |line| goals)
    line > 0 → away spread  (away covers unless home wins by more than line)

    Returns (win_probability, push_probability).
    Push is non-zero only on integer lines when home wins by exactly |line|.
    """
    n = score_matrix.shape[0]
    win_p = 0.0
    push_p = 0.0
    is_integer_line = abs(round(abs(line)) - abs(line)) < 0.01

    for h in range(n):
        for a in range(n):
            margin = h - a
            p = float(score_matrix[h, a])
            if line < 0:
                threshold = abs(line)
                if margin > threshold:
                    win_p += p
                elif is_integer_line and margin == round(threshold):
                    push_p += p
            else:
                threshold = line
                if margin < threshold:
                    win_p += p
                elif is_integer_line and margin == round(threshold):
                    push_p += p

    return win_p, push_p


def spread_cover_dc(
    score_matrix: np.ndarray,
    team_side: str,
    line: float,
) -> tuple[float, float]:
    """
    Cover probability for a team-side spread bet.

    `line` is the book line from that team's perspective
    (e.g. Sassuolo -1 → team_side="away", line=-1.0).

    Home covers iff (h - a) + line > 0.
    Away covers iff (a - h) + line > 0.
    Push only on integer lines when the adjusted margin == 0.
    """
    n = score_matrix.shape[0]
    win_p = 0.0
    push_p = 0.0
    is_integer_line = abs(round(line) - line) < 1e-6
    for h in range(n):
        for a in range(n):
            margin = (h - a) if team_side == "home" else (a - h)
            adj = margin + line
            p = float(score_matrix[h, a])
            if adj > 0:
                win_p += p
            elif is_integer_line and adj == 0:
                push_p += p
    return win_p, push_p


def ou_probability_dc(
    score_matrix: np.ndarray,
    line: float,
) -> float:
    """
    P(total goals > line) using a DC score matrix.

    For half-ball lines (1.5, 2.5, 3.5) no push is possible.
    """
    n = score_matrix.shape[0]
    over_p = 0.0
    for h in range(n):
        for a in range(n):
            if h + a > line:
                over_p += float(score_matrix[h, a])
    return over_p


def moneyline_probability_dc(score_matrix: np.ndarray) -> tuple[float, float, float]:
    """Return (home_win, draw, away_win) probabilities from a DC score matrix."""
    n = score_matrix.shape[0]
    home_p = draw_p = away_p = 0.0
    for h in range(n):
        for a in range(n):
            p = float(score_matrix[h, a])
            if h > a:
                home_p += p
            elif h == a:
                draw_p += p
            else:
                away_p += p
    return home_p, draw_p, away_p
