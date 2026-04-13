# Phase 2 — Data Sources & Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Understat + FBref xG scrapers, API-Football lineups/referee client, OpenWeatherMap weather client, and the TimescaleDB line_movement hypertable. These data sources feed the Phase 2 Dixon-Coles model and ML pipeline. All new data collectors are Celery tasks (rate-limited, I/O-bound).

**Architecture:** New scrapers in `app/collector/`. New API clients in `app/collector/`. Line movement polling task in `app/celery_app.py`. All write to PostgreSQL via SQLAlchemy. TimescaleDB migration via Alembic raw SQL.

**Tech Stack:** Python 3.12, httpx, BeautifulSoup4, SQLAlchemy 2.x, Alembic. No proxy needed initially.

**Must complete before:** Phase 2 Dixon-Coles & Simulation plan.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `migrations/versions/<hash>_phase2_schema.py` | New tables: line_movement, player_impact, draw_propensity, manager_profiles, referee_profiles, tactical_profiles, stadium_profiles, rotation_flags |
| Modify | `app/db/models.py` | Add new Phase 2 ORM models |
| Create | `app/collector/understat.py` | Understat scraper — xG per team per match, PPDA |
| Create | `app/collector/fbref.py` | FBref scraper — UCL xG, PSxG |
| Create | `app/collector/api_football.py` | API-Football client — lineups, referee, red card events |
| Create | `app/collector/weather.py` | OpenWeatherMap client — match day weather |
| Modify | `app/collector/collector.py` | Wire new collectors into collection cycle |
| Modify | `app/form_cache.py` | Populate xg_scored_avg, xg_conceded_avg from Understat data |
| Modify | `app/celery_app.py` | Add line_movement_poll_task, understat_collect_task, fbref_collect_task |
| Modify | `app/scheduler.py` | Schedule new Celery tasks |
| Modify | `app/config.py` | Add api_football_key, openweathermap_key settings |
| Create | `tests/test_collector/test_understat.py` | Unit tests — mocked HTTP responses |
| Create | `tests/test_collector/test_fbref.py` | Unit tests — mocked HTTP responses |
| Create | `tests/test_collector/test_api_football.py` | Unit tests — mocked API responses |
| Create | `tests/test_collector/test_weather.py` | Unit tests — mocked API responses |
| Create | `data/stadium_profiles.json` | Static seed data — enclosure ratings per stadium |
| Create | `scripts/seed_stadiums.py` | One-time seed script for stadium_profiles table |

---

## Task 1: Phase 2 schema — new tables + TimescaleDB line_movement

**Files:**
- Modify: `app/db/models.py`
- Create: `migrations/versions/<hash>_phase2_schema.py`

### Step 1: Write tests for new models

Create `tests/test_phase2_models.py`:

```python
from app.db.models import (
    LineMovement, PlayerImpact, DrawPropensity,
    ManagerProfile, RefereeProfile, TacticalProfile,
    StadiumProfile, RotationFlag
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.models import Base
import pytest

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s

def test_line_movement_columns(session):
    from datetime import datetime
    lm = LineMovement(
        fixture_id=1, book="pinnacle", market="spread",
        line=-0.5, odds=-110, recorded_at=datetime.utcnow()
    )
    session.add(lm)
    session.commit()
    assert session.query(LineMovement).count() == 1

def test_referee_profile_columns(session):
    rp = RefereeProfile(name="Mike Dean", league="eng.1",
                        fouls_per_tackle=0.42, penalty_rate=0.08, cards_per_game=3.1)
    session.add(rp)
    session.commit()
    assert rp.id is not None

def test_stadium_profile_enclosure(session):
    sp = StadiumProfile(name="Tottenham Hotspur Stadium",
                        team_id=None, enclosure_rating="Closed",
                        latitude=51.604, longitude=-0.066)
    session.add(sp)
    session.commit()
    assert sp.enclosure_rating == "Closed"

def test_tactical_profile_ppda(session):
    tp = TacticalProfile(team_id=1, season="2025-26",
                         archetype="High Press", ppda=8.3, press_resistance=62.1)
    session.add(tp)
    session.commit()
    assert tp.ppda == pytest.approx(8.3)

def test_rotation_flag_columns(session):
    rf = RotationFlag(fixture_id=1, team_id=1,
                      rotation_probability=0.72, ucl_fixture_id=99)
    session.add(rf)
    session.commit()
    assert rf.rotation_probability == pytest.approx(0.72)
```

