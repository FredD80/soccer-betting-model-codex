# Phase 2 — XGBoost/LightGBM Learned Signal Weights Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed heuristic λ formula (`goals_scored × goals_conceded / league_avg`) in `SpreadPredictor` / `OUAnalyzer` with a learned XGBoost regressor that outputs `(λ_home, λ_away)` from a richer feature vector spanning all six signal layers (form, xG, tactical, referee, manager, environmental). The learned λ values feed directly into the existing Dixon-Coles `build_score_matrix` — the DC layer stays unchanged.

**Architecture:** `app/features.py` — pure feature-vector assembly from fixture + DB state, no DB writes. `app/ml_lambda.py` — thin wrapper around a trained `xgboost.XGBRegressor` pair; loads `.pkl` artifacts lazily from `models/artifacts/`. `scripts/train_ml_lambda.py` — offline trainer reading `results` table, producing versioned artifacts. `SpreadPredictor` / `OUAnalyzer` gain an `ml_enabled` flag; when true, they call `ml_lambda.predict()` instead of the heuristic formula. DC math and Monte Carlo task are **not modified**.

**Tech Stack:** Python 3.12, xgboost==2.1.1, scikit-learn==1.5.2 (for train/test split + metrics), numpy, SQLAlchemy 2.x, joblib==1.4.2 (artifact serialization).

**Prerequisites:**
- Phase 2 Dixon-Coles plan complete (DC math + league_calibration + monte_carlo tables exist).
- FormCache populated with xg_scored_avg / xg_conceded_avg.
- `results` table has at least ~500 completed fixtures across tracked leagues (for statistically meaningful training).

**Must complete before:** Market blending plan (ML-learned λ is an input to the blended final probability).

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `app/features.py` | Build per-fixture feature vector from DB state as-of kickoff |
| Create | `app/ml_lambda.py` | `MLLambdaPredictor` — loads trained artifacts, returns (λ_home, λ_away) |
| Create | `scripts/train_ml_lambda.py` | Offline trainer: read results → features → fit XGBoost → save artifact |
| Create | `models/artifacts/.gitkeep` | Directory for `.pkl` model files (gitignored except .gitkeep) |
| Modify | `app/spread_predictor.py` | Add `ml_enabled` init flag, use `MLLambdaPredictor` when true |
| Modify | `app/ou_analyzer.py` | Add `ml_enabled` init flag, use `MLLambdaPredictor` when true |
| Modify | `app/db/models.py` | Add `MLArtifact` ORM model (tracks versioned artifact paths) |
| Create | `migrations/versions/<hash>_ml_artifact.py` | `ml_artifacts` table |
| Modify | `requirements.txt` | Add xgboost, scikit-learn, joblib |
| Modify | `.gitignore` | Exclude `models/artifacts/*.pkl` |
| Create | `tests/test_features.py` | Unit tests: deterministic feature vector, handles missing joins |
| Create | `tests/test_ml_lambda.py` | Unit tests: load artifact → predict shape + bounds |
| Create | `tests/test_train_ml_lambda.py` | Integration: train on synthetic fixtures, verify fit |

---

## Task 1: Feature Engineering Module

**Files:**
- Create: `app/features.py`
- Create: `tests/test_features.py`

**Goal:** A single `build_feature_vector(session, fixture)` function that returns a `numpy.ndarray` of length `N_FEATURES` and a parallel `FEATURE_NAMES: list[str]`. Must be deterministic given DB state, tolerate missing joins (returns NaN, which XGBoost handles natively), and be used identically by training and serving.

### Step 1: Write feature tests first

`tests/test_features.py` must cover:
- `test_feature_vector_shape`: returns ndarray of expected length
- `test_feature_vector_handles_missing_form_cache`: fills NaN, does not crash
- `test_feature_names_match_vector_length`: `len(FEATURE_NAMES) == N_FEATURES`
- `test_feature_order_is_stable`: vector[i] corresponds to FEATURE_NAMES[i]
- `test_home_xg_diff_computed`: `xg_scored_home - xg_conceded_away` appears as a feature

### Step 2: Implement `app/features.py`

Feature groups (approximate count in parens):

