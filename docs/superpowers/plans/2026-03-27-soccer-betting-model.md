# Soccer Betting Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python application that collects soccer fixture data and betting odds for EPL, La Liga, Bundesliga, and Serie A, runs pluggable versioned prediction models across four bet types (match result, half-time result, total goals, half-time goals), tracks live accuracy and ROI per model version, supports backtesting, and deploys as a single-replica Kubernetes Deployment in Tenant B of the Multiverse cluster.

**Architecture:** APScheduler embedded in a Python process drives automated data collection and prediction runs. PostgreSQL (Longhorn PVC) stores all fixtures, odds snapshots, predictions, and results. Models are Python classes implementing a standard interface; the framework is neutral about prediction logic.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Alembic, APScheduler 3.x, Click (CLI), Requests, Prometheus-client, psycopg2-binary, pytest, responses (HTTP mocking), Kubernetes + Longhorn + NGINX Ingress + Jenkins

---

## File Map

```
soccer-betting-model/
├── app/
│   ├── __init__.py
│   ├── config.py                        # Pydantic-settings config from env vars
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py                # SQLAlchemy engine + session factory
│   │   └── models.py                    # All ORM table definitions
│   ├── collector/
│   │   ├── __init__.py
│   │   ├── odds_api.py                  # The Odds API HTTP client
│   │   ├── espn_api.py                  # ESPN unofficial API HTTP client
│   │   └── collector.py                 # Orchestrates both clients, writes to DB
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                      # BaseModel ABC + Prediction dataclass
│   │   └── registry.py                  # Model registry CRUD
│   ├── predictor.py                     # Prediction Engine
│   ├── tracker.py                       # Results Tracker
│   ├── backtester.py                    # Backtester
│   ├── scheduler.py                     # APScheduler job definitions
│   └── metrics.py                       # Prometheus /metrics HTTP endpoint
├── cli.py                               # Click CLI entry point
├── tests/
│   ├── conftest.py                      # pytest fixtures: test DB session, sample rows
│   ├── test_collector/
│   │   ├── test_odds_api.py
│   │   └── test_espn_api.py
│   ├── test_models/
│   │   ├── test_base.py
│   │   └── test_registry.py
│   ├── test_predictor.py
│   ├── test_tracker.py
│   └── test_backtester.py
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── k8s/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   ├── postgres/
│   │   ├── statefulset.yaml
│   │   └── service.yaml
│   ├── configmap.yaml
│   ├── secret.yaml.example
│   └── ingress.yaml
├── Dockerfile
├── Jenkinsfile
├── alembic.ini
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Dockerfile`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `alembic.ini`

- [ ] **Step 1: Create requirements.txt**

```text
sqlalchemy==2.0.36
alembic==1.14.0
psycopg2-binary==2.9.10
apscheduler==3.10.4
requests==2.32.3
click==8.1.8
prometheus-client==0.21.1
python-dotenv==1.0.1
pydantic-settings==2.7.0
pytest==8.3.4
pytest-mock==3.14.0
responses==0.25.3
```

- [ ] **Step 2: Create .gitignore**

```gitignore
__pycache__/
*.pyc
.env
k8s/secret.yaml
.pytest_cache/
*.egg-info/
dist/
.venv/
```

- [ ] **Step 3: Create .env.example**

```env
DATABASE_URL=postgresql://betuser:betpass@localhost:5432/soccerbet
ODDS_API_KEY=your_key_here
COLLECTION_INTERVAL_HOURS=6
PREDICTION_LEAD_HOURS=2
```

- [ ] **Step 4: Create app/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    odds_api_key: str
    collection_interval_hours: int = 6
    prediction_lead_hours: int = 2

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 5: Create app/__init__.py**

```python
```

- [ ] **Step 6: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "cli.py", "scheduler"]
```

- [ ] **Step 7: Create alembic.ini**

```ini
[alembic]
script_location = migrations
sqlalchemy.url = %(DATABASE_URL)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 8: Create empty test and migrations directories**

```bash
mkdir -p tests/test_collector tests/test_models migrations/versions
touch tests/__init__.py tests/test_collector/__init__.py tests/test_models/__init__.py
touch app/collector/__init__.py app/models/__init__.py app/db/__init__.py
```

- [ ] **Step 9: Install dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 10: Commit**

```bash
git add .
git commit -m "feat: project scaffolding — requirements, config, Dockerfile"
```

---

## Task 2: Database ORM Models

**Files:**
- Create: `app/db/connection.py`
- Create: `app/db/models.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing test for DB connection**

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base


@pytest.fixture(scope="session")
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
```

```python
# tests/test_db_models.py
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction, Result, Performance, BacktestRun, SchedulerLog


def test_league_table_exists(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    assert league.id is not None


def test_model_version_table_exists(db):
    mv = ModelVersion(name="test_model", version="1.0", description="test", active=False)
    db.add(mv)
    db.flush()
    assert mv.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_db_models.py -v
```
Expected: ImportError — `app.db.models` does not exist yet.

- [ ] **Step 3: Create app/db/connection.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(settings.database_url)
Session = sessionmaker(bind=engine)


def get_session():
    return Session()
```

- [ ] **Step 4: Create app/db/models.py**

```python
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class League(Base):
    __tablename__ = "leagues"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    country = Column(String, nullable=False)
    espn_id = Column(String, nullable=False)
    odds_api_key = Column(String, nullable=False)


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    espn_id = Column(String)


class Fixture(Base):
    __tablename__ = "fixtures"
    id = Column(Integer, primary_key=True)
    espn_id = Column(String, unique=True)
    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    kickoff_at = Column(DateTime, nullable=False)
    status = Column(String, default="scheduled")  # scheduled | live | completed


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    bookmaker = Column(String, nullable=False)
    home_odds = Column(Float)
    draw_odds = Column(Float)
    away_odds = Column(Float)
    ht_home_odds = Column(Float)
    ht_draw_odds = Column(Float)
    ht_away_odds = Column(Float)
    total_goals_line = Column(Float)
    over_odds = Column(Float)
    under_odds = Column(Float)
    ht_goals_line = Column(Float)
    ht_over_odds = Column(Float)
    ht_under_odds = Column(Float)
    captured_at = Column(DateTime, nullable=False)


class ModelVersion(Base):
    __tablename__ = "models"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    description = Column(Text)
    active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    bet_type = Column(String, nullable=False)  # match_result | ht_result | total_goals | ht_goals
    predicted_outcome = Column(String, nullable=False)  # home|draw|away or over|under
    confidence = Column(Float)
    line = Column(Float)  # goals line for over/under bets, None for result bets
    odds_snapshot_id = Column(Integer, ForeignKey("odds_snapshots.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class Result(Base):
    __tablename__ = "results"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), unique=True, nullable=False)
    home_score = Column(Integer)
    away_score = Column(Integer)
    outcome = Column(String)          # home | draw | away
    ht_home_score = Column(Integer)
    ht_away_score = Column(Integer)
    ht_outcome = Column(String)       # home | draw | away
    total_goals = Column(Integer)
    ht_total_goals = Column(Integer)
    verified_at = Column(DateTime)


class Performance(Base):
    __tablename__ = "performance"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    bet_type = Column(String, nullable=False)
    total_predictions = Column(Integer, default=0)
    correct = Column(Integer, default=0)
    accuracy = Column(Float, default=0.0)
    roi = Column(Float, default=0.0)
    updated_at = Column(DateTime)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    bet_type = Column(String)
    date_from = Column(DateTime)
    date_to = Column(DateTime)
    total = Column(Integer)
    correct = Column(Integer)
    accuracy = Column(Float)
    roi = Column(Float)
    run_at = Column(DateTime, default=datetime.utcnow)


class SchedulerLog(Base):
    __tablename__ = "scheduler_log"
    id = Column(Integer, primary_key=True)
    job_name = Column(String, nullable=False)
    status = Column(String, nullable=False)   # success | error
    error = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
```

- [ ] **Step 5: Create tests/test_db_models.py**

```python
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction, Result, Performance, BacktestRun, SchedulerLog
from datetime import datetime


