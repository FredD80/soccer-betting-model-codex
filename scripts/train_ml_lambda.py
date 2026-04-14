"""
Offline trainer for the (λ_home, λ_away) XGBoost regressor pair.

Reads completed fixtures + results, assembles feature vectors, fits two
count:poisson regressors, saves a joblib artifact under models/artifacts/,
and registers the artifact in ml_artifacts with active=True.

Usage:
    DATABASE_URL=postgresql://... python scripts/train_ml_lambda.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connection import get_engine
from app.db.models import Fixture, Result, MLArtifact
from app.features import FEATURE_NAMES, build_feature_vector


ARTIFACT_DIR = Path(__file__).parent.parent / "models" / "artifacts"
LEAGUE_AVG_GOALS = 1.5


class InsufficientDataError(RuntimeError):
    """Raised when there are fewer completed fixtures than min_samples."""


class BaselineRegressionError(RuntimeError):
    """Raised when ML model fails to beat the heuristic baseline."""


def _heuristic_lambda(session, fixture) -> tuple[float, float]:
    """The current non-ML formula — used as a baseline comparison."""
    from app.db.models import FormCache
    hf = session.query(FormCache).filter_by(team_id=fixture.home_team_id, is_home=True).first()
    af = session.query(FormCache).filter_by(team_id=fixture.away_team_id, is_home=False).first()
    if not hf or not af:
        return 1.5, 1.2  # league-average fallback
    lh = max(0.1, hf.goals_scored_avg * (af.goals_conceded_avg / LEAGUE_AVG_GOALS))
    la = max(0.1, af.goals_scored_avg * (hf.goals_conceded_avg / LEAGUE_AVG_GOALS))
    return lh, la


def _build_dataset(session: Session):
    """Return (X, y_home, y_away, fixtures) for all completed fixtures."""
    rows = (
        session.query(Fixture, Result)
        .join(Result, Result.fixture_id == Fixture.id)
        .filter(Result.home_score.isnot(None))
        .filter(Result.away_score.isnot(None))
        .all()
    )
    X, y_home, y_away, fixtures = [], [], [], []
    for fixture, result in rows:
        vec = build_feature_vector(session, fixture)
        X.append(vec)
        y_home.append(result.home_score)
        y_away.append(result.away_score)
        fixtures.append(fixture)
    return np.array(X), np.array(y_home), np.array(y_away), fixtures


def _fit_regressor(X_tr, y_tr, X_val, y_val) -> xgb.XGBRegressor:
    model = xgb.XGBRegressor(
        objective="count:poisson",
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        early_stopping_rounds=20,
        missing=np.nan,
        verbosity=0,
    )
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
    return model


def train(
    session: Session,
    output_dir: Path = ARTIFACT_DIR,
    min_samples: int = 500,
    check_baseline: bool = True,
) -> Path:
    X, y_home, y_away, fixtures = _build_dataset(session)
    if len(X) < min_samples:
        raise InsufficientDataError(f"{len(X)} samples < required {min_samples}")

    X_tr, X_te, yh_tr, yh_te, ya_tr, ya_te, idx_tr, idx_te = train_test_split(
        X, y_home, y_away, np.arange(len(X)),
        test_size=0.2, random_state=42,
    )

    home_model = _fit_regressor(X_tr, yh_tr, X_te, yh_te)
    away_model = _fit_regressor(X_tr, ya_tr, X_te, ya_te)

    mae_home = float(mean_absolute_error(yh_te, home_model.predict(X_te)))
    mae_away = float(mean_absolute_error(ya_te, away_model.predict(X_te)))

    if check_baseline:
        baseline_home = np.array([_heuristic_lambda(session, fixtures[i])[0] for i in idx_te])
        baseline_away = np.array([_heuristic_lambda(session, fixtures[i])[1] for i in idx_te])
        base_mae_home = float(mean_absolute_error(yh_te, baseline_home))
        base_mae_away = float(mean_absolute_error(ya_te, baseline_away))
        # Require ML to beat heuristic on at least one side — both is ideal
        if mae_home >= base_mae_home and mae_away >= base_mae_away:
            raise BaselineRegressionError(
                f"ML underperforms baseline on both sides. "
                f"ML: ({mae_home:.3f}, {mae_away:.3f}), "
                f"Baseline: ({base_mae_home:.3f}, {base_mae_away:.3f})"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_path = output_dir / f"ml_lambda_{version}.pkl"
    joblib.dump({
        "home_model": home_model,
        "away_model": away_model,
        "feature_names": FEATURE_NAMES,
        "metrics": {"mae_home": mae_home, "mae_away": mae_away, "n_samples": len(X)},
        "trained_at": version,
    }, artifact_path)

    # Deactivate previous artifacts, insert new active row
    session.query(MLArtifact).filter_by(name="ml_lambda").update({"active": False})
    session.add(MLArtifact(
        name="ml_lambda",
        version=version,
        path=str(artifact_path),
        mae_home=mae_home,
        mae_away=mae_away,
        n_samples=len(X),
        active=True,
        trained_at=datetime.now(timezone.utc),
    ))
    session.commit()

    print(f"Trained ml_lambda {version}: n={len(X)}, "
          f"MAE home={mae_home:.3f} away={mae_away:.3f}")
    print(f"Artifact: {artifact_path}")
    return artifact_path


if __name__ == "__main__":
    with Session(get_engine()) as session:
        train(session)
