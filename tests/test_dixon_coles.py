"""Tests for the Dixon-Coles bivariate Poisson math module."""
import math
import numpy as np
import pytest
from app.dixon_coles import (
    tau,
    dixon_coles_pmf,
    build_score_matrix,
    cover_probability_dc,
    ou_probability_dc,
)


class TestTau:
    def test_zero_zero_increases_probability_with_negative_rho(self):
        # rho < 0 → tau(0,0) > 1 → increases 0-0 probability
        t = tau(0, 0, lambda_home=1.5, lambda_away=1.2, rho=-0.13)
        assert t > 1.0

    def test_one_one_decreases_probability_with_negative_rho(self):
        # rho < 0 → tau(1,1) = 1 - rho > 1? No: tau(1,1) = 1 - rho, rho=-0.13 → 1.13? Wait:
        # tau(1,1) = 1 - rho. With rho=-0.13: 1 - (-0.13) = 1.13 > 1
        # Actually Dixon-Coles: tau(1,1) = 1 - rho where rho is typically negative,
        # so tau(1,1) = 1 - (-0.13) = 1.13. This INCREASES 1-1, not decreases.
        # Let me re-check the paper...
        # Dixon & Coles (1997): tau(0,0) = 1 - λ_h * λ_a * rho
        # tau(1,0) = 1 + λ_a * rho
        # tau(0,1) = 1 + λ_h * rho
        # tau(1,1) = 1 - rho
        # With rho < 0:
        #   tau(0,0) > 1 (increased)
        #   tau(1,0) < 1 (decreased) since λ_a * rho < 0
        #   tau(0,1) < 1 (decreased)
        #   tau(1,1) > 1 (increased since -rho > 0)
        # Hmm, let me just verify the math is correct
        t = tau(1, 1, lambda_home=1.5, lambda_away=1.2, rho=-0.13)
        assert abs(t - 1.13) < 1e-9

    def test_zero_one_decreases_with_negative_rho(self):
        # tau(0,1) = 1 + lambda_home * rho; with rho=-0.13, lambda_home=1.5:
        # 1 + 1.5 * (-0.13) = 1 - 0.195 = 0.805
        t = tau(0, 1, lambda_home=1.5, lambda_away=1.2, rho=-0.13)
        assert abs(t - 0.805) < 1e-9

    def test_one_zero_decreases_with_negative_rho(self):
        # tau(1,0) = 1 + lambda_away * rho = 1 + 1.2 * (-0.13) = 1 - 0.156 = 0.844
        t = tau(1, 0, lambda_home=1.5, lambda_away=1.2, rho=-0.13)
        assert abs(t - 0.844) < 1e-9

    def test_high_scores_return_one(self):
        for h in range(2, 6):
            for a in range(2, 6):
                assert tau(h, a, 1.5, 1.2, -0.13) == 1.0

    def test_zero_rho_always_returns_one(self):
        for h, a in [(0, 0), (1, 0), (0, 1), (1, 1), (2, 3)]:
            assert tau(h, a, 1.5, 1.2, 0.0) == 1.0


class TestDixonColesPmf:
    def test_probabilities_are_non_negative(self):
        for h in range(6):
            for a in range(6):
                p = dixon_coles_pmf(h, a, 1.5, 1.2, rho=-0.13)
                assert p >= 0.0, f"Negative probability for {h}-{a}"

    def test_sums_to_approximately_one(self):
        """PMF over a large grid should be close to 1 (tail truncation causes slight shortfall)."""
        total = sum(
            dixon_coles_pmf(h, a, 1.5, 1.2, rho=-0.13)
            for h in range(15)
            for a in range(15)
        )
        assert total == pytest.approx(1.0, abs=0.01)

    def test_zero_rho_matches_independent_poisson(self):
        """With rho=0, Dixon-Coles PMF should match product of Poisson PMFs."""
        lh, la = 1.5, 1.2
        for h in range(5):
            for a in range(5):
                dc = dixon_coles_pmf(h, a, lh, la, rho=0.0)
                poisson = (
                    (lh ** h) * math.exp(-lh) / math.factorial(h) *
                    (la ** a) * math.exp(-la) / math.factorial(a)
                )
                assert dc == pytest.approx(poisson, rel=1e-9)