def test_league_table_exists(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    assert league.id is not None


def test_model_version_table_exists(db):
    mv = ModelVersion(name="test_model", version="1.0", description="test", active=False)
    db.add(mv)
    db.flush()
    assert mv.id is not None


def test_odds_snapshot_stores_all_bet_types(db):
    league = League(name="La Liga", country="Spain", espn_id="esp.1", odds_api_key="soccer_spain_la_liga")
    db.add(league)
    db.flush()
    home_team = Team(name="Barcelona", league_id=league.id)
    away_team = Team(name="Real Madrid", league_id=league.id)
    db.add_all([home_team, away_team])
    db.flush()
    fixture = Fixture(home_team_id=home_team.id, away_team_id=away_team.id,
                      league_id=league.id, kickoff_at=datetime(2026, 4, 1, 20, 0))
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(
        fixture_id=fixture.id, bookmaker="betmgm",
        home_odds=2.10, draw_odds=3.50, away_odds=3.20,
        total_goals_line=2.5, over_odds=1.90, under_odds=1.90,
        ht_goals_line=1.5, ht_over_odds=2.00, ht_under_odds=1.80,
        captured_at=datetime.utcnow()
    )
    db.add(snap)
    db.flush()
    assert snap.id is not None
    assert snap.total_goals_line == 2.5
    assert snap.ht_goals_line == 1.5
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_db_models.py -v
```
Expected: All 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add app/db/ tests/conftest.py tests/test_db_models.py
git commit -m "feat: SQLAlchemy ORM models for all tables"
```

---

## Task 3: Alembic Migration

**Files:**
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/001_initial_schema.py`

- [ ] **Step 1: Initialise Alembic**

```bash
alembic init migrations
```

- [ ] **Step 2: Update migrations/env.py to use app models**

Replace the contents of `migrations/env.py`:

```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Generate initial migration**

```bash
alembic revision --autogenerate -m "initial_schema"
```
Expected: Creates `migrations/versions/<hash>_initial_schema.py` with all table definitions.

- [ ] **Step 4: Verify migration file contains all tables**

Open the generated file and confirm these table names appear: `leagues`, `teams`, `fixtures`, `odds_snapshots`, `models`, `predictions`, `results`, `performance`, `backtest_runs`, `scheduler_log`.

- [ ] **Step 5: Commit**

```bash
git add migrations/ alembic.ini
git commit -m "feat: Alembic initial migration for full schema"
```

---

## Task 4: The Odds API Client

**Files:**
- Create: `app/collector/odds_api.py`
- Create: `tests/test_collector/test_odds_api.py`

The Odds API base URL: `https://api.the-odds-api.com/v4`

League sport keys:
- EPL → `soccer_epl`
- La Liga → `soccer_spain_la_liga`
- Bundesliga → `soccer_germany_bundesliga`
- Serie A → `soccer_italy_serie_a`

Markets collected per request: `h2h,totals,h2h_h1,totals_h1`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_collector/test_odds_api.py
import responses as rsps
import pytest
from app.collector.odds_api import OddsAPIClient

SAMPLE_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "soccer_epl",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-04-01T15:00:00Z",
        "bookmakers": [
            {
                "key": "betmgm",
                "title": "BetMGM",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Arsenal", "price": 2.10},
                            {"name": "Draw", "price": 3.50},
                            {"name": "Chelsea", "price": 3.20},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.90, "point": 2.5},
                            {"name": "Under", "price": 1.90, "point": 2.5},
                        ],
                    },
                ],
            }
        ],
    }
]


@rsps.activate
def test_fetch_odds_returns_parsed_fixtures():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    assert len(fixtures) == 1
    assert fixtures[0]["odds_api_id"] == "abc123"
    assert fixtures[0]["home_team"] == "Arsenal"
    assert fixtures[0]["away_team"] == "Chelsea"


@rsps.activate
def test_fetch_odds_extracts_h2h_odds():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["key"] == "betmgm"
    assert bookmaker["h2h"]["home"] == 2.10
    assert bookmaker["h2h"]["draw"] == 3.50
    assert bookmaker["h2h"]["away"] == 3.20


@rsps.activate
def test_fetch_odds_extracts_totals():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["totals"]["line"] == 2.5
    assert bookmaker["totals"]["over"] == 1.90
    assert bookmaker["totals"]["under"] == 1.90


@rsps.activate
def test_fetch_odds_handles_missing_ht_markets():
    """Half-time markets are optional — not all bookmakers provide them."""
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,  # sample has no h2h_h1 or totals_h1
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["ht_h2h"] is None
    assert bookmaker["ht_totals"] is None


@rsps.activate
def test_fetch_all_leagues_calls_each_sport_key():
    for sport_key in ["soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga", "soccer_italy_serie_a"]:
        rsps.add(
            rsps.GET,
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            json=[],
            status=200,
        )
    client = OddsAPIClient(api_key="testkey")
    results = client.fetch_all_leagues()
    assert len(results) == 4
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_collector/test_odds_api.py -v
```
Expected: ImportError — `app.collector.odds_api` does not exist.

- [ ] **Step 3: Create app/collector/odds_api.py**

```python
import requests
from datetime import datetime

BASE_URL = "https://api.the-odds-api.com/v4"

LEAGUE_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
]


class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_odds(self, sport_key: str) -> list[dict]:
        url = f"{BASE_URL}/sports/{sport_key}/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": "us,uk",
            "markets": "h2h,totals,h2h_h1,totals_h1",
            "oddsFormat": "decimal",
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        raw = response.json()
        return [self._parse_fixture(f) for f in raw]

    def fetch_all_leagues(self) -> dict[str, list[dict]]:
        return {key: self.fetch_odds(key) for key in LEAGUE_SPORT_KEYS}

    def _parse_fixture(self, raw: dict) -> dict:
        return {
            "odds_api_id": raw["id"],
            "sport_key": raw["sport_key"],
            "home_team": raw["home_team"],
            "away_team": raw["away_team"],
            "commence_time": raw["commence_time"],
            "bookmakers": [self._parse_bookmaker(b, raw["home_team"], raw["away_team"]) for b in raw.get("bookmakers", [])],
        }

    def _parse_bookmaker(self, bookmaker: dict, home_team: str, away_team: str) -> dict:
        markets = {m["key"]: m for m in bookmaker.get("markets", [])}
        return {
            "key": bookmaker["key"],
            "title": bookmaker["title"],
            "h2h": self._parse_h2h(markets.get("h2h"), home_team, away_team),
            "totals": self._parse_totals(markets.get("totals")),
            "ht_h2h": self._parse_h2h(markets.get("h2h_h1"), home_team, away_team),
            "ht_totals": self._parse_totals(markets.get("totals_h1")),
        }

    def _parse_h2h(self, market: dict | None, home_team: str, away_team: str) -> dict | None:
        if not market:
            return None
        outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
        return {
            "home": outcomes.get(home_team),
            "draw": outcomes.get("Draw"),
            "away": outcomes.get(away_team),
        }

    def _parse_totals(self, market: dict | None) -> dict | None:
        if not market:
            return None
        outcomes = {o["name"]: o for o in market["outcomes"]}
        over = outcomes.get("Over", {})
        return {
            "line": over.get("point"),
            "over": over.get("price"),
            "under": outcomes.get("Under", {}).get("price"),
        }
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_collector/test_odds_api.py -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/collector/odds_api.py tests/test_collector/test_odds_api.py
git commit -m "feat: Odds API client with h2h, totals, and half-time market parsing"
```

---

## Task 5: ESPN API Client

**Files:**
- Create: `app/collector/espn_api.py`
- Create: `tests/test_collector/test_espn_api.py`

ESPN scoreboard URL: `https://site.api.espn.com/apis/site/v2/sports/soccer/{league_id}/scoreboard`

League ESPN IDs: `eng.1`, `esp.1`, `ger.1`, `ita.1`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_collector/test_espn_api.py
import responses as rsps
from app.collector.espn_api import ESPNClient

SAMPLE_SCOREBOARD = {
    "events": [
        {
            "id": "espn_001",
            "date": "2026-04-01T15:00Z",
            "status": {"type": {"name": "STATUS_SCHEDULED", "completed": False}},
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Arsenal"}, "score": "0"},
                        {"homeAway": "away", "team": {"displayName": "Chelsea"}, "score": "0"},
                    ],
                    "situation": None,
                }
            ],
        }
    ]
}

SAMPLE_COMPLETED = {
    "events": [
        {
            "id": "espn_002",
            "date": "2026-03-20T15:00Z",
            "status": {"type": {"name": "STATUS_FINAL", "completed": True}},
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Liverpool"}, "score": "2"},
                        {"homeAway": "away", "team": {"displayName": "Everton"}, "score": "1"},
                    ],
                    "situation": None,
                }
            ],
        }
    ]
}


