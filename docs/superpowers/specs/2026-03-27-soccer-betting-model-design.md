# Soccer Betting Model — Architecture Design

**Date:** 2026-03-27
**Leagues:** EPL (England), La Liga (Spain), Bundesliga (Germany), Serie A (Italy)
**Deployment:** Multiverse K8s Cluster — Tenant B (`tenant-b` namespace)

---

## 1. Goals

- Predict match outcomes (home / draw / away) against live sports betting lines
- Predict total goals (over/under lines) for full match and first half
- Predict half-time outcomes independently from full-match outcomes
- Track multiple prediction model versions simultaneously
- Backtest new model versions against historical data before activating
- Evaluate models by two metrics: prediction accuracy and ROI
- Run automatically on a schedule with manual CLI override available

---

## 2. Data Sources

| Source | Purpose | Method |
|---|---|---|
| The Odds API | Betting lines (open/close, multiple books) | REST API (paid, key required) |
| ESPN unofficial API | Fixtures, team data, final scores/results | REST API (no key required) |

Odds are snapshotted at collection time with a timestamp — odds move, so history is preserved in full.

---

## 3. System Components

### 3.1 Data Collector
- Polls The Odds API for upcoming fixture lines across all four leagues
- Polls ESPN API for upcoming fixtures and completed match results
- Writes raw data to PostgreSQL with timestamps
- Runs on schedule and via CLI trigger

### 3.2 Model Registry
- PostgreSQL table tracking all model versions
- Fields: `id`, `name`, `version`, `description`, `active` (bool), `created_at`
- Each model is a Python class implementing a standard interface (see Section 6)
- New versions can be registered via CLI and set to inactive until backtesting passes

### 3.3 Prediction Engine
- On each scheduled run, fetches upcoming fixtures + latest odds
- Runs every active model, stores each prediction tagged with `model_id` + `fixture_id`
- Predictions include: predicted outcome, confidence score, odds at time of prediction

### 3.4 Results Tracker
- After a match completes, fetches final score via ESPN API
- Marks each prediction correct/incorrect
- Computes updated accuracy + ROI for each model version
- Writes to `performance` table

### 3.5 Backtester
- Accepts a model version and date range
- Runs predictions against historical fixtures + odds snapshots
- Results written to a separate `backtest_runs` table — isolated from live tracking
- Triggered via CLI only (never by scheduler)

### 3.6 Scheduler (APScheduler, embedded)
- Runs inside the main application process
- Default schedule: data collection every 6 hours, predictions 2 hours before kickoff
- Schedule configurable via ConfigMap
- Logs all run history and errors to PostgreSQL

### 3.7 CLI
Manual trigger for any pipeline step:
```
python cli.py collect          # Run data collection now
python cli.py predict          # Run prediction engine now
python cli.py backtest --model <name> --version <v> --from <date> --to <date>
python cli.py performance      # Print accuracy + ROI report per model
python cli.py register-model   # Add a new model version to the registry
```

---

## 4. Storage Schema

```sql
leagues         (id, name, country, espn_id)
teams           (id, name, league_id, espn_id)
fixtures        (id, home_team_id, away_team_id, league_id, kickoff_at, status)
odds_snapshots  (id, fixture_id, bookmaker,
                 home_odds, draw_odds, away_odds,           -- match result
                 ht_home_odds, ht_draw_odds, ht_away_odds,  -- half-time result
                 total_goals_line, over_odds, under_odds,   -- full match over/under
                 ht_goals_line, ht_over_odds, ht_under_odds, -- half-time over/under
                 captured_at)
models          (id, name, version, description, active, created_at)
predictions     (id, model_id, fixture_id, bet_type,        -- bet_type: "match_result" | "ht_result" | "total_goals" | "ht_goals"
                 predicted_outcome, confidence, odds_snapshot_id, created_at)
results         (id, fixture_id,
                 home_score, away_score, outcome,           -- full match
                 ht_home_score, ht_away_score, ht_outcome,  -- half-time
                 total_goals, ht_total_goals,               -- goal totals
                 verified_at)
performance     (id, model_id, bet_type, total_predictions, correct, accuracy, roi, updated_at)
backtest_runs   (id, model_id, bet_type, date_from, date_to, total, correct, accuracy, roi, run_at)
scheduler_log   (id, job_name, status, error, started_at, completed_at)
```