Run and verify FAIL:
```bash
cd /Users/fred/.claude/projects/soccer-betting-model
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest tests/test_phase2_models.py -v
```
Expected: ImportError — models don't exist yet.

### Step 2: Add ORM models to `app/db/models.py`

Append after the `OUAnalysis` class:

```python
class LineMovement(Base):
    """Odds snapshots every 30min per tracked fixture — TimescaleDB hypertable."""
    __tablename__ = "line_movement"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    book = Column(String, nullable=False)           # e.g. "pinnacle", "draftkings"
    market = Column(String, nullable=False)         # "spread" | "ou"
    line = Column(Float, nullable=False)            # spread goal-line or O/U total
    odds = Column(Integer)                          # American odds
    recorded_at = Column(DateTime, nullable=False)


class PlayerImpact(Base):
    __tablename__ = "player_impact"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    player_name = Column(String, nullable=False)
    xg_contribution_pct = Column(Float)            # % of team's season xG
    is_absent = Column(Boolean, default=False)
    is_gk = Column(Boolean, default=False)
    psxg_plus_minus = Column(Float)               # GK overperformance vs expected
    source = Column(String)                        # "api_football" | "fbref"
    updated_at = Column(DateTime)


class DrawPropensity(Base):
    __tablename__ = "draw_propensity"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False, unique=True)
    score = Column(Float)                          # 0.0 to 1.0
    manager_draw_tendency = Column(Float)
    table_utility = Column(Float)
    motivation_asymmetry = Column(Float)
    defensive_trend = Column(Float)
    ucl_aggregate_context = Column(Float)
    updated_at = Column(DateTime)


class ManagerProfile(Base):
    __tablename__ = "manager_profiles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"))
    tenure_games = Column(Integer, default=0)
    draw_tendency_underdog = Column(Float)         # draw % as underdog vs top-6 away
    tactical_archetype = Column(String)            # "High Press" | "Low Block" | etc.
    updated_at = Column(DateTime)


class RefereeProfile(Base):
    __tablename__ = "referee_profiles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    league = Column(String)
    fouls_per_tackle = Column(Float)
    penalty_rate = Column(Float)                   # penalties awarded per game
    cards_per_game = Column(Float)
    updated_at = Column(DateTime)


class TacticalProfile(Base):
    __tablename__ = "tactical_profiles"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    season = Column(String, nullable=False)        # e.g. "2025-26"
    archetype = Column(String)                     # "High Press" | "Low Block" | "Counter-Attack" | "Possession"
    ppda = Column(Float)                           # Passes Allowed Per Defensive Action (from Understat)
    press_resistance = Column(Float)               # dribble success rate vs high press
    set_piece_pct_scored = Column(Float)           # % of goals from set pieces
    aerial_win_rate = Column(Float)
    updated_at = Column(DateTime)


class StadiumProfile(Base):
    __tablename__ = "stadium_profiles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"))
    enclosure_rating = Column(String, nullable=False)  # "Open" | "Semi-Enclosed" | "Closed"
    latitude = Column(Float)
    longitude = Column(Float)


class RotationFlag(Base):
    __tablename__ = "rotation_flags"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    rotation_probability = Column(Float)           # 0.0 to 1.0
    ucl_fixture_id = Column(Integer, ForeignKey("fixtures.id"))
    hours_between = Column(Float)                  # hours between fixtures
    overridden_by_lineup = Column(Boolean, default=False)
    updated_at = Column(DateTime)
```

### Step 3: Generate migration

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m alembic revision --autogenerate -m "phase2_schema"
```

Open the generated migration file. After the `op.create_table("line_movement", ...)` call, add the TimescaleDB hypertable conversion wrapped in a try/except (no-op on SQLite in tests):

```python
# TimescaleDB hypertable for line_movement (PostgreSQL only)
try:
    op.execute(
        "SELECT create_hypertable('line_movement', 'recorded_at', if_not_exists => TRUE)"
    )
    op.execute(
        "ALTER TABLE line_movement SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'fixture_id,book,market')"
    )
    op.execute(
        "SELECT add_compression_policy('line_movement', INTERVAL '30 days')"
    )
