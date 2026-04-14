"""Tests for the Monte Carlo simulator."""
import json
import numpy as np
import pytest
from app.dixon_coles import build_score_matrix
from app.monte_carlo import MonteCarloSimulator, MonteCarloResult


@pytest.fixture
def balanced_matrix():
    """Score matrix for roughly balanced teams (λ_home=1.5, λ_away=1.2)."""
    return build_score_matrix(1.5, 1.2, rho=-0.13)


@pytest.fixture
def simulator():
    return MonteCarloSimulator(n_simulations=10_000, seed=42)


class TestMonteCarloSimulator:
    def test_returns_monte_carlo_result(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        assert isinstance(result, MonteCarloResult)

    def test_outcome_probs_sum_to_one(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        total = result.home_win_prob + result.draw_prob + result.away_win_prob
        assert total == pytest.approx(1.0, abs=0.01)

    def test_all_probs_between_zero_and_one(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        for attr in ("home_win_prob", "draw_prob", "away_win_prob",
                     "over_15_prob", "over_25_prob", "over_35_prob"):
            val = getattr(result, attr)
            assert 0.0 <= val <= 1.0, f"{attr} out of range: {val}"

    def test_over_probabilities_decrease_with_higher_line(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        assert result.over_15_prob > result.over_25_prob > result.over_35_prob

    def test_home_advantage_reflected_in_results(self):
        """Strong home team should win majority of simulations."""
        matrix = build_score_matrix(3.0, 0.5, rho=-0.13)
        sim = MonteCarloSimulator(n_simulations=20_000, seed=7)
        result = sim.run(matrix)
        assert result.home_win_prob > 0.8

    def test_scoreline_json_is_valid_json(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        parsed = json.loads(result.scoreline_json)
        assert isinstance(parsed, list)

    def test_scoreline_json_has_at_most_20_entries(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        parsed = json.loads(result.scoreline_json)
        assert len(parsed) <= 20

    def test_scoreline_json_entries_have_required_keys(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        parsed = json.loads(result.scoreline_json)
        for entry in parsed:
            assert "h" in entry
            assert "a" in entry
            assert "p" in entry

    def test_scoreline_json_sorted_by_probability_descending(self, simulator, balanced_matrix):
        result = simulator.run(balanced_matrix)
        parsed = json.loads(result.scoreline_json)
        probs = [e["p"] for e in parsed]
        assert probs == sorted(probs, reverse=True)

    def test_top_scoreline_is_plausible(self, simulator, balanced_matrix):
        """The most likely scoreline for λ_home=1.5, λ_away=1.2 should be 1-1 or 1-0 or 2-1."""
        result = simulator.run(balanced_matrix)
        parsed = json.loads(result.scoreline_json)
        top = parsed[0]
        # Top scoreline should be a low-scoring result
        assert top["h"] + top["a"] <= 4

    def test_reproducible_with_same_seed(self, balanced_matrix):
        s1 = MonteCarloSimulator(n_simulations=1000, seed=99)
        s2 = MonteCarloSimulator(n_simulations=1000, seed=99)
        r1 = s1.run(balanced_matrix)
        r2 = s2.run(balanced_matrix)
        assert r1.home_win_prob == r2.home_win_prob
        assert r1.draw_prob == r2.draw_prob

    def test_statistical_accuracy_within_tolerance(self):
        """
        Analytical DC probabilities should be close to Monte Carlo estimates
        (within 3 percentage points at 10k simulations).
        """
        from app.dixon_coles import ou_probability_dc
        matrix = build_score_matrix(1.8, 1.4, rho=-0.13)
        analytical_over_25 = ou_probability_dc(matrix, 2.5)

        sim = MonteCarloSimulator(n_simulations=50_000, seed=0)
        result = sim.run(matrix)

        assert abs(result.over_25_prob - analytical_over_25) < 0.03