1. **Form layer (8):** `home_goals_scored_avg`, `home_goals_conceded_avg`, `away_goals_scored_avg`, `away_goals_conceded_avg`, `home_ou_25_rate`, `away_ou_25_rate`, `home_spread_cover_rate`, `away_spread_cover_rate`
2. **xG layer (4):** `home_xg_scored_avg`, `home_xg_conceded_avg`, `away_xg_scored_avg`, `away_xg_conceded_avg`
3. **Tactical (6):** `home_ppda`, `away_ppda`, `home_press_resistance`, `away_press_resistance`, `home_set_piece_pct`, `home_aerial_win_rate`
4. **Manager (2):** `home_mgr_draw_tendency`, `away_mgr_draw_tendency`
5. **Referee (3):** `ref_cards_per_game`, `ref_penalty_rate`, `ref_fouls_per_tackle`
6. **Player impact (2):** `home_absent_xg_pct` (sum of `xg_contribution_pct` where `is_absent=True`), `away_absent_xg_pct`
7. **Environmental (2):** `wind_modifier` (from `WindModifier.calculate()` — requires stadium + weather), `rest_days_delta` (home − away)
8. **Market signal (2):** `pinnacle_implied_home`, `pinnacle_implied_away` (from latest OddsSnapshot if bookmaker is Pinnacle)
9. **Draw propensity (1):** `draw_propensity_score` (from DrawPropensity.score)
10. **League context (1):** `league_avg_goals` (running average from Results for this league)

Target: ~31 features. Missing values → `np.nan`; XGBoost's `missing` parameter handles these without imputation.

### Step 3: Run tests, iterate

```bash
DATABASE_URL=sqlite:///:memory: .venv/bin/python -m pytest tests/test_features.py -v
```

- [ ] Task 1 complete when: feature vector is deterministic, length matches names, tests pass.

---

## Task 2: ML Lambda Predictor (Serving)

**Files:**
- Create: `app/ml_lambda.py`
- Create: `tests/test_ml_lambda.py`

**Goal:** `MLLambdaPredictor` class that loads a joblib-pickled `(home_model, away_model)` tuple once (cached on instance) and exposes `predict(session, fixture) -> tuple[float, float]`.

### Step 1: Write serving tests

`tests/test_ml_lambda.py`:
- `test_load_artifact_from_path`: accepts explicit artifact path
- `test_load_artifact_from_registry`: reads latest active `MLArtifact` row
- `test_predict_returns_two_floats`: shape check
- `test_predict_clamps_to_minimum`: λ >= 0.1 (same floor as heuristic formula)
- `test_missing_artifact_raises`: clear error if no artifact available

### Step 2: Implement

```python
class MLLambdaPredictor:
    def __init__(self, session, artifact_path: str | None = None):
        self.session = session
        self._home_model, self._away_model, self._feature_names = self._load(artifact_path)

    def predict(self, fixture) -> tuple[float, float]:
        vec = build_feature_vector(self.session, fixture)
        λh = max(0.1, float(self._home_model.predict(vec.reshape(1, -1))[0]))
        λa = max(0.1, float(self._away_model.predict(vec.reshape(1, -1))[0]))
        return λh, λa

    def _load(self, path): ...  # joblib.load + FEATURE_NAMES validation
```

**Version check:** artifact stores its `FEATURE_NAMES` list; `_load` asserts it matches `app.features.FEATURE_NAMES` or raises `FeatureDriftError`. This catches the silent-breakage case where features were added/removed after training.

- [ ] Task 2 complete when: serving tests pass and FeatureDriftError fires when feature list changes.

---

## Task 3: Training Script

**Files:**
- Create: `scripts/train_ml_lambda.py`
- Create: `tests/test_train_ml_lambda.py`

**Goal:** Offline trainer. Reads all completed fixtures + results, builds features as-of kickoff, trains two XGBoost regressors (target: actual home_goals and away_goals), saves artifact + registers in `ml_artifacts` table.

### Step 1: Training tests (smaller synthetic dataset)

```python
def test_training_produces_artifact(db, tmp_path):
    # seed 100 synthetic fixtures with FormCache + Result rows
    ...
    artifact_path = train(db, output_dir=tmp_path, min_samples=50)
    assert artifact_path.exists()

    predictor = MLLambdaPredictor(db, artifact_path=artifact_path)
    λh, λa = predictor.predict(db.query(Fixture).first())
    assert 0.1 <= λh <= 5.0
    assert 0.1 <= λa <= 5.0
```

