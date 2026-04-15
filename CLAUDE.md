# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running locally (Docker Compose)
```bash
docker-compose up -d postgres redis   # start dependencies
python cli.py migrate                 # create DB tables (dev only; prod uses Alembic)
python cli.py seed                    # seed 6 supported leagues
python cli.py collect                 # fetch fixtures + odds
python cli.py build_form_cache        # required before predictions
python cli.py predict_spreads         # Poisson spread predictions
python cli.py predict_ou              # Poisson O/U predictions
python cli.py predict                 # general ML prediction engine
python cli.py scheduler               # blocking scheduler (container entrypoint)
```

### Database migrations (Alembic)
```bash
# Run inside a pod or with DATABASE_URL set:
PYTHONPATH=/app alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Running tests
```bash
pytest tests/ -v --tb=short               # all tests (uses SQLite in-memory)
pytest tests/test_predictor.py -v         # single file
pytest tests/ -k "test_spread"            # by name pattern
```

Tests use SQLite in-memory via `conftest.py`; no Postgres needed. The `db` fixture wraps each test in a rolled-back transaction.

### Docker images
```bash
docker build -t sbm-engine .                             # scheduler + worker
docker build -f Dockerfile.api -t sbm-api .              # FastAPI
docker build -f Dockerfile.dashboard -t sbm-dashboard .  # React dashboard
```

### Kubernetes (tenant-d namespace)
```bash
kubectl -n tenant-d rollout restart deployment/<name>
kubectl -n tenant-d exec -it <pod> -- python cli.py <command>
kubectl -n tenant-d logs -l app=sbm-engine --tail=100
```

## Architecture

### Service decomposition
Four Docker images, all deployed to the `tenant-d` Kubernetes namespace:

| Image | Entrypoint | Role |
|---|---|---|
| `sbm-engine` | `python cli.py scheduler` | APScheduler runs collect → build_form_cache → predict cycle |
| `sbm-engine` | `celery -A app.celery_app worker` | Async task worker (same image, different CMD) |
| `sbm-api` | uvicorn | FastAPI read-only REST API for the dashboard |
| `sbm-dashboard` | nginx | React SPA served at sbm.chelseablue.cloud |

Postgres and Redis run as StatefulSets in the same namespace.

### Core pipeline flow
```
DataCollector → FormCacheBuilder → SpreadPredictor / OUAnalyzer / PredictionEngine
                                         ↓
                                  Predictions table
                                         ↓
                               FastAPI /picks endpoint (filters by confidence tier)
```

1. **DataCollector** (`app/collector/collector.py`) orchestrates sub-clients: `OddsAPIClient` (the-odds-api v4), `ESPNClient`, `FBRefClient`, `WeatherClient`. Supported markets: `h2h`, `spreads`, `totals` — half-time variants (`h2h_h1`, `totals_h1`) are **not** supported by the API and must not be requested.
2. **FormCacheBuilder** (`app/form_cache.py`) must run before any predictor. It requires completed result rows per team; returns `False` (skips team) if no history exists.
3. **SpreadPredictor** (`app/spread_predictor.py`) / **OUAnalyzer** (`app/ou_analyzer.py`) use Poisson modeling. Both skip fixtures outside the `PREDICTION_LEAD_HOURS` window and require an active `ModelVersion` row.
4. **PredictionEngine** (`app/predictor.py`) runs registered ML model classes from `MODEL_CLASSES` in `cli.py`.
5. **Picks API** (`api/routers/picks.py`) filters predictions by `HIGH` or `ELITE` confidence tier — predictions assigned `SKIP` never surface.

### Confidence tiers
Defined in `app/edge_tiers.py`. Tiers: `SKIP`, `LOW`, `MEDIUM`, `HIGH`, `ELITE`. The API only returns `HIGH`/`ELITE`. Tier assignment is the key lever for controlling output volume.

### Data models (`app/db/models.py`)
Key tables: `League`, `Team`, `Fixture`, `OddsSnapshot`, `FormCache`, `ModelVersion`, `Prediction`, `Performance`, `LeagueCalibration`, `MLArtifact`.

Migrations live in `migrations/versions/`. The phase2 migration guards TimescaleDB-specific DDL with a `pg_extension` check.

### Configuration
Runtime config comes from environment variables (pydantic-settings, `.env` file locally). In Kubernetes, non-secret values come from the `sbm-config` ConfigMap (`k8s/configmap.yaml`); secrets (`DATABASE_URL`, `ODDS_API_KEY`) come from the `sbm-secrets` Secret.

Key settings:
- `PREDICTION_LEAD_HOURS` — how far ahead to predict
- `COLLECTION_INTERVAL_HOURS` — scheduler cadence (default `12`)

### Scripts (`scripts/`)
One-off operational scripts:
- `backfill_results.py` — ESPN-based historical results backfill (1,633 results written for EPL)
- `compute_calibration.py`, `seed_league_calibration.py`, `train_ml_lambda.py`, `fit_market_weights.py`

### CI/CD
Jenkins pipeline (Jenkinsfile): test → build 4 images → push to GHCR (`ghcr.io/fredd80/`) → `kubectl set image` for each deployment. Image tag is the short git commit SHA. The engine and worker share the same `sbm-engine` image.

### Supported leagues
EPL, La Liga, Bundesliga, Serie A, Ligue 1, Champions League. ESPN IDs and odds-api keys are hardcoded in `cli.py seed`.