@rsps.activate
def test_fetch_fixtures_returns_scheduled_matches():
    rsps.add(rsps.GET, "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard",
             json=SAMPLE_SCOREBOARD, status=200)
    client = ESPNClient()
    fixtures = client.fetch_fixtures("eng.1")
    assert len(fixtures) == 1
    assert fixtures[0]["espn_id"] == "espn_001"
    assert fixtures[0]["home_team"] == "Arsenal"
    assert fixtures[0]["away_team"] == "Chelsea"
    assert fixtures[0]["status"] == "scheduled"


@rsps.activate
def test_fetch_fixtures_parses_completed_with_scores():
    rsps.add(rsps.GET, "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard",
             json=SAMPLE_COMPLETED, status=200)
    client = ESPNClient()
    fixtures = client.fetch_fixtures("eng.1")
    assert fixtures[0]["status"] == "completed"
    assert fixtures[0]["home_score"] == 2
    assert fixtures[0]["away_score"] == 1


@rsps.activate
def test_fetch_all_leagues_queries_all_four():
    for league in ["eng.1", "esp.1", "ger.1", "ita.1"]:
        rsps.add(rsps.GET,
                 f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard",
                 json={"events": []}, status=200)
    client = ESPNClient()
    results = client.fetch_all_leagues()
    assert set(results.keys()) == {"eng.1", "esp.1", "ger.1", "ita.1"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_collector/test_espn_api.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create app/collector/espn_api.py**

```python
import requests

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUE_ESPN_IDS = ["eng.1", "esp.1", "ger.1", "ita.1"]


class ESPNClient:
    def fetch_fixtures(self, league_id: str) -> list[dict]:
        url = f"{BASE_URL}/{league_id}/scoreboard"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        events = response.json().get("events", [])
        return [self._parse_event(e) for e in events]

    def fetch_all_leagues(self) -> dict[str, list[dict]]:
        return {lid: self.fetch_fixtures(lid) for lid in LEAGUE_ESPN_IDS}

    def _parse_event(self, event: dict) -> dict:
        competition = event["competitions"][0]
        competitors = {c["homeAway"]: c for c in competition["competitors"]}
        status_name = event["status"]["type"]["name"]
        completed = event["status"]["type"]["completed"]

        home_score = int(competitors["home"]["score"]) if completed else None
        away_score = int(competitors["away"]["score"]) if completed else None

        if completed:
            status = "completed"
        elif "IN_PROGRESS" in status_name or "HALF" in status_name:
            status = "live"
        else:
            status = "scheduled"

        return {
            "espn_id": event["id"],
            "kickoff_at": event["date"],
            "home_team": competitors["home"]["team"]["displayName"],
            "away_team": competitors["away"]["team"]["displayName"],
            "status": status,
            "home_score": home_score,
            "away_score": away_score,
            "ht_home_score": None,  # ESPN scoreboard doesn't include HT scores; tracker fills this
            "ht_away_score": None,
        }
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_collector/test_espn_api.py -v
```
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/collector/espn_api.py tests/test_collector/test_espn_api.py
git commit -m "feat: ESPN API client for fixtures and scores"
```

---

## Task 6: Data Collector Orchestrator

**Files:**
- Create: `app/collector/collector.py`
- Create: `tests/test_collector/test_collector.py`

Responsibilities: upsert teams, upsert fixtures, insert odds snapshots, mark completed fixtures.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_collector/test_collector.py
from unittest.mock import MagicMock, patch
from datetime import datetime
from app.collector.collector import DataCollector
from app.db.models import League, Team, Fixture, OddsSnapshot


def make_league(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    return league


def test_collect_upserts_teams(db):
    league = make_league(db)
    espn_fixtures = [{"espn_id": "e1", "kickoff_at": "2026-04-01T15:00Z",
                      "home_team": "Arsenal", "away_team": "Chelsea",
                      "status": "scheduled", "home_score": None, "away_score": None,
                      "ht_home_score": None, "ht_away_score": None}]
    collector = DataCollector(db)
    collector._upsert_fixture(espn_fixtures[0], league)
    teams = db.query(Team).all()
    assert {t.name for t in teams} == {"Arsenal", "Chelsea"}


def test_collect_upserts_fixture(db):
    league = make_league(db)
    espn_fixture = {"espn_id": "e1", "kickoff_at": "2026-04-01T15:00Z",
                    "home_team": "Arsenal", "away_team": "Chelsea",
                    "status": "scheduled", "home_score": None, "away_score": None,
                    "ht_home_score": None, "ht_away_score": None}
    collector = DataCollector(db)
    fixture = collector._upsert_fixture(espn_fixture, league)
    assert fixture.espn_id == "e1"
    # Run again — should not create a duplicate
    fixture2 = collector._upsert_fixture(espn_fixture, league)
    assert db.query(Fixture).count() == 1


def test_save_odds_snapshot_creates_row(db):
    league = make_league(db)
    home_team = Team(name="Arsenal", league_id=league.id)
    away_team = Team(name="Chelsea", league_id=league.id)
    db.add_all([home_team, away_team])
    db.flush()
    fixture = Fixture(home_team_id=home_team.id, away_team_id=away_team.id,
                      league_id=league.id, kickoff_at=datetime(2026, 4, 1, 15, 0),
                      espn_id="e1", status="scheduled")
    db.add(fixture)
    db.flush()

    bookmaker_data = {
        "key": "betmgm", "title": "BetMGM",
        "h2h": {"home": 2.10, "draw": 3.50, "away": 3.20},
        "totals": {"line": 2.5, "over": 1.90, "under": 1.90},
        "ht_h2h": None, "ht_totals": None,
    }
    collector = DataCollector(db)
    collector._save_odds_snapshot(fixture.id, bookmaker_data)
    snap = db.query(OddsSnapshot).first()
    assert snap.bookmaker == "betmgm"
    assert snap.home_odds == 2.10
    assert snap.total_goals_line == 2.5
    assert snap.ht_goals_line is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_collector/test_collector.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create app/collector/collector.py**

```python
from datetime import datetime, timezone
from app.db.models import League, Team, Fixture, OddsSnapshot
from app.collector.odds_api import OddsAPIClient
from app.collector.espn_api import ESPNClient
from app.config import settings

ESPN_TO_ODDS_API_LEAGUE = {
    "eng.1": "soccer_epl",
    "esp.1": "soccer_spain_la_liga",
    "ger.1": "soccer_germany_bundesliga",
    "ita.1": "soccer_italy_serie_a",
}


class DataCollector:
    def __init__(self, session):
        self.session = session
        self.odds_client = OddsAPIClient(api_key=settings.odds_api_key)
        self.espn_client = ESPNClient()

    def run(self):
        espn_data = self.espn_client.fetch_all_leagues()
        odds_data = self.odds_client.fetch_all_leagues()

        for espn_id, fixtures in espn_data.items():
            league = self.session.query(League).filter_by(espn_id=espn_id).first()
            if not league:
                continue
            for espn_fixture in fixtures:
                fixture = self._upsert_fixture(espn_fixture, league)
                sport_key = ESPN_TO_ODDS_API_LEAGUE[espn_id]
                odds_fixture = self._find_odds_fixture(
                    odds_data.get(sport_key, []),
                    espn_fixture["home_team"],
                    espn_fixture["away_team"],
                )
                if odds_fixture:
                    for bookmaker in odds_fixture["bookmakers"]:
                        self._save_odds_snapshot(fixture.id, bookmaker)

        self.session.commit()

    def _upsert_fixture(self, espn_fixture: dict, league: League) -> Fixture:
        existing = self.session.query(Fixture).filter_by(espn_id=espn_fixture["espn_id"]).first()
        home_team = self._upsert_team(espn_fixture["home_team"], league)
        away_team = self._upsert_team(espn_fixture["away_team"], league)

        if existing:
            existing.status = espn_fixture["status"]
            return existing

        fixture = Fixture(
            espn_id=espn_fixture["espn_id"],
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            league_id=league.id,
            kickoff_at=datetime.fromisoformat(espn_fixture["kickoff_at"].replace("Z", "+00:00")),
            status=espn_fixture["status"],
        )
        self.session.add(fixture)
        self.session.flush()
        return fixture

    def _upsert_team(self, name: str, league: League) -> Team:
        team = self.session.query(Team).filter_by(name=name, league_id=league.id).first()
        if not team:
            team = Team(name=name, league_id=league.id)
            self.session.add(team)
            self.session.flush()
        return team

    def _save_odds_snapshot(self, fixture_id: int, bookmaker: dict):
        h2h = bookmaker.get("h2h") or {}
        totals = bookmaker.get("totals") or {}
        ht_h2h = bookmaker.get("ht_h2h") or {}
        ht_totals = bookmaker.get("ht_totals") or {}

        snap = OddsSnapshot(
            fixture_id=fixture_id,
            bookmaker=bookmaker["key"],
            home_odds=h2h.get("home"),
            draw_odds=h2h.get("draw"),
            away_odds=h2h.get("away"),
            ht_home_odds=ht_h2h.get("home"),
            ht_draw_odds=ht_h2h.get("draw"),
            ht_away_odds=ht_h2h.get("away"),
            total_goals_line=totals.get("line"),
            over_odds=totals.get("over"),
            under_odds=totals.get("under"),
            ht_goals_line=ht_totals.get("line"),
            ht_over_odds=ht_totals.get("over"),
            ht_under_odds=ht_totals.get("under"),
            captured_at=datetime.now(timezone.utc),
        )
        self.session.add(snap)

    def _find_odds_fixture(self, odds_fixtures: list, home_team: str, away_team: str) -> dict | None:
        for f in odds_fixtures:
            if f["home_team"] == home_team and f["away_team"] == away_team:
                return f
        return None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_collector/test_collector.py -v
```
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/collector/collector.py tests/test_collector/test_collector.py
git commit -m "feat: data collector orchestrator — upserts fixtures and saves odds snapshots"
```

---

## Task 7: BaseModel Interface

**Files:**
- Create: `app/models/base.py`
- Create: `tests/test_models/test_base.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models/test_base.py
import pytest
from app.models.base import BaseModel, ModelPrediction

BET_TYPES = ["match_result", "ht_result", "total_goals", "ht_goals"]
RESULT_OUTCOMES = ["home", "draw", "away"]
GOALS_OUTCOMES = ["over", "under"]


class ConcreteModel(BaseModel):
    name = "test_model"
    version = "1.0"

    def predict(self, fixture, odds, history):
        return [
            ModelPrediction(bet_type="match_result", outcome="home", confidence=0.65, line=None),
            ModelPrediction(bet_type="total_goals", outcome="over", confidence=0.55, line=2.5),
        ]


def test_concrete_model_returns_predictions():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    assert len(preds) == 2


def test_prediction_bet_types_are_valid():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    for pred in preds:
        assert pred.bet_type in BET_TYPES


def test_prediction_outcomes_are_valid():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    for pred in preds:
        if pred.bet_type in ("match_result", "ht_result"):
            assert pred.outcome in RESULT_OUTCOMES
        else:
            assert pred.outcome in GOALS_OUTCOMES


def test_prediction_confidence_is_between_0_and_1():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    for pred in preds:
        assert 0.0 <= pred.confidence <= 1.0


def test_model_without_predict_raises():
    with pytest.raises(TypeError):
        class BadModel(BaseModel):
            name = "bad"
            version = "1.0"
        BadModel()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_models/test_base.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create app/models/base.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ModelPrediction:
    bet_type: str    # "match_result" | "ht_result" | "total_goals" | "ht_goals"
    outcome: str     # match_result/ht_result: "home"|"draw"|"away"  |  total_goals/ht_goals: "over"|"under"
    confidence: float  # 0.0 – 1.0
    line: float | None  # goals line for over/under bets; None for result bets


class BaseModel(ABC):
    name: str
    version: str

    @abstractmethod
    def predict(self, fixture: dict, odds: dict, history: list[dict]) -> list[ModelPrediction]:
        """
        fixture  — dict with keys: id, home_team, away_team, league, kickoff_at
        odds     — latest OddsSnapshot as dict (all bet types included)
        history  — list of recent Result dicts for both teams (configurable lookback)
        Returns a list of ModelPrediction — model may return one or all bet types.
        """
        ...
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_models/test_base.py -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/base.py tests/test_models/test_base.py
git commit -m "feat: BaseModel ABC and ModelPrediction dataclass"
```

---

## Task 8: Model Registry

**Files:**
- Create: `app/models/registry.py`
- Create: `tests/test_models/test_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models/test_registry.py
import pytest
from app.models.registry import ModelRegistry
from app.db.models import ModelVersion


def test_register_creates_inactive_model(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First version")
    mv = db.query(ModelVersion).first()
    assert mv.name == "my_model"
    assert mv.version == "1.0"
    assert mv.active is False


def test_activate_sets_active_flag(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First version")
    registry.activate("my_model", "1.0")
    mv = db.query(ModelVersion).first()
    assert mv.active is True


def test_deactivate_clears_active_flag(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First version")
    registry.activate("my_model", "1.0")
    registry.deactivate("my_model", "1.0")
    mv = db.query(ModelVersion).first()
    assert mv.active is False


def test_get_active_models_returns_only_active(db):
    registry = ModelRegistry(db)
    registry.register("model_a", "1.0", "active")
    registry.register("model_b", "1.0", "inactive")
    registry.activate("model_a", "1.0")
    active = registry.get_active()
    assert len(active) == 1
    assert active[0].name == "model_a"


def test_register_duplicate_raises(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First")
    with pytest.raises(ValueError, match="already registered"):
        registry.register("my_model", "1.0", "Duplicate")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_models/test_registry.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create app/models/registry.py**

```python
from datetime import datetime
from app.db.models import ModelVersion


class ModelRegistry:
    def __init__(self, session):
        self.session = session

    def register(self, name: str, version: str, description: str = "") -> ModelVersion:
        existing = self.session.query(ModelVersion).filter_by(name=name, version=version).first()
        if existing:
            raise ValueError(f"Model {name}@{version} already registered")
        mv = ModelVersion(name=name, version=version, description=description,
                          active=False, created_at=datetime.utcnow())
        self.session.add(mv)
        self.session.commit()
        return mv

    def activate(self, name: str, version: str):
        mv = self._get_or_raise(name, version)
        mv.active = True
        self.session.commit()

    def deactivate(self, name: str, version: str):
        mv = self._get_or_raise(name, version)
        mv.active = False
        self.session.commit()

    def get_active(self) -> list[ModelVersion]:
        return self.session.query(ModelVersion).filter_by(active=True).all()

    def list_all(self) -> list[ModelVersion]:
        return self.session.query(ModelVersion).order_by(ModelVersion.created_at).all()

    def _get_or_raise(self, name: str, version: str) -> ModelVersion:
        mv = self.session.query(ModelVersion).filter_by(name=name, version=version).first()
        if not mv:
            raise ValueError(f"Model {name}@{version} not found")
        return mv
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_models/test_registry.py -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/registry.py tests/test_models/test_registry.py
git commit -m "feat: model registry — register, activate, deactivate, list"
```

---

## Task 9: Prediction Engine

**Files:**
- Create: `app/predictor.py`
- Create: `tests/test_predictor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_predictor.py
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.predictor import PredictionEngine
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction
from app.models.base import BaseModel, ModelPrediction


class AlwaysHomeModel(BaseModel):
    name = "always_home"
    version = "1.0"

    def predict(self, fixture, odds, history):
        return [
            ModelPrediction(bet_type="match_result", outcome="home", confidence=0.70, line=None),
            ModelPrediction(bet_type="total_goals", outcome="over", confidence=0.60, line=2.5),
        ]


def make_fixture_with_odds(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    kickoff = datetime.now(timezone.utc) + timedelta(hours=1)
    fixture = Fixture(espn_id="e1", home_team_id=home.id, away_team_id=away.id,
                      league_id=league.id, kickoff_at=kickoff, status="scheduled")
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(fixture_id=fixture.id, bookmaker="betmgm",
                        home_odds=2.10, draw_odds=3.50, away_odds=3.20,
                        total_goals_line=2.5, over_odds=1.90, under_odds=1.90,
                        captured_at=datetime.now(timezone.utc))
    db.add(snap)
    db.flush()
    return fixture, snap


def test_engine_stores_predictions_for_active_models(db):
    fixture, snap = make_fixture_with_odds(db)
    mv = ModelVersion(name="always_home", version="1.0", active=True, created_at=datetime.utcnow())
    db.add(mv)
    db.flush()

    engine = PredictionEngine(db, model_classes=[AlwaysHomeModel])
    engine.run()

    preds = db.query(Prediction).all()
    assert len(preds) == 2
    bet_types = {p.bet_type for p in preds}
    assert "match_result" in bet_types
    assert "total_goals" in bet_types


def test_engine_tags_prediction_with_model_id(db):
    fixture, snap = make_fixture_with_odds(db)
    mv = ModelVersion(name="always_home", version="1.0", active=True, created_at=datetime.utcnow())
    db.add(mv)
    db.flush()

    engine = PredictionEngine(db, model_classes=[AlwaysHomeModel])
    engine.run()

    pred = db.query(Prediction).filter_by(bet_type="match_result").first()
    assert pred.model_id == mv.id
    assert pred.predicted_outcome == "home"
    assert pred.confidence == 0.70


def test_engine_skips_fixtures_without_odds(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    kickoff = datetime.now(timezone.utc) + timedelta(hours=1)
    fixture = Fixture(espn_id="e1", home_team_id=home.id, away_team_id=away.id,
                      league_id=league.id, kickoff_at=kickoff, status="scheduled")
    db.add(fixture)
    db.flush()
    mv = ModelVersion(name="always_home", version="1.0", active=True, created_at=datetime.utcnow())
    db.add(mv)
    db.flush()

    engine = PredictionEngine(db, model_classes=[AlwaysHomeModel])
    engine.run()

    assert db.query(Prediction).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_predictor.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create app/predictor.py**

```python
from datetime import datetime, timezone, timedelta
from app.db.models import ModelVersion, Fixture, OddsSnapshot, Prediction, Result, Team, League
from app.models.base import BaseModel, ModelPrediction
from app.config import settings


class PredictionEngine:
    def __init__(self, session, model_classes: list[type[BaseModel]]):
        self.session = session
        self.model_map = {(cls.name, cls.version): cls() for cls in model_classes}

    def run(self):
        active_versions = self.session.query(ModelVersion).filter_by(active=True).all()
        upcoming = self._get_upcoming_fixtures()

        for mv in active_versions:
            model = self.model_map.get((mv.name, mv.version))
            if not model:
                continue
            for fixture in upcoming:
                snap = self._latest_snapshot(fixture.id)
                if not snap:
                    continue
                history = self._get_history(fixture)
                odds_dict = self._snapshot_to_dict(snap)
                fixture_dict = self._fixture_to_dict(fixture)
                predictions = model.predict(fixture_dict, odds_dict, history)
                for pred in predictions:
                    self._save_prediction(mv.id, fixture.id, snap.id, pred)

        self.session.commit()

    def _get_upcoming_fixtures(self) -> list[Fixture]:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=settings.prediction_lead_hours)
        return (self.session.query(Fixture)
                .filter(Fixture.status == "scheduled")
                .filter(Fixture.kickoff_at <= cutoff)
                .all())

    def _latest_snapshot(self, fixture_id: int) -> OddsSnapshot | None:
        return (self.session.query(OddsSnapshot)
                .filter_by(fixture_id=fixture_id)
                .order_by(OddsSnapshot.captured_at.desc())
                .first())

    def _get_history(self, fixture: Fixture, lookback: int = 10) -> list[dict]:
        recent = (self.session.query(Result)
                  .join(Fixture, Result.fixture_id == Fixture.id)
                  .filter(
                      (Fixture.home_team_id == fixture.home_team_id) |
                      (Fixture.away_team_id == fixture.home_team_id) |
                      (Fixture.home_team_id == fixture.away_team_id) |
                      (Fixture.away_team_id == fixture.away_team_id)
                  )
                  .order_by(Fixture.kickoff_at.desc())
                  .limit(lookback)
                  .all())
        return [self._result_to_dict(r) for r in recent]

    def _save_prediction(self, model_id: int, fixture_id: int, snap_id: int, pred: ModelPrediction):
        p = Prediction(
            model_id=model_id,
            fixture_id=fixture_id,
            bet_type=pred.bet_type,
            predicted_outcome=pred.outcome,
            confidence=pred.confidence,
            line=pred.line,
            odds_snapshot_id=snap_id,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(p)

    def _snapshot_to_dict(self, snap: OddsSnapshot) -> dict:
        return {
            "home_odds": snap.home_odds, "draw_odds": snap.draw_odds, "away_odds": snap.away_odds,
            "ht_home_odds": snap.ht_home_odds, "ht_draw_odds": snap.ht_draw_odds, "ht_away_odds": snap.ht_away_odds,
            "total_goals_line": snap.total_goals_line, "over_odds": snap.over_odds, "under_odds": snap.under_odds,
            "ht_goals_line": snap.ht_goals_line, "ht_over_odds": snap.ht_over_odds, "ht_under_odds": snap.ht_under_odds,
        }

    def _fixture_to_dict(self, fixture: Fixture) -> dict:
        return {"id": fixture.id, "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id, "league_id": fixture.league_id,
                "kickoff_at": fixture.kickoff_at}

    def _result_to_dict(self, result: Result) -> dict:
        return {"fixture_id": result.fixture_id, "outcome": result.outcome,
                "home_score": result.home_score, "away_score": result.away_score,
                "ht_outcome": result.ht_outcome, "total_goals": result.total_goals,
                "ht_total_goals": result.ht_total_goals}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_predictor.py -v
```
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/predictor.py tests/test_predictor.py
git commit -m "feat: prediction engine — runs active models against upcoming fixtures"
```

---

## Task 10: Results Tracker

**Files:**
- Create: `app/tracker.py`
- Create: `tests/test_tracker.py`

The tracker: fetches completed fixtures from ESPN, stores results, evaluates predictions, updates performance (accuracy + ROI per model/bet_type).

ROI formula: `(odds_at_prediction - 1)` for correct predictions, `-1` for incorrect. Averaged across all predictions.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tracker.py
from datetime import datetime, timezone, timedelta
from app.tracker import ResultsTracker
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Prediction, Result, Performance


def make_completed_fixture(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    kickoff = datetime.now(timezone.utc) - timedelta(hours=3)
    fixture = Fixture(espn_id="e1", home_team_id=home.id, away_team_id=away.id,
                      league_id=league.id, kickoff_at=kickoff, status="completed")
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(fixture_id=fixture.id, bookmaker="betmgm",
                        home_odds=2.10, draw_odds=3.50, away_odds=3.20,
                        total_goals_line=2.5, over_odds=1.90, under_odds=1.90,
                        captured_at=kickoff - timedelta(hours=2))
    db.add(snap)
    db.flush()
    mv = ModelVersion(name="my_model", version="1.0", active=True, created_at=datetime.utcnow())
    db.add(mv)
    db.flush()
    pred = Prediction(model_id=mv.id, fixture_id=fixture.id, bet_type="match_result",
                      predicted_outcome="home", confidence=0.70, line=None,
                      odds_snapshot_id=snap.id, created_at=kickoff - timedelta(hours=1))
    db.add(pred)
    db.flush()
    return fixture, snap, mv, pred


def test_save_result_stores_outcome(db):
    fixture, _, _, _ = make_completed_fixture(db)
    tracker = ResultsTracker(db)
    tracker.save_result(fixture.id, home_score=2, away_score=1,
                        ht_home_score=1, ht_away_score=0)
    result = db.query(Result).first()
    assert result.outcome == "home"
    assert result.ht_outcome == "home"
    assert result.total_goals == 3
    assert result.ht_total_goals == 1


def test_evaluate_correct_match_result_prediction(db):
    fixture, snap, mv, pred = make_completed_fixture(db)
    result = Result(fixture_id=fixture.id, home_score=2, away_score=1, outcome="home",
                    ht_home_score=1, ht_away_score=0, ht_outcome="home",
                    total_goals=3, ht_total_goals=1, verified_at=datetime.utcnow())
    db.add(result)
    db.flush()
    tracker = ResultsTracker(db)
    tracker.evaluate_predictions(fixture.id)
    perf = db.query(Performance).filter_by(model_id=mv.id, bet_type="match_result").first()
    assert perf.total_predictions == 1
    assert perf.correct == 1
    assert perf.accuracy == 1.0
    assert round(perf.roi, 4) == round(snap.home_odds - 1, 4)


def test_evaluate_incorrect_prediction_gives_negative_roi(db):
    fixture, snap, mv, pred = make_completed_fixture(db)
    result = Result(fixture_id=fixture.id, home_score=0, away_score=2, outcome="away",
                    ht_home_score=0, ht_away_score=1, ht_outcome="away",
                    total_goals=2, ht_total_goals=1, verified_at=datetime.utcnow())
    db.add(result)
    db.flush()
    tracker = ResultsTracker(db)
    tracker.evaluate_predictions(fixture.id)
    perf = db.query(Performance).filter_by(model_id=mv.id, bet_type="match_result").first()
    assert perf.correct == 0
    assert perf.roi == -1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tracker.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create app/tracker.py**

```python
from datetime import datetime, timezone
from app.db.models import Fixture, Result, Prediction, OddsSnapshot, Performance


def compute_outcome(home: int, away: int) -> str:
    if home > away:
        return "home"
    elif away > home:
        return "away"
    return "draw"


def prediction_correct(pred: Prediction, result: Result) -> bool:
    if pred.bet_type == "match_result":
        return pred.predicted_outcome == result.outcome
    if pred.bet_type == "ht_result":
        return pred.predicted_outcome == result.ht_outcome
    if pred.bet_type == "total_goals":
        if pred.line is None or result.total_goals is None:
            return False
        return (pred.predicted_outcome == "over" and result.total_goals > pred.line) or \
               (pred.predicted_outcome == "under" and result.total_goals < pred.line)
    if pred.bet_type == "ht_goals":
        if pred.line is None or result.ht_total_goals is None:
            return False
        return (pred.predicted_outcome == "over" and result.ht_total_goals > pred.line) or \
               (pred.predicted_outcome == "under" and result.ht_total_goals < pred.line)
    return False


def get_odds_for_prediction(pred: Prediction, snap: OddsSnapshot) -> float | None:
    mapping = {
        ("match_result", "home"): snap.home_odds,
        ("match_result", "draw"): snap.draw_odds,
        ("match_result", "away"): snap.away_odds,
        ("ht_result", "home"): snap.ht_home_odds,
        ("ht_result", "draw"): snap.ht_draw_odds,
        ("ht_result", "away"): snap.ht_away_odds,
        ("total_goals", "over"): snap.over_odds,
        ("total_goals", "under"): snap.under_odds,
        ("ht_goals", "over"): snap.ht_over_odds,
        ("ht_goals", "under"): snap.ht_under_odds,
    }
    return mapping.get((pred.bet_type, pred.predicted_outcome))


class ResultsTracker:
    def __init__(self, session):
        self.session = session

    def save_result(self, fixture_id: int, home_score: int, away_score: int,
                    ht_home_score: int | None = None, ht_away_score: int | None = None):
        ht_outcome = compute_outcome(ht_home_score, ht_away_score) if ht_home_score is not None else None
        result = Result(
            fixture_id=fixture_id,
            home_score=home_score,
            away_score=away_score,
            outcome=compute_outcome(home_score, away_score),
            ht_home_score=ht_home_score,
            ht_away_score=ht_away_score,
            ht_outcome=ht_outcome,
            total_goals=home_score + away_score,
            ht_total_goals=(ht_home_score + ht_away_score) if ht_home_score is not None else None,
            verified_at=datetime.now(timezone.utc),
        )
        self.session.add(result)
        self.session.commit()

    def evaluate_predictions(self, fixture_id: int):
        result = self.session.query(Result).filter_by(fixture_id=fixture_id).first()
        if not result:
            return
        predictions = self.session.query(Prediction).filter_by(fixture_id=fixture_id).all()
        for pred in predictions:
            snap = self.session.query(OddsSnapshot).filter_by(id=pred.odds_snapshot_id).first()
            is_correct = prediction_correct(pred, result)
            odds = get_odds_for_prediction(pred, snap) if snap else None
            roi_delta = (odds - 1) if (is_correct and odds) else -1.0
            self._update_performance(pred.model_id, pred.bet_type, is_correct, roi_delta)
        self.session.commit()

    def _update_performance(self, model_id: int, bet_type: str, correct: bool, roi_delta: float):
        perf = self.session.query(Performance).filter_by(model_id=model_id, bet_type=bet_type).first()
        if not perf:
            perf = Performance(model_id=model_id, bet_type=bet_type,
                               total_predictions=0, correct=0, accuracy=0.0, roi=0.0)
            self.session.add(perf)
            self.session.flush()

        n = perf.total_predictions
        perf.total_predictions = n + 1
        perf.correct = perf.correct + (1 if correct else 0)
        perf.accuracy = perf.correct / perf.total_predictions
        perf.roi = ((perf.roi * n) + roi_delta) / perf.total_predictions
        perf.updated_at = datetime.now(timezone.utc)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_tracker.py -v
```
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/tracker.py tests/test_tracker.py
git commit -m "feat: results tracker — stores results, evaluates predictions, updates accuracy and ROI"
```

---

## Task 11: Backtester

**Files:**
- Create: `app/backtester.py`
- Create: `tests/test_backtester.py`

The backtester replays the prediction engine against historical completed fixtures and writes to `backtest_runs`, never touching the live `predictions` table.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_backtester.py
from datetime import datetime, timezone, timedelta
from app.backtester import Backtester
from app.db.models import League, Team, Fixture, OddsSnapshot, ModelVersion, Result, BacktestRun
from app.models.base import BaseModel, ModelPrediction


class AlwaysHomeModel(BaseModel):
    name = "always_home"
    version = "1.0"

    def predict(self, fixture, odds, history):
        return [ModelPrediction(bet_type="match_result", outcome="home", confidence=0.7, line=None)]


def seed_historical(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    mv = ModelVersion(name="always_home", version="1.0", active=False, created_at=datetime.utcnow())
    db.add(mv)
    db.flush()

    kickoff = datetime.now(timezone.utc) - timedelta(days=7)
    fixture = Fixture(espn_id="e1", home_team_id=home.id, away_team_id=away.id,
                      league_id=league.id, kickoff_at=kickoff, status="completed")
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(fixture_id=fixture.id, bookmaker="betmgm",
                        home_odds=2.10, draw_odds=3.50, away_odds=3.20,
                        total_goals_line=2.5, over_odds=1.90, under_odds=1.90,
                        captured_at=kickoff - timedelta(hours=2))
    db.add(snap)
    db.flush()
    result = Result(fixture_id=fixture.id, home_score=2, away_score=0, outcome="home",
                    ht_home_score=1, ht_away_score=0, ht_outcome="home",
                    total_goals=2, ht_total_goals=1, verified_at=kickoff + timedelta(hours=2))
    db.add(result)
    db.flush()
    return mv, kickoff


def test_backtest_creates_run_record(db):
    mv, kickoff = seed_historical(db)
    backtester = Backtester(db, model_classes=[AlwaysHomeModel])
    date_from = kickoff - timedelta(days=1)
    date_to = kickoff + timedelta(days=1)
    backtester.run("always_home", "1.0", date_from, date_to)
    run = db.query(BacktestRun).first()
    assert run is not None
    assert run.model_id == mv.id
    assert run.total == 1
    assert run.correct == 1
    assert run.accuracy == 1.0


def test_backtest_does_not_write_to_predictions_table(db):
    from app.db.models import Prediction
    mv, kickoff = seed_historical(db)
    backtester = Backtester(db, model_classes=[AlwaysHomeModel])
    date_from = kickoff - timedelta(days=1)
    date_to = kickoff + timedelta(days=1)
    backtester.run("always_home", "1.0", date_from, date_to)
    assert db.query(Prediction).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_backtester.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create app/backtester.py**

```python
from datetime import datetime, timezone
from app.db.models import ModelVersion, Fixture, OddsSnapshot, Result, BacktestRun
from app.models.base import BaseModel, ModelPrediction
from app.tracker import prediction_correct, get_odds_for_prediction


class Backtester:
    def __init__(self, session, model_classes: list[type[BaseModel]]):
        self.session = session
        self.model_map = {(cls.name, cls.version): cls() for cls in model_classes}

    def run(self, model_name: str, model_version: str, date_from: datetime, date_to: datetime):
        mv = self.session.query(ModelVersion).filter_by(name=model_name, version=model_version).first()
        if not mv:
            raise ValueError(f"Model {model_name}@{model_version} not registered")

        model = self.model_map.get((model_name, model_version))
        if not model:
            raise ValueError(f"Model class for {model_name}@{model_version} not provided")

        fixtures = (self.session.query(Fixture)
                    .filter(Fixture.status == "completed")
                    .filter(Fixture.kickoff_at >= date_from)
                    .filter(Fixture.kickoff_at <= date_to)
                    .all())

        bet_type_stats: dict[str, dict] = {}

        for fixture in fixtures:
            snap = (self.session.query(OddsSnapshot)
                    .filter_by(fixture_id=fixture.id)
                    .order_by(OddsSnapshot.captured_at.desc())
                    .first())
            result = self.session.query(Result).filter_by(fixture_id=fixture.id).first()
            if not snap or not result:
                continue

            fixture_dict = {"id": fixture.id, "home_team_id": fixture.home_team_id,
                            "away_team_id": fixture.away_team_id, "kickoff_at": fixture.kickoff_at}
            odds_dict = {
                "home_odds": snap.home_odds, "draw_odds": snap.draw_odds, "away_odds": snap.away_odds,
                "ht_home_odds": snap.ht_home_odds, "ht_draw_odds": snap.ht_draw_odds, "ht_away_odds": snap.ht_away_odds,
                "total_goals_line": snap.total_goals_line, "over_odds": snap.over_odds, "under_odds": snap.under_odds,
                "ht_goals_line": snap.ht_goals_line, "ht_over_odds": snap.ht_over_odds, "ht_under_odds": snap.ht_under_odds,
            }

            predictions = model.predict(fixture_dict, odds_dict, [])
            for pred in predictions:
                stats = bet_type_stats.setdefault(pred.bet_type, {"total": 0, "correct": 0, "roi_sum": 0.0})
                is_correct = prediction_correct(pred, result)
                odds = get_odds_for_prediction(pred, snap)
                roi_delta = (odds - 1) if (is_correct and odds) else -1.0
                stats["total"] += 1
                stats["correct"] += (1 if is_correct else 0)
                stats["roi_sum"] += roi_delta

        for bet_type, stats in bet_type_stats.items():
            n = stats["total"]
            run = BacktestRun(
                model_id=mv.id,
                bet_type=bet_type,
                date_from=date_from,
                date_to=date_to,
                total=n,
                correct=stats["correct"],
                accuracy=stats["correct"] / n if n else 0.0,
                roi=stats["roi_sum"] / n if n else 0.0,
                run_at=datetime.now(timezone.utc),
            )
            self.session.add(run)

        self.session.commit()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_backtester.py -v
```
Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/backtester.py tests/test_backtester.py
git commit -m "feat: backtester — isolated historical replay with per-bet-type stats"
```

---

## Task 12: Scheduler

**Files:**
- Create: `app/scheduler.py`

APScheduler jobs: collect data every N hours, run predictions N hours before kickoff (checked every 30 minutes).

- [ ] **Step 1: Create app/scheduler.py**

```python
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.db.connection import get_session
from app.db.models import SchedulerLog
from app.collector.collector import DataCollector
from app.predictor import PredictionEngine
from app.tracker import ResultsTracker
from app.config import settings

logger = logging.getLogger(__name__)


def collect_job(model_classes):
    session = get_session()
    log = SchedulerLog(job_name="collect", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        DataCollector(session).run()
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("collect_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def predict_job(model_classes):
    session = get_session()
    log = SchedulerLog(job_name="predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        PredictionEngine(session, model_classes=model_classes).run()
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def track_results_job():
    session = get_session()
    log = SchedulerLog(job_name="track_results", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.db.models import Fixture, Result
        from app.collector.espn_api import ESPNClient
        espn = ESPNClient()
        all_fixtures = espn.fetch_all_leagues()
        tracker = ResultsTracker(session)
        for league_id, fixtures in all_fixtures.items():
            for espn_fixture in fixtures:
                if espn_fixture["status"] != "completed":
                    continue
                db_fixture = session.query(Fixture).filter_by(espn_id=espn_fixture["espn_id"]).first()
                if not db_fixture:
                    continue
                existing = session.query(Result).filter_by(fixture_id=db_fixture.id).first()
                if existing:
                    continue
                if espn_fixture["home_score"] is None:
                    continue
                tracker.save_result(
                    db_fixture.id,
                    home_score=espn_fixture["home_score"],
                    away_score=espn_fixture["away_score"],
                    ht_home_score=espn_fixture.get("ht_home_score"),
                    ht_away_score=espn_fixture.get("ht_away_score"),
                )
                tracker.evaluate_predictions(db_fixture.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("track_results_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def start_scheduler(model_classes):
    scheduler = BlockingScheduler()
    scheduler.add_job(
        collect_job, IntervalTrigger(hours=settings.collection_interval_hours),
        args=[model_classes], id="collect", replace_existing=True
    )
    scheduler.add_job(
        predict_job, IntervalTrigger(minutes=30),
        args=[model_classes], id="predict", replace_existing=True
    )
    scheduler.add_job(
        track_results_job, IntervalTrigger(hours=1),
        id="track_results", replace_existing=True
    )
    logger.info("Scheduler started")
    scheduler.start()
```

- [ ] **Step 2: Commit**

```bash
git add app/scheduler.py
git commit -m "feat: APScheduler — collect, predict, track_results jobs with DB logging"
```

---

## Task 13: Prometheus Metrics Endpoint

**Files:**
- Create: `app/metrics.py`

Exposes `/metrics` on port 9090 for the existing observability stack to scrape.

- [ ] **Step 1: Create app/metrics.py**

```python
import threading
from prometheus_client import start_http_server, Gauge, Counter
from app.db.connection import get_session
from app.db.models import Performance, SchedulerLog

model_accuracy = Gauge("betting_model_accuracy", "Prediction accuracy per model/bet_type",
                       ["model_name", "model_version", "bet_type"])
model_roi = Gauge("betting_model_roi", "Average ROI per model/bet_type",
                  ["model_name", "model_version", "bet_type"])
scheduler_errors = Counter("scheduler_job_errors_total", "Scheduler job error count", ["job_name"])


def update_metrics():
    session = get_session()
    try:
        from app.db.models import ModelVersion
        performances = session.query(Performance).all()
        for perf in performances:
            mv = session.query(ModelVersion).filter_by(id=perf.model_id).first()
            if not mv:
                continue
            model_accuracy.labels(model_name=mv.name, model_version=mv.version,
                                   bet_type=perf.bet_type).set(perf.accuracy or 0)
            model_roi.labels(model_name=mv.name, model_version=mv.version,
                              bet_type=perf.bet_type).set(perf.roi or 0)
    finally:
        session.close()


def start_metrics_server(port: int = 9090):
    start_http_server(port)
    timer = threading.Timer(60, _refresh_loop)
    timer.daemon = True
    timer.start()


def _refresh_loop():
    update_metrics()
    timer = threading.Timer(60, _refresh_loop)
    timer.daemon = True
    timer.start()
```

- [ ] **Step 2: Commit**

```bash
git add app/metrics.py
git commit -m "feat: Prometheus metrics endpoint — accuracy and ROI gauges per model/bet_type"
```

---

## Task 14: CLI

**Files:**
- Create: `cli.py`

- [ ] **Step 1: Create cli.py**

```python
import click
import logging
from app.db.connection import get_session
from app.db.models import Base
from app.db.connection import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Import all user-defined model classes here as they are added
MODEL_CLASSES = []  # e.g. [MyModelV1, MyModelV2]


@click.group()
def cli():
    """Soccer Betting Model CLI"""


@cli.command()
def migrate():
    """Run database migrations (creates tables)."""
    Base.metadata.create_all(engine)
    click.echo("Database tables created.")


@cli.command()
def collect():
    """Run data collection now (fixtures + odds)."""
    from app.collector.collector import DataCollector
    session = get_session()
    try:
        DataCollector(session).run()
        click.echo("Data collection complete.")
    finally:
        session.close()


@cli.command()
def predict():
    """Run prediction engine now for upcoming fixtures."""
    from app.predictor import PredictionEngine
    session = get_session()
    try:
        PredictionEngine(session, model_classes=MODEL_CLASSES).run()
        click.echo("Predictions complete.")
    finally:
        session.close()


@cli.command()
@click.option("--model", required=True, help="Model name")
@click.option("--version", required=True, help="Model version")
@click.option("--from-date", required=True, help="Start date YYYY-MM-DD")
@click.option("--to-date", required=True, help="End date YYYY-MM-DD")
def backtest(model, version, from_date, to_date):
    """Backtest a model version against historical data."""
    from app.backtester import Backtester
    from datetime import datetime
    session = get_session()
    try:
        date_from = datetime.strptime(from_date, "%Y-%m-%d")
        date_to = datetime.strptime(to_date, "%Y-%m-%d")
        Backtester(session, model_classes=MODEL_CLASSES).run(model, version, date_from, date_to)
        click.echo(f"Backtest complete for {model}@{version}.")
    finally:
        session.close()


@cli.command()
@click.argument("name")
@click.argument("version")
@click.option("--description", default="", help="Model description")
@click.option("--activate", is_flag=True, default=False, help="Activate immediately")
def register_model(name, version, description, activate):
    """Register a new model version."""
    from app.models.registry import ModelRegistry
    session = get_session()
    try:
        registry = ModelRegistry(session)
        registry.register(name, version, description)
        if activate:
            registry.activate(name, version)
            click.echo(f"Registered and activated {name}@{version}.")
        else:
            click.echo(f"Registered {name}@{version} (inactive). Run activate-model to enable.")
    finally:
        session.close()


@cli.command()
@click.argument("name")
@click.argument("version")
def activate_model(name, version):
    """Activate a registered model version."""
    from app.models.registry import ModelRegistry
    session = get_session()
    try:
        ModelRegistry(session).activate(name, version)
        click.echo(f"Activated {name}@{version}.")
    finally:
        session.close()


@cli.command()
def performance():
    """Print accuracy and ROI per model version and bet type."""
    from app.db.models import Performance, ModelVersion
    session = get_session()
    try:
        rows = session.query(Performance).all()
        if not rows:
            click.echo("No performance data yet.")
            return
        click.echo(f"\n{'Model':<20} {'Version':<10} {'Bet Type':<15} {'Preds':>6} {'Correct':>8} {'Accuracy':>10} {'ROI':>8}")
        click.echo("-" * 80)
        for p in rows:
            mv = session.query(ModelVersion).filter_by(id=p.model_id).first()
            click.echo(f"{mv.name:<20} {mv.version:<10} {p.bet_type:<15} {p.total_predictions:>6} "
                       f"{p.correct:>8} {p.accuracy:>10.1%} {p.roi:>8.3f}")
    finally:
        session.close()


@cli.command()
def scheduler():
    """Start the scheduler (blocking — use as container entrypoint)."""
    from app.scheduler import start_scheduler
    from app.metrics import start_metrics_server
    start_metrics_server(port=9090)
    start_scheduler(model_classes=MODEL_CLASSES)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Test CLI help**

```bash
python cli.py --help
python cli.py performance --help
python cli.py backtest --help
```
Expected: Help text displays for all commands with no import errors.

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "feat: Click CLI — collect, predict, backtest, register-model, performance, scheduler"
```

---

## Task 15: Kubernetes Manifests

**Files:**
- Create: `k8s/namespace.yaml`
- Create: `k8s/postgres/statefulset.yaml`
- Create: `k8s/postgres/service.yaml`
- Create: `k8s/configmap.yaml`
- Create: `k8s/secret.yaml.example`
- Create: `k8s/deployment.yaml`
- Create: `k8s/ingress.yaml`

- [ ] **Step 1: Create k8s/namespace.yaml**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tenant-b
```

- [ ] **Step 2: Create k8s/postgres/statefulset.yaml**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: tenant-b
spec:
  selector:
    matchLabels:
      app: postgres
  serviceName: postgres
  replicas: 1
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:16
          env:
            - name: POSTGRES_DB
              value: soccerbet
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: betting-secrets
                  key: POSTGRES_USER
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: betting-secrets
                  key: POSTGRES_PASSWORD
          ports:
            - containerPort: 5432
          volumeMounts:
            - name: postgres-data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: postgres-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: longhorn
        resources:
          requests:
            storage: 10Gi
```

- [ ] **Step 3: Create k8s/postgres/service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: tenant-b
spec:
  selector:
    app: postgres
  ports:
    - port: 5432
      targetPort: 5432
  clusterIP: None
```

- [ ] **Step 4: Create k8s/configmap.yaml**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: betting-config
  namespace: tenant-b
data:
  COLLECTION_INTERVAL_HOURS: "6"
  PREDICTION_LEAD_HOURS: "2"
```

- [ ] **Step 5: Create k8s/secret.yaml.example**

```yaml
# Copy to secret.yaml, fill in values, apply with kubectl — DO NOT commit secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: betting-secrets
  namespace: tenant-b
type: Opaque
stringData:
  DATABASE_URL: postgresql://betuser:betpass@postgres:5432/soccerbet
  ODDS_API_KEY: your_odds_api_key_here
  POSTGRES_USER: betuser
  POSTGRES_PASSWORD: betpass
```

- [ ] **Step 6: Create k8s/deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: soccer-betting-model
  namespace: tenant-b
spec:
  replicas: 1
  selector:
    matchLabels:
      app: soccer-betting-model
  template:
    metadata:
      labels:
        app: soccer-betting-model
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
        prometheus.io/path: "/metrics"
    spec:
      containers:
        - name: app
          image: your-registry/soccer-betting-model:latest
          command: ["python", "cli.py", "scheduler"]
          envFrom:
            - configMapRef:
                name: betting-config
            - secretRef:
                name: betting-secrets
          ports:
            - containerPort: 9090
              name: metrics
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

- [ ] **Step 7: Create k8s/ingress.yaml**

```yaml
# Placeholder for future UI — no routes active yet
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: soccer-betting-model
  namespace: tenant-b
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
    - host: betting.local
      http:
        paths: []
```

- [ ] **Step 8: Commit**

```bash
git add k8s/
git commit -m "feat: Kubernetes manifests — Longhorn PVC, ConfigMap, Deployment, Ingress placeholder"
```

---

## Task 16: Jenkinsfile

**Files:**
- Create: `Jenkinsfile`

- [ ] **Step 1: Create Jenkinsfile**

```groovy
pipeline {
    agent any

    environment {
        IMAGE_NAME = "your-registry/soccer-betting-model"
        IMAGE_TAG  = "${env.GIT_COMMIT[0..7]}"
        KUBECONFIG = credentials('kubeconfig-multiverse')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Test') {
            steps {
                sh '''
                    pip install -r requirements.txt
                    pytest tests/ -v --tb=short
                '''
            }
        }

        stage('Build') {
            steps {
                sh "docker build -t ${IMAGE_NAME}:${IMAGE_TAG} ."
            }
        }

        stage('Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'registry-creds',
                                                  usernameVariable: 'REG_USER',
                                                  passwordVariable: 'REG_PASS')]) {
                    sh '''
                        echo "$REG_PASS" | docker login -u "$REG_USER" --password-stdin
                        docker push ${IMAGE_NAME}:${IMAGE_TAG}
                        docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                        docker push ${IMAGE_NAME}:latest
                    '''
                }
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b set image \
                        deployment/soccer-betting-model \
                        app=${IMAGE_NAME}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b rollout status \
                        deployment/soccer-betting-model
                '''
            }
        }
    }

    post {
        failure {
            echo "Build failed — check test output above."
        }
    }
}
```

- [ ] **Step 2: Verify full test suite passes**

```bash
pytest tests/ -v
```
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add Jenkinsfile
git commit -m "feat: Jenkinsfile — test, build, push, deploy to tenant-b"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All components covered — Data Collector (Tasks 4-6), Model Registry (Task 8), BaseModel (Task 7), Prediction Engine (Task 9), Results Tracker (Task 10), Backtester (Task 11), Scheduler (Task 12), CLI (Task 14), Metrics (Task 13), K8s (Task 15), Jenkins (Task 16), Git from Task 1.
- [x] **Four bet types:** All four bet types (match_result, ht_result, total_goals, ht_goals) handled in OddsSnapshot schema, Prediction model, tracker, backtester, and BaseModel interface.
- [x] **Longhorn StorageClass:** Specified in postgres/statefulset.yaml.
- [x] **Tenant B:** All manifests use `namespace: tenant-b`.
- [x] **No placeholders:** All steps contain actual code.
- [x] **Type consistency:** `ModelPrediction` used throughout (Tasks 7, 9, 11). `get_odds_for_prediction` and `prediction_correct` imported from tracker in backtester. `MODEL_CLASSES` list in cli.py is the single place to register user models.