### Step 2: Implement `scripts/train_ml_lambda.py`

```python
def train(session, output_dir: Path, min_samples: int = 500) -> Path:
    X, y_home, y_away = [], [], []
    completed = session.query(Fixture).join(Result).filter(Fixture.status == "completed").all()
    for fixture in completed:
        vec = build_feature_vector(session, fixture)
        result = session.query(Result).filter_by(fixture_id=fixture.id).one()
        X.append(vec); y_home.append(result.home_score); y_away.append(result.away_score)

    if len(X) < min_samples:
        raise InsufficientDataError(f"{len(X)} < {min_samples}")

    X = np.array(X); y_home = np.array(y_home); y_away = np.array(y_away)
    X_tr, X_te, yh_tr, yh_te = train_test_split(X, y_home, test_size=0.2, random_state=42)
    _, _, ya_tr, ya_te = train_test_split(X, y_away, test_size=0.2, random_state=42)

    home_model = xgb.XGBRegressor(
        objective="count:poisson",  # Poisson regression for count target
        n_estimators=300, max_depth=4, learning_rate=0.05,
        early_stopping_rounds=20, missing=np.nan,
    )
    home_model.fit(X_tr, yh_tr, eval_set=[(X_te, yh_te)], verbose=False)
    away_model = xgb.XGBRegressor(objective="count:poisson", ...)
    away_model.fit(X_tr, ya_tr, ...)

    mae_home = mean_absolute_error(yh_te, home_model.predict(X_te))
    mae_away = mean_absolute_error(ya_te, away_model.predict(X_te))

    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_path = output_dir / f"ml_lambda_{version}.pkl"
    joblib.dump({
        "home_model": home_model, "away_model": away_model,
        "feature_names": FEATURE_NAMES,
        "metrics": {"mae_home": mae_home, "mae_away": mae_away, "n_samples": len(X)},
        "trained_at": version,
    }, artifact_path)

    session.add(MLArtifact(
        name="ml_lambda", version=version, path=str(artifact_path),
        mae_home=mae_home, mae_away=mae_away, n_samples=len(X), active=True,
    ))
    # Deactivate previous
    session.query(MLArtifact).filter(MLArtifact.name == "ml_lambda", MLArtifact.version != version).update({"active": False})
    session.commit()
    return artifact_path
```

**Objective choice:** `count:poisson` is appropriate because scores are non-negative counts and the downstream DC model also assumes Poisson-like λ inputs. Do **not** use `reg:squarederror` here — it would not preserve the count structure.

**Baseline comparison:** after training, log MAE of the heuristic formula on the same test set and assert the ML model beats it by ≥5% (else raise; forces investigation).

- [ ] Task 3 complete when: synthetic training test passes, MAE < baseline formula MAE on the test fold.

---

## Task 4: ML Artifact Registry (DB)

**Files:**
- Modify: `app/db/models.py`
- Create: `migrations/versions/<hash>_ml_artifact.py`

### Step 1: Add ORM model

```python
class MLArtifact(Base):
    __tablename__ = "ml_artifacts"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)           # "ml_lambda"
    version = Column(String, nullable=False)        # "20260413_223145"
    path = Column(String, nullable=False)           # filesystem path
    mae_home = Column(Float)
    mae_away = Column(Float)
    n_samples = Column(Integer)
    active = Column(Boolean, default=False)
    trained_at = Column(DateTime, default=datetime.utcnow)
```

### Step 2: Generate + apply migration

```bash
PYTHONPATH=. DATABASE_URL=sqlite:///test_migration.db .venv/bin/alembic revision --autogenerate -m "ml_artifact"
PYTHONPATH=. DATABASE_URL=sqlite:///test_migration.db .venv/bin/alembic upgrade head
```

- [ ] Task 4 complete when: migration applies cleanly, `MLArtifact` appears in `tests/test_db_models.py` coverage.

---

## Task 5: Wire ML into Predictors

**Files:**
- Modify: `app/spread_predictor.py`
- Modify: `app/ou_analyzer.py`

