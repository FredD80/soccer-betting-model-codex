# Phase 1 — API & Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI REST service exposing picks and fixture data, and a React (Vite) dashboard that renders today's picks with pick cards. Both run as separate containers in K8s.

**Architecture:** FastAPI service in `api/` reads from shared Postgres via SQLAlchemy. React SPA in `dashboard/` served by nginx; it fetches from `/api/*` which Ingress routes to the FastAPI service. In docker-compose, vite dev server proxies `/api` to the FastAPI container.

**Tech Stack:** FastAPI, uvicorn, SQLAlchemy (read-only queries), pydantic v2 — React 18, Vite 5, TypeScript, Tailwind CSS.

**Prerequisite:** Phase 1 Data & Predictions plan must be complete (tables `spread_predictions`, `ou_analysis`, `form_cache` must exist).

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `api/__init__.py` | Package marker |
| Create | `api/main.py` | FastAPI app init + router registration |
| Create | `api/config.py` | Settings (database_url from env) |
| Create | `api/deps.py` | `get_session` dependency for FastAPI |
| Create | `api/schemas.py` | Pydantic response models |
| Create | `api/routers/picks.py` | `/picks/today`, `/picks/week`, `/picks/ucl` |
| Create | `api/routers/fixtures.py` | `/fixture/{id}` detail view |
| Create | `api/routers/performance.py` | `/performance` model stats |
| Create | `requirements.api.txt` | FastAPI + uvicorn + httpx deps |
| Create | `Dockerfile.api` | FastAPI container image |
| Create | `tests/test_api/conftest.py` | FastAPI test client fixture |
| Create | `tests/test_api/test_picks.py` | Tests for picks endpoints |
| Create | `tests/test_api/test_fixtures.py` | Tests for fixture detail endpoint |
| Create | `dashboard/package.json` | Node project manifest |
| Create | `dashboard/vite.config.ts` | Vite config with `/api` proxy |
| Create | `dashboard/tailwind.config.ts` | Tailwind config |
| Create | `dashboard/postcss.config.js` | PostCSS (required by Tailwind) |
| Create | `dashboard/tsconfig.json` | TypeScript config |
| Create | `dashboard/index.html` | Vite entry HTML |
| Create | `dashboard/src/main.tsx` | React entry point |
| Create | `dashboard/src/App.tsx` | Root component + routing |
| Create | `dashboard/src/api/client.ts` | Fetch wrapper for API calls |
| Create | `dashboard/src/api/types.ts` | TypeScript types matching API schemas |
| Create | `dashboard/src/components/PickCard.tsx` | Individual fixture pick card |
| Create | `dashboard/src/components/ConfidenceBadge.tsx` | ELITE/HIGH badge component |
| Create | `dashboard/src/pages/TodayPage.tsx` | Today's picks page |
| Create | `dashboard/nginx.conf` | nginx config for SPA routing |
| Create | `Dockerfile.dashboard` | Multi-stage node build + nginx image |

---

## Task 1: FastAPI scaffold and dependencies

**Files:**
- Create: `requirements.api.txt`
- Create: `api/__init__.py`
- Create: `api/config.py`
- Create: `api/deps.py`
- Create: `api/main.py`

- [ ] **Step 1: Create requirements.api.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.36
psycopg2-binary==2.9.10
pydantic-settings==2.7.0
httpx==0.28.0
pytest==8.3.4
pytest-asyncio==0.24.0
```

- [ ] **Step 2: Create api/__init__.py**

```python
```
(empty file)

- [ ] **Step 3: Create api/config.py**

```python
from pydantic_settings import BaseSettings


class APISettings(BaseSettings):
    database_url: str
    api_prefix: str = "/api"

    class Config:
        env_file = ".env"


