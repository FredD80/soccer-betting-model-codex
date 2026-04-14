"""
Monte Carlo simulation over the Dixon-Coles score matrix.

Samples N_SIMULATIONS scorelines from the DC probability matrix using
numpy's vectorised multinomial sampling to compute outcome distributions
without enumerating all score combinations explicitly.
"""
import json
import numpy as np
from dataclasses import dataclass

N_SIMULATIONS = 10_000
MAX_GOALS = 10


@dataclass
class MonteCarloResult:
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    over_15_prob: float
    over_25_prob: float
    over_35_prob: float
    scoreline_json: str  # JSON array of top-20 scorelines by analytical probability


class MonteCarloSimulator:
    def __init__(self, n_simulations: int = N_SIMULATIONS, seed: int | None = None):
        self.n_simulations = n_simulations
        self._rng = np.random.default_rng(seed)

    def run(self, score_matrix: np.ndarray) -> MonteCarloResult:
        """
        Sample n_simulations scorelines from score_matrix and compute
        aggregate outcome probabilities.

        score_matrix[h, a] = P(home_goals=h, away_goals=a)
        """
        n = score_matrix.shape[0]
        flat_probs = score_matrix.flatten().copy()
        flat_probs = np.maximum(flat_probs, 0.0)
        flat_probs /= flat_probs.sum()

        # Vectorised multinomial sample
        indices = self._rng.choice(len(flat_probs), size=self.n_simulations, p=flat_probs)
        home_goals = indices // n
        away_goals = indices % n
        total_goals = home_goals + away_goals
        margin = home_goals - away_goals

        return MonteCarloResult(
            home_win_prob=float((margin > 0).mean()),
            draw_prob=float((margin == 0).mean()),
            away_win_prob=float((margin < 0).mean()),
            over_15_prob=float((total_goals > 1.5).mean()),
            over_25_prob=float((total_goals > 2.5).mean()),
            over_35_prob=float((total_goals > 3.5).mean()),
            scoreline_json=self._top_scorelines(score_matrix),
        )

    @staticmethod
    def _top_scorelines(score_matrix: np.ndarray, top_n: int = 20) -> str:
        """Return JSON of top-N scorelines ordered by analytical DC probability."""
        n = score_matrix.shape[0]
        entries = [
            {"h": h, "a": a, "p": round(float(score_matrix[h, a]), 6)}
            for h in range(n)
            for a in range(n)
        ]
        entries.sort(key=lambda x: x["p"], reverse=True)
        return json.dumps(entries[:top_n])