except Exception:
    pass  # SQLite / TimescaleDB not installed
```

### Step 4: Run tests — verify PASS

```bash
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest tests/test_phase2_models.py -v
```

Expected: All PASS.

### Step 5: Commit

```bash
git add app/db/models.py migrations/ tests/test_phase2_models.py
git commit -m "feat: add Phase 2 database schema — line_movement hypertable + 7 new tables"
```

---

## Task 2: Understat scraper — xG per team per match

**Files:**
- Create: `app/collector/understat.py`
- Create: `tests/test_collector/test_understat.py`

Understat embeds JSON in JavaScript variables inside `<script>` tags. The pattern is:
`var datesData = JSON.parse('...')` — we extract with regex, no heavy HTML parsing needed.

### Step 1: Write failing tests

Create `tests/test_collector/test_understat.py`:

```python
import json
import pytest
import responses as rsps_lib
import responses
from app.collector.understat import UnderstatClient, LEAGUE_UNDERSTAT_KEYS

def make_html(data: dict) -> str:
    encoded = json.dumps(data).replace("'", "\\'")
    return f"<html><script>var datesData = JSON.parse('{encoded}')</script></html>"

@responses.activate
def test_fetch_league_matches_returns_list():
    sample = [
        {"id": "1", "h": {"id": "11", "title": "Arsenal", "xG": "1.42"},
         "a": {"id": "22", "title": "Chelsea", "xG": "0.87"},
         "datetime": "2025-12-01 15:00:00", "goals": {"h": "2", "a": "1"}}
    ]
    responses.add(responses.GET, "https://understat.com/league/EPL/2025",
                  body=make_html(sample), status=200)
    client = UnderstatClient()
    matches = client.fetch_league_matches("EPL", 2025)
    assert len(matches) == 1
    assert matches[0]["h"]["title"] == "Arsenal"
    assert float(matches[0]["h"]["xG"]) == pytest.approx(1.42)

def test_league_keys_cover_all_five():
    assert set(LEAGUE_UNDERSTAT_KEYS.keys()) == {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}
    assert LEAGUE_UNDERSTAT_KEYS["eng.1"] == "EPL"

@responses.activate
def test_fetch_team_ppda():
    # PPDA comes from team page shot stats embedded JSON
    team_data = {"ppda": {"att": 456, "def": 55}}  # ppda = att/def = 8.29
    encoded = json.dumps(team_data).replace("'", "\\'")
    html = f"<html><script>var teamData = JSON.parse('{encoded}')</script></html>"
    responses.add(responses.GET, "https://understat.com/team/Arsenal/2025",
                  body=html, status=200)
    client = UnderstatClient()
    ppda = client.fetch_team_ppda("Arsenal", 2025)
    assert ppda == pytest.approx(456 / 55, rel=0.01)

@responses.activate
def test_rate_limit_respected(monkeypatch):
    import time
    calls = []
    monkeypatch.setattr(time, "sleep", lambda s: calls.append(s))
    sample = []
    responses.add(responses.GET, "https://understat.com/league/EPL/2025",
                  body=make_html(sample), status=200)
    responses.add(responses.GET, "https://understat.com/league/La_liga/2025",
                  body=make_html(sample), status=200)
    client = UnderstatClient()
    client.fetch_league_matches("EPL", 2025)
    client.fetch_league_matches("La_liga", 2025)
    assert len(calls) >= 1  # sleep called between requests
    assert all(s >= 2.0 for s in calls)
```

Run and verify FAIL:
```bash
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest tests/test_collector/test_understat.py -v
```
Expected: ImportError — module doesn't exist yet.

### Step 2: Implement `app/collector/understat.py`

```python
import json
import re
import time
import httpx

LEAGUE_UNDERSTAT_KEYS: dict[str, str] = {
    "eng.1": "EPL",
    "esp.1": "La_liga",
    "ger.1": "Bundesliga",
    "ita.1": "Serie_A",
    "fra.1": "Ligue_1",
}