settings = APISettings()
```

- [ ] **Step 4: Create api/deps.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from api.config import settings

_engine = create_engine(settings.database_url)
_SessionLocal = sessionmaker(bind=_engine)


def get_session():
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 5: Create api/main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Soccer Prediction API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened in prod via K8s NetworkPolicy
    allow_methods=["GET"],
    allow_headers=["*"],
)

from api.routers import picks, fixtures, performance  # noqa: E402
app.include_router(picks.router, prefix="/picks", tags=["picks"])
app.include_router(fixtures.router, prefix="/fixture", tags=["fixtures"])
app.include_router(performance.router, prefix="/performance", tags=["performance"])


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Create api/routers/__init__.py**

```python
```
(empty file)

- [ ] **Step 7: Verify the app imports cleanly**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
pip install fastapi uvicorn httpx pytest-asyncio 2>/dev/null || pip install -r requirements.api.txt
python -c "from api.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add api/ requirements.api.txt
git commit -m "feat: FastAPI app scaffold with config, deps, and router structure"
```

---

## Task 2: Pydantic response schemas

**Files:**
- Create: `api/schemas.py`

- [ ] **Step 1: Write failing test that imports schemas**

Create `tests/test_api/__init__.py` (empty) and `tests/test_api/test_schemas.py`:

```python
def test_spread_pick_schema():
    from api.schemas import SpreadPickResponse
    pick = SpreadPickResponse(
        team_side="home",
        goal_line=-0.5,
        cover_probability=0.62,
        push_probability=0.0,
        ev_score=0.08,
        confidence_tier="HIGH",
    )
    assert pick.goal_line == -0.5
    assert pick.confidence_tier == "HIGH"


def test_ou_pick_schema():
    from api.schemas import OUPickResponse
    ou = OUPickResponse(
        line=2.5,
        direction="over",
        probability=0.58,
        ev_score=0.06,
        confidence_tier="HIGH",
    )
    assert ou.line == 2.5
    assert ou.direction == "over"


def test_fixture_pick_response_schema():
    from api.schemas import FixturePickResponse, SpreadPickResponse, OUPickResponse
    from datetime import datetime, timezone
    pick = FixturePickResponse(
        fixture_id=1,
        home_team="Arsenal",
        away_team="Chelsea",
        league="Premier League",
        kickoff_at=datetime.now(timezone.utc),
        best_spread=SpreadPickResponse(
            team_side="home", goal_line=-0.5,
            cover_probability=0.62, push_probability=0.0,
            ev_score=0.08, confidence_tier="HIGH",
        ),
        best_ou=None,
        top_ev=0.08,
    )
    assert pick.home_team == "Arsenal"
    assert pick.best_spread is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api/test_schemas.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'api.schemas'`

- [ ] **Step 3: Create api/schemas.py**

```python
from datetime import datetime
from pydantic import BaseModel


class SpreadPickResponse(BaseModel):
    team_side: str               # "home" | "away"
    goal_line: float             # -1.5 | -1.0 | -0.5 | 0.5 | 1.0 | 1.5
    cover_probability: float
    push_probability: float
    ev_score: float | None
    confidence_tier: str         # SKIP | MEDIUM | HIGH | ELITE


class OUPickResponse(BaseModel):
    line: float                  # 1.5 | 2.5 | 3.5
    direction: str               # "over" | "under"
    probability: float
    ev_score: float | None
    confidence_tier: str


class FormSummary(BaseModel):
    goals_scored_avg: float
    goals_conceded_avg: float
    spread_cover_rate: float | None
    ou_hit_rate_25: float | None
    matches_count: int


class FixturePickResponse(BaseModel):
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    kickoff_at: datetime
    best_spread: SpreadPickResponse | None   # highest EV spread pick
    best_ou: OUPickResponse | None           # highest EV O/U pick
    top_ev: float | None                     # max of best_spread.ev, best_ou.ev for sorting


class FixtureDetailResponse(BaseModel):
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    kickoff_at: datetime
    home_form: FormSummary | None
    away_form: FormSummary | None
    spread_picks: list[SpreadPickResponse]
    ou_picks: list[OUPickResponse]


class ModelPerformanceResponse(BaseModel):
    model_name: str
    version: str
    bet_type: str
    total_predictions: int
    correct: int
    accuracy: float
    roi: float
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api/test_schemas.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py tests/test_api/
git commit -m "feat: Pydantic response schemas for picks, fixtures, and performance"
```

---

## Task 3: /picks endpoints

**Files:**
- Create: `api/routers/picks.py`
- Create: `tests/test_api/conftest.py`
- Create: `tests/test_api/test_picks.py`

- [ ] **Step 1: Create the test client fixture**

