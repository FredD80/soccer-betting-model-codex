"""
Serving wrapper for trained XGBoost (λ_home, λ_away) regressors.

Loads a joblib artifact produced by scripts/train_ml_lambda.py and exposes
predict(fixture) -> (lambda_home, lambda_away). Artifact format:

    {
        "home_model": xgb.XGBRegressor,
        "away_model": xgb.XGBRegressor,
        "feature_names": list[str],
        "metrics": dict,
        "trained_at": str,
    }

FeatureDriftError is raised at load time if the artifact's feature_names
list diverges from app.features.FEATURE_NAMES — this catches the silent
breakage of training a model, adding a feature, and redeploying without
retraining.
"""
from pathlib import Path
import joblib

from app.features import FEATURE_NAMES, build_feature_vector


class FeatureDriftError(RuntimeError):
    """Raised when a loaded artifact's feature schema doesn't match the code."""


class MLLambdaPredictor:
    def __init__(self, session, artifact_path: str | Path | None = None):
        self.session = session
        path = self._resolve_path(artifact_path)
        self._home_model, self._away_model = self._load(path)

    def predict(self, fixture) -> tuple[float, float]:
        vec = build_feature_vector(self.session, fixture).reshape(1, -1)
        lambda_home = max(0.1, float(self._home_model.predict(vec)[0]))
        lambda_away = max(0.1, float(self._away_model.predict(vec)[0]))
        return lambda_home, lambda_away

    def _resolve_path(self, explicit: str | Path | None) -> Path:
        if explicit is not None:
            return Path(explicit)
        from app.db.models import MLArtifact
        row = (
            self.session.query(MLArtifact)
            .filter_by(name="ml_lambda", active=True)
            .order_by(MLArtifact.trained_at.desc())
            .first()
        )
        if row is None:
            raise FileNotFoundError(
                "No active ml_lambda artifact found. "
                "Run scripts/train_ml_lambda.py or pass artifact_path explicitly."
            )
        return Path(row.path)

    def _load(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"ML artifact not found at {path}")
        bundle = joblib.load(path)
        if bundle["feature_names"] != FEATURE_NAMES:
            raise FeatureDriftError(
                "Artifact feature_names mismatch with current FEATURE_NAMES. "
                f"Artifact has {len(bundle['feature_names'])} features; "
                f"code has {len(FEATURE_NAMES)}. Retrain required."
            )
        return bundle["home_model"], bundle["away_model"]