_DATES_PATTERN = re.compile(r"var datesData\s*=\s*JSON\.parse\('(.+?)'\)", re.DOTALL)
_TEAM_PATTERN = re.compile(r"var teamData\s*=\s*JSON\.parse\('(.+?)'\)", re.DOTALL)
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36",
]
_DELAY_SECONDS = 2.5


class UnderstatClient:
    def __init__(self):
        self._agent_idx = 0
        self._last_request = 0.0

    def _get(self, url: str) -> str:
        elapsed = time.time() - self._last_request
        if elapsed < _DELAY_SECONDS:
            time.sleep(_DELAY_SECONDS - elapsed)
        headers = {"User-Agent": _USER_AGENTS[self._agent_idx % len(_USER_AGENTS)]}
        self._agent_idx += 1
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        self._last_request = time.time()
        return resp.text

    def fetch_league_matches(self, understat_key: str, season: int) -> list[dict]:
        url = f"https://understat.com/league/{understat_key}/{season}"
        html = self._get(url)
        m = _DATES_PATTERN.search(html)
        if not m:
            return []
        raw = m.group(1).encode().decode("unicode_escape")
        return json.loads(raw)

    def fetch_team_ppda(self, team_name: str, season: int) -> float | None:
        url = f"https://understat.com/team/{team_name}/{season}"
        html = self._get(url)
        m = _TEAM_PATTERN.search(html)
        if not m:
            return None
        raw = m.group(1).encode().decode("unicode_escape")
        data = json.loads(raw)
        ppda = data.get("ppda")
        if not ppda:
            return None
        att, def_ = ppda.get("att"), ppda.get("def")
        if not att or not def_:
            return None
        return att / def_
```

### Step 3: Run tests — verify PASS

```bash
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest tests/test_collector/test_understat.py -v
```

### Step 4: Wire xG into FormCacheBuilder

In `app/form_cache.py`, update `_build_team_form` to populate `xg_scored_avg` and `xg_conceded_avg` when Understat data is available. Add a new method:

```python
def populate_xg_from_understat(self, understat_matches: list[dict], team_name: str, team_id: int, is_home: bool) -> None:
    """Update form_cache xG fields from a list of Understat match dicts."""
    side = "h" if is_home else "a"
    opp = "a" if is_home else "h"
    xg_scored = [float(m[side]["xG"]) for m in understat_matches if m[side]["title"] == team_name]
    xg_conceded = [float(m[opp]["xG"]) for m in understat_matches if m[side]["title"] == team_name]
    if not xg_scored:
        return
    lookback = xg_scored[-self.lookback:]
    lookback_c = xg_conceded[-self.lookback:]
    cache = (self.session.query(FormCache)
             .filter_by(team_id=team_id, is_home=is_home).first())
    if cache:
        cache.xg_scored_avg = sum(lookback) / len(lookback)
        cache.xg_conceded_avg = sum(lookback_c) / len(lookback_c)
        self.session.commit()
```

### Step 5: Commit

```bash
git add app/collector/understat.py app/form_cache.py tests/test_collector/test_understat.py
git commit -m "feat: add Understat scraper for xG data with rate limiting"
```

---

## Task 3: FBref scraper — UCL xG and PSxG

**Files:**
- Create: `app/collector/fbref.py`
- Create: `tests/test_collector/test_fbref.py`

FBref serves data in HTML tables. We parse with BeautifulSoup4. UCL focus only (domestic leagues use Understat).

### Step 1: Write failing tests

Create `tests/test_collector/test_fbref.py`:

```python
import responses
from app.collector.fbref import FBrefClient

UCL_FIXTURES_URL = "https://fbref.com/en/comps/8/schedule/Champions-League-Scores-and-Fixtures"

def _make_table_html(rows: list[dict]) -> str:
    header = "<tr><th>Date</th><th>Home</th><th>xG</th><th>Away</th><th>xG.1</th></tr>"
    body = ""
    for r in rows:
        body += f"<tr><td>{r['date']}</td><td>{r['home']}</td><td>{r['home_xg']}</td><td>{r['away']}</td><td>{r['away_xg']}</td></tr>"
    return f"<html><body><table id='sched_all'>{header}{body}</table></body></html>"