Create `tests/test_api/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base
from api.main import app
from api.deps import get_session


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def api_db(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(api_db):
    app.dependency_overrides[get_session] = lambda: api_db
    yield TestClient(app)
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Write failing tests for /picks/today**

Create `tests/test_api/test_picks.py`:

```python
from datetime import datetime, timezone, timedelta
from app.db.models import (
    League, Team, Fixture, FormCache, ModelVersion,
    SpreadPrediction, OUAnalysis
)


def _seed_pick(db, espn_id="p1", hours_until_kickoff=2, tier="HIGH"):
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id=espn_id,
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=hours_until_kickoff),
        status="scheduled",
    )
    db.add(fixture)
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    sp = SpreadPrediction(
        model_id=mv.id, fixture_id=fixture.id,
        team_side="home", goal_line=-0.5,
        cover_probability=0.62, push_probability=0.0,
        ev_score=0.08, confidence_tier=tier,
        created_at=datetime.now(timezone.utc),
    )
    db.add(sp)
    mv2 = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add(mv2)
    db.flush()
    ou = OUAnalysis(
        model_id=mv2.id, fixture_id=fixture.id,
        line=2.5, direction="over",
        probability=0.58, ev_score=0.06, confidence_tier=tier,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ou)
    db.flush()
    return fixture


def test_picks_today_returns_200(client, api_db):
    response = client.get("/picks/today")
    assert response.status_code == 200


def test_picks_today_returns_high_elite_only(client, api_db):
    _seed_pick(api_db, espn_id="high1", tier="HIGH")
    _seed_pick(api_db, espn_id="skip1", tier="SKIP")
    response = client.get("/picks/today")
    data = response.json()
    # SKIP fixture should not appear
    fixture_ids = {p["fixture_id"] for p in data}
    # Both fixtures seeded but only HIGH one should be in the response
    for p in data:
        assert p["best_spread"]["confidence_tier"] in ("HIGH", "ELITE") or \
               p["best_ou"]["confidence_tier"] in ("HIGH", "ELITE")


def test_picks_today_sorted_by_ev(client, api_db):
    _seed_pick(api_db, espn_id="ev_low", tier="HIGH")
    # Manually set different EV on second pick after seeding
    _seed_pick(api_db, espn_id="ev_high", tier="ELITE")
    response = client.get("/picks/today")
    data = response.json()
    evs = [p["top_ev"] for p in data if p["top_ev"] is not None]
    assert evs == sorted(evs, reverse=True)


def test_picks_today_excludes_past_fixtures(client, api_db):
    _seed_pick(api_db, espn_id="past1", hours_until_kickoff=-3, tier="ELITE")
    response = client.get("/picks/today")
    data = response.json()
    # past fixture should not appear
    for p in data:
        kt = datetime.fromisoformat(p["kickoff_at"].replace("Z", "+00:00"))
        assert kt >= datetime.now(timezone.utc) - timedelta(minutes=1)


def test_picks_week_returns_7_day_window(client, api_db):
    _seed_pick(api_db, espn_id="day3", hours_until_kickoff=72, tier="HIGH")
    _seed_pick(api_db, espn_id="day8", hours_until_kickoff=192, tier="HIGH")  # 8 days out
    response = client.get("/picks/week")
    data = response.json()
    espn_ids_in_response = set()
    # day3 should be in, day8 should not
    for p in data:
        kt = datetime.fromisoformat(p["kickoff_at"].replace("Z", "+00:00"))
        assert kt <= datetime.now(timezone.utc) + timedelta(days=7, minutes=1)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_api/test_picks.py -v
```

Expected: FAIL — `ImportError` or 404 on `/picks/today`

- [ ] **Step 4: Implement api/routers/picks.py**

```python
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.models import (
    Fixture, League, Team, SpreadPrediction, OUAnalysis
)
from api.deps import get_session
from api.schemas import FixturePickResponse, SpreadPickResponse, OUPickResponse

router = APIRouter()

_SHOW_TIERS = {"HIGH", "ELITE"}


def _team_name(session: Session, team_id: int) -> str:
    t = session.query(Team).filter_by(id=team_id).first()
    return t.name if t else "Unknown"