**Goal:** Add `ml_enabled: bool = False` init flag. When true, replace the heuristic λ formula with `MLLambdaPredictor(session).predict(fixture)`. Everything downstream (DC matrix, Monte Carlo, EV computation) unchanged.

```python
class SpreadPredictor:
    def __init__(self, session, lead_hours=None, ml_enabled: bool = False):
        self.session = session
        self._lead_hours = lead_hours
        self._ml = MLLambdaPredictor(session) if ml_enabled else None

    def run(self, model_id):
        ...
        for fixture in upcoming:
            if self._ml:
                lambda_home, lambda_away = self._ml.predict(fixture)
                # home_advantage NOT applied here — the ML model has already
                # learned it from (is_home, league_id) features
            else:
                # existing heuristic × home_advantage path
                ...
```

**Key subtlety:** when `ml_enabled=True`, **do not** multiply by `params.home_advantage` — the model has learned the home effect from training data. When `ml_enabled=False`, keep the existing DC + per-league calibration path. This preserves backward-compatible behavior when artifacts are unavailable.

### Tests (add to existing files)

- `test_spread_predictor_uses_ml_when_enabled`: mock `MLLambdaPredictor.predict` returns (1.5, 1.2), assert predictions use those λ values
- `test_spread_predictor_falls_back_when_ml_disabled`: default path unchanged

- [ ] Task 5 complete when: `pytest tests/test_spread_predictor.py tests/test_ou_analyzer.py` passes and ML path produces different predictions from heuristic path on same fixture.

---

## Task 6: Full Regression + Artifact Commit

**Files:**
- Modify: `.gitignore`
- Create: `models/artifacts/.gitkeep`

### Steps

1. `.gitignore`: add `models/artifacts/*.pkl` and `!models/artifacts/.gitkeep`
2. Create `models/artifacts/.gitkeep` (empty)
3. Run full test suite: `DATABASE_URL=sqlite:///:memory: ODDS_API_KEY=test .venv/bin/python -m pytest tests/ -v` — target: 100% pass
4. Commit with message: `feat: XGBoost/LightGBM learned λ regressors with feature pipeline`
5. Push to origin/main

**Do not commit actual `.pkl` artifacts.** They are produced by the training script and should be regenerated on deploy. The `MLArtifact` DB row tracks which version is active on each environment.

- [ ] Task 6 complete when: full test suite passes, .pkl files are gitignored, commit pushed.

---

## Non-Goals

- **No online learning.** Models are retrained offline via `train_ml_lambda.py` on a cadence (weekly/monthly cron), not continuously.
- **No hyperparameter tuning in this plan.** Use the fixed values above. Tuning is a separate concern once we have >6 months of fixtures.
- **No probability calibration yet.** Poisson-regressed λ values already give well-behaved DC probabilities; calibration curves come in the Market Blending plan.
- **No drift monitoring dashboard.** Out of scope — covered by the planned "model decay detection" work in Phase 3.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Insufficient training data early on | `InsufficientDataError` raised at train time; predictors fall back to heuristic path via `ml_enabled=False` in scheduler |
| Feature leakage (e.g., using post-match stats) | `build_feature_vector` only reads tables updated pre-kickoff. Tests assert no post-match dependency |
| FormCache state drift between train and serve | FeatureDriftError in `MLLambdaPredictor._load` — artifact pins feature names |
| XGBoost version mismatch between train and serve | Pin `xgboost==2.1.1` in requirements.txt; joblib captures sklearn version in pickle metadata |
| Overfitting on small sample | `early_stopping_rounds=20` on held-out fold + force MAE < baseline |

---

## Validation Checklist

- [ ] `app/features.py` has ~31 features across 10 groups
- [ ] FEATURE_NAMES list is length-matched to vector
- [ ] `MLLambdaPredictor` loads artifact and predicts in < 10 ms
- [ ] `train_ml_lambda.py` runs on synthetic data in test
- [ ] MAE(ML) < MAE(heuristic baseline) on held-out fold
- [ ] Both predictors have `ml_enabled` flag, default False
- [ ] Migration for `ml_artifacts` applies cleanly
- [ ] `.pkl` files gitignored; `.gitkeep` committed
- [ ] Full test suite green