@responses.activate
def test_fetch_ucl_fixtures():
    html = _make_table_html([
        {"date": "2025-11-05", "home": "Arsenal", "home_xg": "2.10",
         "away": "PSG", "away_xg": "0.87"}
    ])
    responses.add(responses.GET, UCL_FIXTURES_URL, body=html, status=200)
    client = FBrefClient()
    fixtures = client.fetch_ucl_fixtures(season=2025)
    assert len(fixtures) == 1
    assert fixtures[0]["home"] == "Arsenal"
    assert fixtures[0]["home_xg"] == pytest.approx(2.10)

@responses.activate
def test_fetch_ucl_fixtures_skips_rows_without_xg():
    html = _make_table_html([
        {"date": "2025-11-05", "home": "Arsenal", "home_xg": "",
         "away": "PSG", "away_xg": ""},  # future fixture, no xG yet
    ])
    responses.add(responses.GET, UCL_FIXTURES_URL, body=html, status=200)
    client = FBrefClient()
    fixtures = client.fetch_ucl_fixtures(season=2025)
    assert len(fixtures) == 0  # empty xG rows skipped

import pytest
```

Run and verify FAIL.

### Step 2: Implement `app/collector/fbref.py`

```python
import time
import httpx
from bs4 import BeautifulSoup

_DELAY_SECONDS = 3.0
_UCL_SCHEDULE_URL = (
    "https://fbref.com/en/comps/8/schedule/Champions-League-Scores-and-Fixtures"
)
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"


class FBrefClient:
    def __init__(self):
        self._last_request = 0.0

    def _get(self, url: str) -> str:
        elapsed = time.time() - self._last_request
        if elapsed < _DELAY_SECONDS:
            time.sleep(_DELAY_SECONDS - elapsed)
        resp = httpx.get(url, headers={"User-Agent": _USER_AGENT},
                         timeout=30, follow_redirects=True)
        resp.raise_for_status()
        self._last_request = time.time()
        return resp.text

    def fetch_ucl_fixtures(self, season: int) -> list[dict]:
        html = self._get(_UCL_SCHEDULE_URL)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="sched_all")
        if not table:
            return []
        results = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            date_str = cells[0].get_text(strip=True)
            home = cells[1].get_text(strip=True)
            home_xg_str = cells[2].get_text(strip=True)
            away = cells[3].get_text(strip=True)
            away_xg_str = cells[4].get_text(strip=True)
            if not home_xg_str or not away_xg_str:
                continue
            try:
                results.append({
                    "date": date_str,
                    "home": home,
                    "home_xg": float(home_xg_str),
                    "away": away,
                    "away_xg": float(away_xg_str),
                })
            except ValueError:
                continue
        return results
```

Install BeautifulSoup4 if not present:
```bash
/opt/homebrew/opt/python/bin/python3.14 -m pip install beautifulsoup4 --target=venv/lib/python3.14/site-packages
```

### Step 3: Run tests — verify PASS

```bash
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest tests/test_collector/test_fbref.py -v
```

### Step 4: Commit

```bash
git add app/collector/fbref.py tests/test_collector/test_fbref.py
git commit -m "feat: add FBref scraper for UCL xG and PSxG data"
```

---

## Task 4: API-Football client — lineups, referee, red card events

**Files:**
- Create: `app/collector/api_football.py`
- Create: `tests/test_collector/test_api_football.py`
- Modify: `app/config.py`

API-Football (api-football.com) provides confirmed lineups ~1hr pre-kickoff, referee assignments, and in-match events (red cards with minute).

### Step 1: Add config setting

In `app/config.py`, add:
```python
api_football_key: str = ""
```

### Step 2: Write failing tests

Create `tests/test_collector/test_api_football.py`:

```python
import responses
import pytest
from app.collector.api_football import APIFootballClient

BASE = "https://v3.football.api-sports.io"

@responses.activate
def test_fetch_lineup_returns_players():
    responses.add(responses.GET, f"{BASE}/fixtures/lineups",
        json={"response": [
            {"team": {"id": 42, "name": "Arsenal"},
             "startXI": [{"player": {"id": 1, "name": "Raya", "pos": "G"}}],
             "coach": {"id": 9, "name": "Arteta"}}
        ]}, status=200)
    client = APIFootballClient(api_key="test-key")
    lineups = client.fetch_lineups(fixture_id=123)
    assert len(lineups) == 1
    assert lineups[0]["team"]["name"] == "Arsenal"
    assert len(lineups[0]["startXI"]) == 1