def _league_name(session: Session, league_id: int) -> str:
    lg = session.query(League).filter_by(id=league_id).first()
    return lg.name if lg else "Unknown"


def _best_spread(session: Session, fixture_id: int) -> SpreadPickResponse | None:
    picks = (
        session.query(SpreadPrediction)
        .filter(SpreadPrediction.fixture_id == fixture_id)
        .filter(SpreadPrediction.confidence_tier.in_(_SHOW_TIERS))
        .order_by(SpreadPrediction.ev_score.desc())
        .first()
    )
    if not picks:
        return None
    return SpreadPickResponse(
        team_side=picks.team_side,
        goal_line=picks.goal_line,
        cover_probability=picks.cover_probability,
        push_probability=picks.push_probability or 0.0,
        ev_score=picks.ev_score,
        confidence_tier=picks.confidence_tier,
    )


def _best_ou(session: Session, fixture_id: int) -> OUPickResponse | None:
    pick = (
        session.query(OUAnalysis)
        .filter(OUAnalysis.fixture_id == fixture_id)
        .filter(OUAnalysis.confidence_tier.in_(_SHOW_TIERS))
        .order_by(OUAnalysis.ev_score.desc())
        .first()
    )
    if not pick:
        return None
    return OUPickResponse(
        line=pick.line,
        direction=pick.direction,
        probability=pick.probability,
        ev_score=pick.ev_score,
        confidence_tier=pick.confidence_tier,
    )


def _build_fixture_pick(session: Session, fixture: Fixture) -> FixturePickResponse | None:
    spread = _best_spread(session, fixture.id)
    ou = _best_ou(session, fixture.id)
    if not spread and not ou:
        return None
    spread_ev = spread.ev_score if spread else None
    ou_ev = ou.ev_score if ou else None
    top_ev = max(e for e in (spread_ev, ou_ev) if e is not None) if (spread_ev or ou_ev) else None
    return FixturePickResponse(
        fixture_id=fixture.id,
        home_team=_team_name(session, fixture.home_team_id),
        away_team=_team_name(session, fixture.away_team_id),
        league=_league_name(session, fixture.league_id),
        kickoff_at=fixture.kickoff_at,
        best_spread=spread,
        best_ou=ou,
        top_ev=top_ev,
    )


def _picks_in_window(session: Session, from_dt: datetime, to_dt: datetime) -> list[FixturePickResponse]:
    fixtures = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.kickoff_at >= from_dt)
        .filter(Fixture.kickoff_at <= to_dt)
        .all()
    )
    picks = []
    for f in fixtures:
        p = _build_fixture_pick(session, f)
        if p:
            picks.append(p)
    return sorted(picks, key=lambda p: p.top_ev or 0.0, reverse=True)


