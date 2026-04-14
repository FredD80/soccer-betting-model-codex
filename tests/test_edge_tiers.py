import pytest
from app.edge_tiers import edge_tier, kelly_fraction


def test_skip_below_2pct():
    assert edge_tier(0.01) == "SKIP"
    assert edge_tier(0.0) == "SKIP"
    assert edge_tier(-0.1) == "SKIP"
    assert edge_tier(None) == "SKIP"


def test_bucket_boundaries():
    assert edge_tier(0.02) == "MEDIUM"
    assert edge_tier(0.049) == "MEDIUM"
    assert edge_tier(0.05) == "HIGH"
    assert edge_tier(0.099) == "HIGH"
    assert edge_tier(0.10) == "ELITE"
    assert edge_tier(0.25) == "ELITE"


def test_kelly_zero_when_skip():
    assert kelly_fraction("SKIP", 0.5, 2.0) == 0.0


def test_kelly_zero_when_full_negative():
    # model says 0.3, odds 2.0 → b=1, full = (0.3 - 0.7)/1 = -0.4 → clamped to 0
    assert kelly_fraction("HIGH", 0.3, 2.0) == 0.0


def test_kelly_analytic():
    # p=0.6, odds=2.0 → b=1, full=(0.6 - 0.4)/1 = 0.2, ELITE mult=0.25 → 0.05
    assert kelly_fraction("ELITE", 0.6, 2.0) == pytest.approx(0.05)
    # HIGH mult 0.15 → 0.03
    assert kelly_fraction("HIGH", 0.6, 2.0) == pytest.approx(0.03)


def test_kelly_zero_for_invalid_odds():
    assert kelly_fraction("HIGH", 0.6, None) == 0.0
    assert kelly_fraction("HIGH", 0.6, 1.0) == 0.0