@responses.activate
def test_fetch_fixture_events_returns_red_cards():
    responses.add(responses.GET, f"{BASE}/fixtures/events",
        json={"response": [
            {"time": {"elapsed": 35}, "type": "Card",
             "detail": "Red Card", "team": {"id": 42}},
            {"time": {"elapsed": 70}, "type": "Goal",
             "detail": "Normal Goal", "team": {"id": 42}},
        ]}, status=200)
    client = APIFootballClient(api_key="test-key")
    events = client.fetch_red_card_events(fixture_id=123)
    assert len(events) == 1
    assert events[0]["time"]["elapsed"] == 35

@responses.activate
def test_fetch_referee_info():
    responses.add(responses.GET, f"{BASE}/fixtures",
        json={"response": [
            {"fixture": {"id": 123, "referee": "Mike Dean"}}
        ]}, status=200)
    client = APIFootballClient(api_key="test-key")
    referee = client.fetch_referee(fixture_id=123)
    assert referee == "Mike Dean"

def test_missing_api_key_raises():
    client = APIFootballClient(api_key="")
    with pytest.raises(ValueError, match="api_football_key"):
        client.fetch_lineups(fixture_id=1)
```

Run and verify FAIL.

### Step 3: Implement `app/collector/api_football.py`

```python
import httpx

_BASE = "https://v3.football.api-sports.io"


class APIFootballClient:
    def __init__(self, api_key: str):
        self._key = api_key

    def _headers(self) -> dict:
        if not self._key:
            raise ValueError("api_football_key is not configured")
        return {"x-apisports-key": self._key}

    def _get(self, path: str, params: dict) -> list:
        resp = httpx.get(f"{_BASE}/{path}", headers=self._headers(),
                         params=params, timeout=20)
        resp.raise_for_status()
        return resp.json().get("response", [])

    def fetch_lineups(self, fixture_id: int) -> list[dict]:
        return self._get("fixtures/lineups", {"fixture": fixture_id})

    def fetch_red_card_events(self, fixture_id: int) -> list[dict]:
        events = self._get("fixtures/events", {"fixture": fixture_id})
        return [e for e in events
                if e.get("type") == "Card" and e.get("detail") == "Red Card"]

    def fetch_referee(self, fixture_id: int) -> str | None:
        results = self._get("fixtures", {"id": fixture_id})
        if not results:
            return None
        return results[0].get("fixture", {}).get("referee")
```

### Step 4: Run tests — verify PASS

```bash
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest tests/test_collector/test_api_football.py -v
```

### Step 5: Commit

```bash
git add app/collector/api_football.py tests/test_collector/test_api_football.py app/config.py
git commit -m "feat: add API-Football client for lineups, referee, and red card events"
```

---

## Task 5: OpenWeatherMap client + stadium_profiles seed

**Files:**
- Create: `app/collector/weather.py`
- Create: `tests/test_collector/test_weather.py`
- Create: `data/stadium_profiles.json`
- Create: `scripts/seed_stadiums.py`
- Modify: `app/config.py`

### Step 1: Add config setting

In `app/config.py`, add:
```python
openweathermap_key: str = ""
```

### Step 2: Write failing tests

Create `tests/test_collector/test_weather.py`:

```python
import responses
import pytest
from app.collector.weather import WeatherClient, WindModifier

BASE = "https://api.openweathermap.org/data/2.5"

@responses.activate
def test_fetch_match_day_weather():
    responses.add(responses.GET, f"{BASE}/weather",
        json={"wind": {"speed": 9.2}, "rain": {}, "snow": {},
              "main": {"temp": 15.0},
              "weather": [{"description": "light rain"}]}, status=200)
    client = WeatherClient(api_key="test-key")
    w = client.fetch_current(lat=51.555, lon=-0.108)
    assert w["wind_speed"] == pytest.approx(9.2)
    assert w["temp_celsius"] == pytest.approx(15.0)

def test_wind_modifier_open_stadium():
    mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Open")
    assert mod < 1.0