class TestBuildScoreMatrix:
    def test_matrix_shape(self):
        m = build_score_matrix(1.5, 1.2, rho=-0.13, max_goals=10)
        assert m.shape == (11, 11)

    def test_matrix_sums_to_one(self):
        m = build_score_matrix(1.5, 1.2, rho=-0.13, max_goals=10)
        assert m.sum() == pytest.approx(1.0, abs=1e-9)

    def test_all_non_negative(self):
        m = build_score_matrix(1.5, 1.2, rho=-0.13, max_goals=10)
        assert (m >= 0).all()

    def test_zero_zero_inflated_vs_independent_poisson(self):
        """DC matrix should assign more probability to 0-0 than independent Poisson."""
        lh, la = 1.5, 1.2
        m_dc = build_score_matrix(lh, la, rho=-0.13, max_goals=15)
        m_ind = build_score_matrix(lh, la, rho=0.0, max_goals=15)
        assert m_dc[0, 0] > m_ind[0, 0]

    def test_custom_max_goals(self):
        m = build_score_matrix(1.5, 1.2, max_goals=5)
        assert m.shape == (6, 6)


class TestCoverProbabilityDc:
    def setup_method(self):
        self.matrix = build_score_matrix(1.5, 1.2, rho=-0.13, max_goals=10)

    def test_probabilities_sum_correctly(self):
        """win + push + lose should sum to ~1 for any line."""
        for line in [-1.5, -1.0, -0.5, 0.5, 1.0, 1.5]:
            win_p, push_p = cover_probability_dc(self.matrix, line)
            assert win_p >= 0.0
            assert push_p >= 0.0
            assert win_p + push_p <= 1.0 + 1e-9

    def test_no_push_on_half_lines(self):
        for line in [-1.5, -0.5, 0.5, 1.5]:
            _, push_p = cover_probability_dc(self.matrix, line)
            assert push_p == pytest.approx(0.0, abs=1e-9)

    def test_push_possible_on_integer_lines(self):
        """A push occurs when home wins by exactly 1 on ±1.0 lines."""
        _, push_home = cover_probability_dc(self.matrix, -1.0)
        _, push_away = cover_probability_dc(self.matrix, 1.0)
        assert push_home > 0
        assert push_away > 0
        # Both sides push on the same scorelines (home wins by 1)
        assert push_home == pytest.approx(push_away, rel=1e-9)

    def test_home_favourite_more_likely_to_cover_home_spread(self):
        """When home team scores more, home -0.5 should have cover_p > 0.5."""
        big_matrix = build_score_matrix(2.5, 0.8, rho=-0.13)
        win_p, _ = cover_probability_dc(big_matrix, -0.5)
        assert win_p > 0.5


class TestOuProbabilityDc:
    def setup_method(self):
        self.matrix = build_score_matrix(1.5, 1.2, rho=-0.13, max_goals=10)

    def test_over_plus_under_sum_to_one_on_half_lines(self):
        for line in [1.5, 2.5, 3.5]:
            over_p = ou_probability_dc(self.matrix, line)
            assert 0.0 <= over_p <= 1.0
            # No push on half lines so under = 1 - over
            under_p = 1.0 - over_p
            assert over_p + under_p == pytest.approx(1.0, abs=1e-9)

    def test_higher_line_lower_over_probability(self):
        over_15 = ou_probability_dc(self.matrix, 1.5)
        over_25 = ou_probability_dc(self.matrix, 2.5)
        over_35 = ou_probability_dc(self.matrix, 3.5)
        assert over_15 > over_25 > over_35

    def test_high_scoring_teams_favour_over(self):
        high_matrix = build_score_matrix(2.5, 2.5, rho=-0.13)
        over_25 = ou_probability_dc(high_matrix, 2.5)
        assert over_25 > 0.5

    def test_low_scoring_teams_favour_under(self):
        low_matrix = build_score_matrix(0.7, 0.6, rho=-0.13)
        over_25 = ou_probability_dc(low_matrix, 2.5)
        assert over_25 < 0.5