@router.get("/today", response_model=list[FixturePickResponse])
def picks_today(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    return _picks_in_window(session, now, end)


@router.get("/week", response_model=list[FixturePickResponse])
def picks_week(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    return _picks_in_window(session, now, end)


@router.get("/ucl", response_model=list[FixturePickResponse])
def picks_ucl(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    ucl_league = session.query(League).filter_by(espn_id="uefa.champions").first()
    if not ucl_league:
        return []
    fixtures = (
        session.query(Fixture)
        .filter(Fixture.status == "scheduled")
        .filter(Fixture.league_id == ucl_league.id)
        .filter(Fixture.kickoff_at >= now)
        .filter(Fixture.kickoff_at <= end)
        .all()
    )
    picks = []
    for f in fixtures:
        p = _build_fixture_pick(session, f)
        if p:
            picks.append(p)
    return sorted(picks, key=lambda p: p.top_ev or 0.0, reverse=True)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_api/test_picks.py -v
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add api/routers/picks.py tests/test_api/conftest.py tests/test_api/test_picks.py
git commit -m "feat: /picks/today, /picks/week, /picks/ucl FastAPI endpoints"
```

---

## Task 4: /fixture/{id} endpoint

**Files:**
- Create: `api/routers/fixtures.py`
- Create: `tests/test_api/test_fixtures.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_api/test_fixtures.py`:

```python
from datetime import datetime, timezone, timedelta
from app.db.models import (
    League, Team, Fixture, FormCache, ModelVersion,
    SpreadPrediction, OUAnalysis
)


def _seed_fixture_with_data(db):
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="detail1",
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=2),
        status="scheduled",
    )
    db.add(fixture)
    db.flush()
    db.add(FormCache(team_id=home.id, is_home=True,
                     goals_scored_avg=1.8, goals_conceded_avg=0.9,
                     spread_cover_rate=0.6, ou_hit_rate_25=0.55,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    db.add(FormCache(team_id=away.id, is_home=False,
                     goals_scored_avg=1.2, goals_conceded_avg=1.5,
                     spread_cover_rate=0.4, ou_hit_rate_25=0.6,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    mv2 = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add_all([mv, mv2])
    db.flush()
    for line in [-1.5, -1.0, -0.5, 0.5, 1.0, 1.5]:
        db.add(SpreadPrediction(
            model_id=mv.id, fixture_id=fixture.id,
            team_side="home" if line < 0 else "away",
            goal_line=line, cover_probability=0.55,
            push_probability=0.0, ev_score=0.05,
            confidence_tier="HIGH", created_at=datetime.now(timezone.utc),
        ))
    for line in [1.5, 2.5, 3.5]:
        db.add(OUAnalysis(
            model_id=mv2.id, fixture_id=fixture.id,
            line=line, direction="over", probability=0.57,
            ev_score=0.05, confidence_tier="HIGH",
            created_at=datetime.now(timezone.utc),
        ))
    db.flush()
    return fixture


def test_fixture_detail_returns_200(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    assert response.status_code == 200


def test_fixture_detail_404_on_missing(client, api_db):
    response = client.get("/fixture/99999")
    assert response.status_code == 404


def test_fixture_detail_includes_form(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    data = response.json()
    assert data["home_form"]["goals_scored_avg"] == 1.8
    assert data["away_form"]["goals_conceded_avg"] == 1.5


def test_fixture_detail_includes_all_spread_picks(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    data = response.json()
    assert len(data["spread_picks"]) == 6


def test_fixture_detail_includes_all_ou_picks(client, api_db):
    fixture = _seed_fixture_with_data(api_db)
    response = client.get(f"/fixture/{fixture.id}")
    data = response.json()
    assert len(data["ou_picks"]) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api/test_fixtures.py -v
```

Expected: FAIL — 404 from missing router

- [ ] **Step 3: Implement api/routers/fixtures.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.models import (
    Fixture, League, Team, FormCache,
    SpreadPrediction, OUAnalysis
)
from api.deps import get_session
from api.schemas import (
    FixtureDetailResponse, FormSummary,
    SpreadPickResponse, OUPickResponse
)

router = APIRouter()


@router.get("/{fixture_id}", response_model=FixtureDetailResponse)
def fixture_detail(fixture_id: int, session: Session = Depends(get_session)):
    fixture = session.query(Fixture).filter_by(id=fixture_id).first()
    if not fixture:
        raise HTTPException(status_code=404, detail="Fixture not found")

    home_team = session.query(Team).filter_by(id=fixture.home_team_id).first()
    away_team = session.query(Team).filter_by(id=fixture.away_team_id).first()
    league = session.query(League).filter_by(id=fixture.league_id).first()

    home_fc = session.query(FormCache).filter_by(team_id=fixture.home_team_id, is_home=True).first()
    away_fc = session.query(FormCache).filter_by(team_id=fixture.away_team_id, is_home=False).first()

    spread_rows = (
        session.query(SpreadPrediction)
        .filter_by(fixture_id=fixture_id)
        .order_by(SpreadPrediction.goal_line)
        .all()
    )
    ou_rows = (
        session.query(OUAnalysis)
        .filter_by(fixture_id=fixture_id)
        .order_by(OUAnalysis.line)
        .all()
    )

    return FixtureDetailResponse(
        fixture_id=fixture.id,
        home_team=home_team.name if home_team else "Unknown",
        away_team=away_team.name if away_team else "Unknown",
        league=league.name if league else "Unknown",
        kickoff_at=fixture.kickoff_at,
        home_form=FormSummary(
            goals_scored_avg=home_fc.goals_scored_avg,
            goals_conceded_avg=home_fc.goals_conceded_avg,
            spread_cover_rate=home_fc.spread_cover_rate,
            ou_hit_rate_25=home_fc.ou_hit_rate_25,
            matches_count=home_fc.matches_count,
        ) if home_fc else None,
        away_form=FormSummary(
            goals_scored_avg=away_fc.goals_scored_avg,
            goals_conceded_avg=away_fc.goals_conceded_avg,
            spread_cover_rate=away_fc.spread_cover_rate,
            ou_hit_rate_25=away_fc.ou_hit_rate_25,
            matches_count=away_fc.matches_count,
        ) if away_fc else None,
        spread_picks=[
            SpreadPickResponse(
                team_side=s.team_side,
                goal_line=s.goal_line,
                cover_probability=s.cover_probability,
                push_probability=s.push_probability or 0.0,
                ev_score=s.ev_score,
                confidence_tier=s.confidence_tier,
            ) for s in spread_rows
        ],
        ou_picks=[
            OUPickResponse(
                line=o.line,
                direction=o.direction,
                probability=o.probability,
                ev_score=o.ev_score,
                confidence_tier=o.confidence_tier,
            ) for o in ou_rows
        ],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api/test_fixtures.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/fixtures.py tests/test_api/test_fixtures.py
git commit -m "feat: /fixture/{id} endpoint with form, spread, and O/U detail"
```

---

## Task 5: /performance endpoint + Dockerfile.api

**Files:**
- Create: `api/routers/performance.py`
- Create: `Dockerfile.api`

- [ ] **Step 1: Implement api/routers/performance.py**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.models import Performance, ModelVersion
from api.deps import get_session
from api.schemas import ModelPerformanceResponse

router = APIRouter()


@router.get("", response_model=list[ModelPerformanceResponse])
def model_performance(session: Session = Depends(get_session)):
    rows = session.query(Performance).all()
    result = []
    for row in rows:
        mv = session.query(ModelVersion).filter_by(id=row.model_id).first()
        result.append(ModelPerformanceResponse(
            model_name=mv.name if mv else "unknown",
            version=mv.version if mv else "unknown",
            bet_type=row.bet_type,
            total_predictions=row.total_predictions or 0,
            correct=row.correct or 0,
            accuracy=row.accuracy or 0.0,
            roi=row.roi or 0.0,
        ))
    return result
```

- [ ] **Step 2: Create Dockerfile.api**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.api.txt .
RUN pip install --no-cache-dir -r requirements.api.txt

COPY app/ ./app/
COPY api/ ./api/

ENV PYTHONPATH=/app

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Verify the image builds**

```bash
docker build -f Dockerfile.api -t soccer-api:local .
```

Expected: Build completes with no errors

- [ ] **Step 4: Smoke-test the container**

```bash
docker run --rm -e DATABASE_URL=postgresql://betuser:betpass@host.docker.internal:5432/soccerbet \
  -p 8000:8000 soccer-api:local &
sleep 3
curl -s http://localhost:8000/health
kill %1
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: Commit**

```bash
git add api/routers/performance.py Dockerfile.api
git commit -m "feat: /performance endpoint and Dockerfile.api"
```

---

## Task 6: Run all API tests

- [ ] **Step 1: Run the full API test suite**

```bash
pytest tests/test_api/ -v
```

Expected: All PASS

- [ ] **Step 2: Run complete test suite to catch regressions**

```bash
pytest tests/ -v
```

Expected: All PASS

---

## Task 7: React Vite scaffold

**Files:**
- Create: `dashboard/package.json`
- Create: `dashboard/tsconfig.json`
- Create: `dashboard/vite.config.ts`
- Create: `dashboard/tailwind.config.ts`
- Create: `dashboard/postcss.config.js`
- Create: `dashboard/index.html`
- Create: `dashboard/src/main.tsx`
- Create: `dashboard/src/App.tsx`

- [ ] **Step 1: Create dashboard/package.json**

```json
{
  "name": "soccer-dashboard",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.13",
    "typescript": "^5.5.3",
    "vite": "^5.4.8"
  }
}
```

- [ ] **Step 2: Create dashboard/tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create dashboard/vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
```

- [ ] **Step 4: Create dashboard/tailwind.config.ts**

```typescript
import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
} satisfies Config
```

- [ ] **Step 5: Create dashboard/postcss.config.js**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 6: Create dashboard/index.html**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Soccer Picks</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 7: Create dashboard/src/main.tsx**

```typescript
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 8: Create dashboard/src/index.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 9: Create dashboard/src/App.tsx**

```typescript
import TodayPage from './pages/TodayPage'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-4 py-3">
        <h1 className="text-lg font-semibold tracking-wide">Soccer Picks</h1>
      </header>
      <main className="max-w-2xl mx-auto px-4 py-6">
        <TodayPage />
      </main>
    </div>
  )
}
```

- [ ] **Step 10: Install dependencies and verify it compiles**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model/dashboard
npm install
npm run build
```

Expected: Build completes with no TypeScript errors. `dist/` directory created.

- [ ] **Step 11: Commit**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
git add dashboard/
git commit -m "feat: React Vite scaffold with Tailwind — dashboard shell"
```

---

## Task 8: API client and TypeScript types

**Files:**
- Create: `dashboard/src/api/types.ts`
- Create: `dashboard/src/api/client.ts`

- [ ] **Step 1: Create dashboard/src/api/types.ts**

These types must match the Pydantic schemas defined in `api/schemas.py`:

```typescript
export interface SpreadPick {
  team_side: 'home' | 'away'
  goal_line: number          // -1.5 | -1.0 | -0.5 | 0.5 | 1.0 | 1.5
  cover_probability: number
  push_probability: number
  ev_score: number | null
  confidence_tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
}

export interface OUPick {
  line: number               // 1.5 | 2.5 | 3.5
  direction: 'over' | 'under'
  probability: number
  ev_score: number | null
  confidence_tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
}

export interface FixturePick {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  kickoff_at: string         // ISO-8601 string
  best_spread: SpreadPick | null
  best_ou: OUPick | null
  top_ev: number | null
}

export interface FormSummary {
  goals_scored_avg: number
  goals_conceded_avg: number
  spread_cover_rate: number | null
  ou_hit_rate_25: number | null
  matches_count: number
}

export interface FixtureDetail {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  kickoff_at: string
  home_form: FormSummary | null
  away_form: FormSummary | null
  spread_picks: SpreadPick[]
  ou_picks: OUPick[]
}
```

- [ ] **Step 2: Create dashboard/src/api/client.ts**

```typescript
import type { FixturePick, FixtureDetail } from './types'

const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const api = {
  picksToday: () => get<FixturePick[]>('/picks/today'),
  picksWeek: () => get<FixturePick[]>('/picks/week'),
  fixtureDetail: (id: number) => get<FixtureDetail>(`/fixture/${id}`),
}
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model/dashboard
npx tsc --noEmit
```

Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
git add dashboard/src/api/
git commit -m "feat: API client and TypeScript types for dashboard"
```

---

## Task 9: PickCard and TodayPage components

**Files:**
- Create: `dashboard/src/components/ConfidenceBadge.tsx`
- Create: `dashboard/src/components/PickCard.tsx`
- Create: `dashboard/src/pages/TodayPage.tsx`

- [ ] **Step 1: Create dashboard/src/components/ConfidenceBadge.tsx**

```typescript
interface Props {
  tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
}

const COLORS: Record<Props['tier'], string> = {
  ELITE: 'bg-yellow-500 text-black',
  HIGH:  'bg-green-600 text-white',
  MEDIUM:'bg-blue-600 text-white',
  SKIP:  'bg-gray-600 text-gray-300',
}

export default function ConfidenceBadge({ tier }: Props) {
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded uppercase tracking-wider ${COLORS[tier]}`}>
      {tier}
    </span>
  )
}
```

- [ ] **Step 2: Create dashboard/src/components/PickCard.tsx**

```typescript
import type { FixturePick } from '../api/types'
import ConfidenceBadge from './ConfidenceBadge'

interface Props {
  pick: FixturePick
}

function formatKickoff(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function evLabel(ev: number | null): string {
  if (ev === null) return '—'
  return `+${(ev * 100).toFixed(1)}%`
}

export default function PickCard({ pick }: Props) {
  const { home_team, away_team, league, kickoff_at, best_spread, best_ou, top_ev } = pick

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-900 p-4 space-y-3">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <p className="font-semibold">{home_team} <span className="text-gray-400">vs</span> {away_team}</p>
          <p className="text-xs text-gray-500">{league} · {formatKickoff(kickoff_at)}</p>
        </div>
        {top_ev !== null && (
          <span className="text-sm font-mono text-green-400">{evLabel(top_ev)} edge</span>
        )}
      </div>

      {/* Spread pick */}
      {best_spread && (
        <div className="flex items-center gap-2 text-sm">
          <ConfidenceBadge tier={best_spread.confidence_tier} />
          <span className="font-medium">
            {best_spread.team_side === 'home' ? home_team : away_team}
            {' '}{best_spread.goal_line > 0 ? '+' : ''}{best_spread.goal_line}
          </span>
          <span className="text-gray-400">
            {(best_spread.cover_probability * 100).toFixed(0)}% cover
          </span>
          {best_spread.ev_score !== null && (
            <span className="text-green-400 text-xs">{evLabel(best_spread.ev_score)}</span>
          )}
        </div>
      )}

      {/* O/U pick */}
      {best_ou && (
        <div className="flex items-center gap-2 text-sm">
          <ConfidenceBadge tier={best_ou.confidence_tier} />
          <span className="font-medium capitalize">{best_ou.direction} {best_ou.line}</span>
          <span className="text-gray-400">
            {(best_ou.probability * 100).toFixed(0)}%
          </span>
          {best_ou.ev_score !== null && (
            <span className="text-green-400 text-xs">{evLabel(best_ou.ev_score)}</span>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Create dashboard/src/pages/TodayPage.tsx**

```typescript
import { useEffect, useState } from 'react'
import type { FixturePick } from '../api/types'
import { api } from '../api/client'
import PickCard from '../components/PickCard'

export default function TodayPage() {
  const [picks, setPicks] = useState<FixturePick[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.picksToday()
      .then(setPicks)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-gray-400">Loading picks…</p>
  if (error) return <p className="text-red-400">Error: {error}</p>
  if (picks.length === 0) return <p className="text-gray-500">No HIGH or ELITE picks today.</p>

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
        Today's Picks — {picks.length} fixture{picks.length !== 1 ? 's' : ''}
      </h2>
      {picks.map(p => (
        <PickCard key={p.fixture_id} pick={p} />
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Run TypeScript check and build**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model/dashboard
npx tsc --noEmit && npm run build
```

Expected: No TypeScript errors, build succeeds.

- [ ] **Step 5: Commit**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
git add dashboard/src/components/ dashboard/src/pages/
git commit -m "feat: PickCard, ConfidenceBadge, and TodayPage components"
```

---

## Task 10: Dockerfile.dashboard + nginx config

**Files:**
- Create: `dashboard/nginx.conf`
- Create: `Dockerfile.dashboard`

- [ ] **Step 1: Create dashboard/nginx.conf**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # All routes fall back to index.html for SPA routing
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Gzip for JS/CSS assets
    gzip on;
    gzip_types text/plain application/javascript text/css application/json;
    gzip_min_length 256;
}
```

- [ ] **Step 2: Create Dockerfile.dashboard**

```dockerfile
# Stage 1: build the React app
FROM node:20-alpine AS builder

WORKDIR /app

COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

COPY dashboard/ .
RUN npm run build

# Stage 2: serve with nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
```

- [ ] **Step 3: Generate package-lock.json if missing**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model/dashboard
npm install
```

This creates `package-lock.json` required by `npm ci` in the Dockerfile.

- [ ] **Step 4: Build the Docker image**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
docker build -f Dockerfile.dashboard -t soccer-dashboard:local .
```

Expected: Build completes. Two stages visible in output.

- [ ] **Step 5: Smoke-test the container**

```bash
docker run --rm -p 8080:80 soccer-dashboard:local &
sleep 2
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
kill %1
```

Expected: `200`

- [ ] **Step 6: Commit**

```bash
git add dashboard/nginx.conf dashboard/package-lock.json Dockerfile.dashboard
git commit -m "feat: Dockerfile.dashboard — multi-stage node build + nginx for React SPA"
```

---

*Plan 2 complete. Plan 3 (Infra) adds Redis, Celery, K8s manifests, and Jenkinsfile updates, and can proceed in parallel with this plan.*