def test_wind_modifier_closed_stadium():
    mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Closed")
    assert mod == pytest.approx(1.0)  # no modifier for enclosed

def test_wind_modifier_semi_enclosed():
    open_mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Open")
    semi_mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Semi-Enclosed")
    closed_mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Closed")
    assert closed_mod <= semi_mod <= open_mod

def test_missing_key_raises():
    client = WeatherClient(api_key="")
    with pytest.raises(ValueError):
        client.fetch_current(lat=51.0, lon=-0.1)
```

Run and verify FAIL.

### Step 3: Implement `app/collector/weather.py`

```python
import httpx

_BASE = "https://api.openweathermap.org/data/2.5"
_ENCLOSURE_WEIGHTS = {"Open": 1.0, "Semi-Enclosed": 0.5, "Closed": 0.0}
_WIND_THRESHOLD_MPS = 7.0   # ~25 km/h — material impact threshold


class WeatherClient:
    def __init__(self, api_key: str):
        self._key = api_key

    def fetch_current(self, lat: float, lon: float) -> dict:
        if not self._key:
            raise ValueError("openweathermap_key is not configured")
        resp = httpx.get(f"{_BASE}/weather",
                         params={"lat": lat, "lon": lon,
                                 "appid": self._key, "units": "metric"},
                         timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "wind_speed": data.get("wind", {}).get("speed", 0.0),
            "temp_celsius": data.get("main", {}).get("temp", 15.0),
            "has_rain": bool(data.get("rain")),
            "has_snow": bool(data.get("snow")),
            "description": data.get("weather", [{}])[0].get("description", ""),
        }


class WindModifier:
    @staticmethod
    def calculate(wind_speed_mps: float, enclosure: str) -> float:
        """Returns xG multiplier. 1.0 = no change. <1.0 = downward modifier."""
        enclosure_weight = _ENCLOSURE_WEIGHTS.get(enclosure, 1.0)
        if wind_speed_mps < _WIND_THRESHOLD_MPS or enclosure_weight == 0.0:
            return 1.0
        # Linear penalty: 0.01 per m/s above threshold, scaled by enclosure weight
        penalty = min(0.10, (wind_speed_mps - _WIND_THRESHOLD_MPS) * 0.01)
        return 1.0 - (penalty * enclosure_weight)