---

## 5. Model Interface

All prediction models implement this base class. Fred writes the logic; the framework handles the rest.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Prediction:
    bet_type: str         # "match_result" | "ht_result" | "total_goals" | "ht_goals"
    outcome: str          # match_result/ht_result: "home"|"draw"|"away"
                          # total_goals/ht_goals: "over"|"under"
    confidence: float     # 0.0 – 1.0
    line: float | None    # goals line for over/under bets, None for result bets

class BaseModel(ABC):
    name: str
    version: str

    @abstractmethod
    def predict(self, fixture: dict, odds: dict, history: list[dict]) -> list[Prediction]:
        """
        fixture  — upcoming match data (teams, league, kickoff)
        odds     — latest odds snapshot for this fixture (includes all bet types)
        history  — recent results for both teams (configurable lookback)
        Returns a list — model can predict one or all bet types per fixture
        """
        ...
```

Register a new model:
```python
# models/my_model_v1.py
class MyModelV1(BaseModel):
    name = "my_model"
    version = "1.0"

    def predict(self, fixture, odds, history) -> list[Prediction]:
        # your logic here — return predictions for whichever bet types you want to cover
        return [
            Prediction(bet_type="match_result", outcome="home", confidence=0.65, line=None),
            Prediction(bet_type="total_goals", outcome="over", confidence=0.58, line=2.5),
            Prediction(bet_type="ht_goals", outcome="under", confidence=0.61, line=1.5),
        ]
```

---

## 6. Kubernetes Deployment

**Namespace:** `tenant-b`

```
k8s/
├── deployment.yaml       # App — 1 replica, APScheduler embedded
├── postgres/
│   ├── statefulset.yaml  # PostgreSQL with Longhorn PVC
│   └── service.yaml      # ClusterIP service
├── configmap.yaml        # Schedule intervals, league config
├── secret.yaml           # API keys, DB credentials (git-ignored, applied via Jenkins)
└── ingress.yaml          # NGINX Ingress — placeholder for future UI
```

**Storage:** Longhorn StorageClass for PostgreSQL PVC
**Ingress:** NGINX Ingress class, MetalLB (192.168.1.240)
**Observability:** App exposes `/metrics` (Prometheus-compatible) on port 9090

---

## 7. CI/CD (Jenkins)

Jenkinsfile stages:
1. `Checkout` — pull from Git
2. `Test` — run unit tests
3. `Build` — build Docker image, tag with Git SHA
4. `Push` — push to container registry
5. `Deploy` — `kubectl apply -k k8s/` targeting `tenant-b`

Secrets applied to cluster separately — never committed to Git.

---

## 8. Repository Structure

```
soccer-betting-model/
├── app/
│   ├── collector.py       # Data Collector
│   ├── predictor.py       # Prediction Engine
│   ├── tracker.py         # Results Tracker
│   ├── backtester.py      # Backtester
│   ├── scheduler.py       # APScheduler setup
│   ├── models/            # Model implementations (user-written)
│   │   └── base.py        # BaseModel interface
│   ├── db/
│   │   ├── schema.py      # SQLAlchemy models
│   │   └── migrations/    # Alembic migrations
│   └── metrics.py         # Prometheus /metrics endpoint
├── cli.py                 # CLI entry point
├── Dockerfile
├── requirements.txt
├── k8s/                   # Kubernetes manifests
├── Jenkinsfile
├── .gitignore             # Includes secret.yaml, .env
└── docs/
    └── superpowers/specs/ # This file
```

---

## 9. Out of Scope (This Phase)

- UI / dashboard (future phase)
- Automated bet placement (manual review only)
- Prediction logic (written by Fred, framework is neutral)
- Additional leagues beyond the four listed
