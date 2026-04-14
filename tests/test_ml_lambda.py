from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pytest

from app.db.models import League, Team, Fixture, MLArtifact
from app.features import FEATURE_NAMES
from app.ml_lambda import MLLambdaPredictor, FeatureDriftError


class StubModel:
    def __init__(self, v): self.v = v
    def predict(self, X): return np.array([self.v])


@pytest.fixture
def fx(db):
    lg = League(name="EPL", country="E", espn_id="eng.1", odds_api_key="x")
    db.add(lg); db.flush()
    h = Team(name="H", league_id=lg.id); a = Team(name="A", league_id=lg.id)
    db.add_all([h, a]); db.flush()
    f = Fixture(home_team_id=h.id, away_team_id=a.id, league_id=lg.id,
                kickoff_at=datetime.now(timezone.utc), status="scheduled")
    db.add(f); db.flush()
    return f


def _save(tmp_path, feature_names=None) -> Path:
    p = tmp_path / "art.pkl"
    joblib.dump({
        "home_model": StubModel(1.7),
        "away_model": StubModel(1.1),
        "feature_names": feature_names or FEATURE_NAMES,
        "metrics": {}, "trained_at": "v1",
    }, p)
    return p


def test_predict_returns_floor(tmp_path, db, fx):
    p = _save(tmp_path)
    pred = MLLambdaPredictor(db, artifact_path=p)
    lh, la = pred.predict(fx)
    assert lh == pytest.approx(1.7)
    assert la == pytest.approx(1.1)


def test_predict_enforces_minimum(tmp_path, db, fx):
    p = tmp_path / "a.pkl"
    joblib.dump({
        "home_model": StubModel(0.0), "away_model": StubModel(-1.0),
        "feature_names": FEATURE_NAMES, "metrics": {}, "trained_at": "v",
    }, p)
    pred = MLLambdaPredictor(db, artifact_path=p)
    lh, la = pred.predict(fx)
    assert lh >= 0.1 and la >= 0.1


def test_feature_drift_raises(tmp_path, db):
    p = _save(tmp_path, feature_names=["x", "y"])
    with pytest.raises(FeatureDriftError):
        MLLambdaPredictor(db, artifact_path=p)


def test_missing_artifact_raises(db, tmp_path):
    with pytest.raises(FileNotFoundError):
        MLLambdaPredictor(db, artifact_path=tmp_path / "nope.pkl")


def test_resolves_active_artifact_from_db(tmp_path, db, fx):
    p = _save(tmp_path)
    db.add(MLArtifact(name="ml_lambda", version="v1", path=str(p),
                      active=True, trained_at=datetime.now(timezone.utc)))
    db.flush()
    pred = MLLambdaPredictor(db)
    lh, _ = pred.predict(fx)
    assert lh == pytest.approx(1.7)


def test_no_active_artifact_raises(db):
    with pytest.raises(FileNotFoundError):
        MLLambdaPredictor(db)