```

### Step 4: Create stadium profiles seed data

Create `data/stadium_profiles.json`:
```json
[
  {"name": "Emirates Stadium", "team": "Arsenal", "enclosure_rating": "Semi-Enclosed", "latitude": 51.5549, "longitude": -0.1084},
  {"name": "Stamford Bridge", "team": "Chelsea", "enclosure_rating": "Open", "latitude": 51.4816, "longitude": -0.1910},
  {"name": "Anfield", "team": "Liverpool", "enclosure_rating": "Semi-Enclosed", "latitude": 53.4308, "longitude": -2.9608},
  {"name": "Etihad Stadium", "team": "Manchester City", "enclosure_rating": "Semi-Enclosed", "latitude": 53.4831, "longitude": -2.2004},
  {"name": "Old Trafford", "team": "Manchester United", "enclosure_rating": "Open", "latitude": 53.4631, "longitude": -2.2913},
  {"name": "Tottenham Hotspur Stadium", "team": "Tottenham", "enclosure_rating": "Closed", "latitude": 51.6042, "longitude": -0.0665},
  {"name": "Camp Nou", "team": "Barcelona", "enclosure_rating": "Open", "latitude": 41.3809, "longitude": 2.1228},
  {"name": "Estadio Bernabéu", "team": "Real Madrid", "enclosure_rating": "Closed", "latitude": 40.4531, "longitude": -3.6883},
  {"name": "Allianz Arena", "team": "Bayern Munich", "enclosure_rating": "Closed", "latitude": 48.2188, "longitude": 11.6247},
  {"name": "Signal Iduna Park", "team": "Borussia Dortmund", "enclosure_rating": "Open", "latitude": 51.4926, "longitude": 7.4519},
  {"name": "San Siro", "team": "AC Milan", "enclosure_rating": "Open", "latitude": 45.4782, "longitude": 9.1239},
  {"name": "Stadio Olimpico", "team": "Roma", "enclosure_rating": "Open", "latitude": 41.9340, "longitude": 12.4547},
  {"name": "Parc des Princes", "team": "PSG", "enclosure_rating": "Semi-Enclosed", "latitude": 48.8414, "longitude": 2.2530}
]
```

Create `scripts/seed_stadiums.py`:
```python
"""One-time script to seed stadium_profiles from data/stadium_profiles.json."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from sqlalchemy.orm import Session
from app.db.connection import get_engine
from app.db.models import StadiumProfile, Team

def seed():
    data = json.loads((Path(__file__).parent.parent / "data" / "stadium_profiles.json").read_text())
    engine = get_engine()
    with Session(engine) as session:
        for item in data:
            existing = session.query(StadiumProfile).filter_by(name=item["name"]).first()
            if existing:
                continue
            team = session.query(Team).filter(
                Team.name.ilike(f"%{item['team']}%")
            ).first()
            sp = StadiumProfile(
                name=item["name"],
                team_id=team.id if team else None,
                enclosure_rating=item["enclosure_rating"],
                latitude=item["latitude"],
                longitude=item["longitude"],
            )
            session.add(sp)
        session.commit()
        print(f"Seeded {len(data)} stadium profiles")

if __name__ == "__main__":
    seed()
```

### Step 5: Run tests — verify PASS

```bash
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest tests/test_collector/test_weather.py -v
```

### Step 6: Commit

```bash
git add app/collector/weather.py tests/test_collector/test_weather.py \
        data/stadium_profiles.json scripts/seed_stadiums.py app/config.py
git commit -m "feat: add OpenWeatherMap client, wind modifier, and stadium profiles seed"
```

---

## Task 6: Wire line_movement polling into Celery + Scheduler

**Files:**
- Modify: `app/celery_app.py`
- Modify: `app/scheduler.py`

### Step 1: Add Celery tasks

In `app/celery_app.py`, add:

```python
@celery_app.task(name="collect_line_movement")
def collect_line_movement_task():
    """Poll current odds for all upcoming fixtures and write LineMovement rows."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session
    from app.db.connection import get_engine
    from app.db.models import Fixture, LineMovement
    from app.collector.odds_api import OddsAPIClient
    from app.config import settings

    engine = get_engine()
    client = OddsAPIClient(api_key=settings.odds_api_key)
    now = datetime.now(timezone.utc)
    window = now + timedelta(days=7)

    with Session(engine) as session:
        upcoming = (session.query(Fixture)
                    .filter(Fixture.kickoff_at >= now, Fixture.kickoff_at <= window)
                    .all())
        recorded = 0
        for fixture in upcoming:
            snapshots = client.fetch_odds_for_fixture(fixture.external_id)
            for snap in snapshots:
                for market in ("spreads", "totals"):
                    lines = snap.get(market, [])
                    for entry in lines:
                        lm = LineMovement(
                            fixture_id=fixture.id,
                            book=snap.get("bookmaker", "unknown"),
                            market="spread" if market == "spreads" else "ou",
                            line=entry.get("line", 0.0),
                            odds=entry.get("odds"),
                            recorded_at=datetime.now(timezone.utc),
                        )
                        session.add(lm)
                        recorded += 1
        session.commit()
        return {"recorded": recorded}
```

### Step 2: Add scheduler job

In `app/scheduler.py`, in `start_scheduler()`, add:
```python
scheduler.add_job(
    lambda: celery_app.send_task("collect_line_movement"),
    "interval", minutes=30, id="line_movement_poll",
    replace_existing=True
)
```

### Step 3: Commit

```bash
git add app/celery_app.py app/scheduler.py
git commit -m "feat: add Celery line_movement polling task every 30min"
```

---

## Task 7: Full test suite validation

Run all tests to verify no regressions:

```bash
PYTHONPATH=venv/lib/python3.14/site-packages /opt/homebrew/opt/python/bin/python3.14 -m pytest --tb=short -q
```

Expected: All existing tests PASS + new tests PASS. Fix any failures before proceeding to Phase 2 Dixon-Coles plan.

### Final commit if needed

```bash
git add -A
git commit -m "feat: complete Phase 2 data sources — Understat, FBref, API-Football, weather, line_movement polling"
```
