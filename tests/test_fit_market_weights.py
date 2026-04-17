from datetime import datetime, timezone, timedelta
import pytest
import numpy as np

from app.db.models import (
    League, Team, Fixture, ModelVersion, Result, OddsSnapshot,
    SpreadPrediction, MoneylinePrediction, MarketWeights,
)
from scripts.fit_market_weights import fit, InsufficientDataError


def _seed(db, n, model_reliable=True, market_reliable=False):
    lg = League(name="EPL", country="E", espn_id="eng.1", odds_api_key="x")
    db.add(lg); db.flush()
    h = Team(name="H", league_id=lg.id); a = Team(name="A", league_id=lg.id)
    db.add_all([h, a]); db.flush()
    mv = ModelVersion(name="spread_v1", version="1", active=True)
    db.add(mv); db.flush()
    np.random.seed(0)
    for i in range(n):
        fx = Fixture(home_team_id=h.id, away_team_id=a.id, league_id=lg.id,
                     kickoff_at=datetime.now(timezone.utc) - timedelta(days=i),
                     status="completed")
        db.add(fx); db.flush()
        true_p = float(np.clip(0.3 + 0.4 * np.random.random(), 0.05, 0.95))
        covered = 1 if np.random.random() < true_p else 0
        margin = 1 if covered else -1
        db.add(Result(fixture_id=fx.id, home_score=max(0, margin),
                      away_score=max(0, -margin), total_goals=2))
        # Model predicts truth; market is noise
        model_p = true_p if model_reliable else float(np.random.random())
        market_p = true_p if market_reliable else float(np.random.random())
        market_odds = 1.0 / max(0.05, min(0.95, market_p))
        db.add(OddsSnapshot(
            fixture_id=fx.id, bookmaker="pinnacle",
            spread_home_odds=market_odds, spread_away_odds=market_odds,
            captured_at=datetime.now(timezone.utc) - timedelta(days=i, hours=1),
        ))
        db.add(SpreadPrediction(
            model_id=mv.id, fixture_id=fx.id,
            team_side="home", goal_line=-0.5,
            cover_probability=model_p, push_probability=0.0,
            ev_score=0.0, confidence_tier="HIGH",
            created_at=datetime.now(timezone.utc),
        ))
    db.flush()


def _seed_h2h(db, n, model_reliable=True, market_reliable=False):
    lg = League(name="EPL", country="E", espn_id="eng.1", odds_api_key="x")
    db.add(lg)
    db.flush()
    h = Team(name="H", league_id=lg.id)
    a = Team(name="A", league_id=lg.id)
    db.add_all([h, a])
    db.flush()
    mv = ModelVersion(name="moneyline_v1", version="1", active=True)
    db.add(mv)
    db.flush()
    np.random.seed(1)
    for i in range(n):
        fx = Fixture(
            home_team_id=h.id,
            away_team_id=a.id,
            league_id=lg.id,
            kickoff_at=datetime.now(timezone.utc) - timedelta(days=i),
            status="completed",
        )
        db.add(fx)
        db.flush()

        home_true = float(np.clip(0.25 + 0.30 * np.random.random(), 0.10, 0.70))
        draw_true = 0.20
        away_true = 1.0 - home_true - draw_true
        u = np.random.random()
        if u < home_true:
            outcome = "home"
            scores = (1, 0)
        elif u < home_true + draw_true:
            outcome = "draw"
            scores = (1, 1)
        else:
            outcome = "away"
            scores = (0, 1)

        db.add(Result(
            fixture_id=fx.id,
            home_score=scores[0],
            away_score=scores[1],
            outcome=outcome,
            total_goals=sum(scores),
        ))

        model_probs = (
            {"home": home_true, "draw": draw_true, "away": away_true}
            if model_reliable
            else {"home": 0.33, "draw": 0.34, "away": 0.33}
        )
        market_probs = (
            {"home": home_true, "draw": draw_true, "away": away_true}
            if market_reliable
            else {"home": 0.50, "draw": 0.20, "away": 0.30}
        )
        overround = 1.05
        db.add(OddsSnapshot(
            fixture_id=fx.id,
            bookmaker="pinnacle",
            home_odds=1.0 / (market_probs["home"] * overround),
            draw_odds=1.0 / (market_probs["draw"] * overround),
            away_odds=1.0 / (market_probs["away"] * overround),
            captured_at=datetime.now(timezone.utc) - timedelta(days=i, hours=1),
        ))
        for side in ("home", "draw", "away"):
            db.add(MoneylinePrediction(
                model_id=mv.id,
                fixture_id=fx.id,
                outcome=side,
                probability=model_probs[side],
                ev_score=0.0,
                confidence_tier="HIGH",
                created_at=datetime.now(timezone.utc),
            ))
    db.flush()


def test_insufficient_data_raises(db):
    lg = League(name="EPL", country="E", espn_id="eng.1", odds_api_key="x")
    db.add(lg); db.flush()
    with pytest.raises(InsufficientDataError):
        fit(db, "eng.1", "spread", min_samples=50)


def test_model_dominates_when_market_noise(db):
    _seed(db, 250, model_reliable=True, market_reliable=False)
    w1, w2, _ = fit(db, "eng.1", "spread", min_samples=50)
    assert w1 >= w2  # prefer model
    row = db.query(MarketWeights).filter_by(league_espn_id="eng.1", bet_type="spread").first()
    assert row is not None
    assert row.w_model == pytest.approx(w1)


def test_market_dominates_when_model_noise(db):
    _seed(db, 250, model_reliable=False, market_reliable=True)
    w1, w2, _ = fit(db, "eng.1", "spread", min_samples=50)
    assert w2 >= w1


def test_h2h_model_dominates_when_market_noise(db):
    _seed_h2h(db, 250, model_reliable=True, market_reliable=False)
    w1, w2, _ = fit(db, "eng.1", "h2h", min_samples=50)
    assert w1 >= w2
