from datetime import datetime, timezone, timedelta

from app.db.models import LineMovement
from app.steam_resistance import steam_move_pct, apply_steam, THRESHOLD


def _add(db, fixture_id, market, line, odds, minutes_ago):
    db.add(LineMovement(
        fixture_id=fixture_id, book="pinnacle", market=market, line=line,
        odds=odds,
        recorded_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    ))


def test_no_data_returns_zero(db):
    assert steam_move_pct(db, 1, "spread", "home", -0.5) == 0.0


def test_single_row_returns_zero(db):
    _add(db, 1, "spread", -0.5, -110, 60)
    db.flush()
    assert steam_move_pct(db, 1, "spread", "home", -0.5) == 0.0


def test_positive_move(db):
    _add(db, 1, "spread", -0.5, -100, 120)
    _add(db, 1, "spread", -0.5, -110, 1)
    db.flush()
    pct = steam_move_pct(db, 1, "spread", "home", -0.5)
    assert pct == -0.10  # (-110 - -100)/100 = -0.10


def test_apply_steam_below_threshold():
    tier, flag = apply_steam("HIGH", 0.01)
    assert tier == "HIGH" and flag is False


def test_apply_steam_at_threshold():
    tier, flag = apply_steam("HIGH", THRESHOLD)
    assert tier == "MEDIUM" and flag is True


def test_downgrade_ladder():
    assert apply_steam("ELITE", 0.05)[0] == "HIGH"
    assert apply_steam("HIGH", 0.05)[0] == "MEDIUM"
    assert apply_steam("MEDIUM", 0.05)[0] == "SKIP"
    assert apply_steam("SKIP", 0.05)[0] == "SKIP"


def test_opposite_direction_does_not_downgrade():
    tier, flag = apply_steam("HIGH", -0.05)
    assert tier == "HIGH" and flag is False
