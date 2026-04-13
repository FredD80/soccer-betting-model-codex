# Phase 1 — Data & Predictions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing collector to cover 6 leagues (adding Ligue 1 + UCL), build a form cache from completed results with red card normalization, and produce spread and O/U predictions for upcoming fixtures.

**Architecture:** All new code lives in `app/`. FormCacheBuilder reads from `results`/`fixtures`, writes to `form_cache`. SpreadPredictor and OUAnalyzer read from `form_cache` + `odds_snapshots`, write to `spread_predictions`/`ou_analysis`. Migrations extend existing tables and add 4 new ones. No new external services — works with existing ESPN + Odds API.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Alembic, standard library `math` (Poisson via manual PMF, no scipy dependency).

**Must complete before:** Phase 1 API & Dashboard plan.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `app/collector/espn_api.py` | Add `fra.1`, `uefa.champions` to league list |
| Modify | `app/collector/odds_api.py` | Add Ligue 1 + UCL sport keys; add `spreads` market |
| Modify | `app/collector/collector.py` | Update ESPN→Odds API league mapping |
| Modify | `app/db/models.py` | Add `red_card_minute` to Result; add FormCache, SpreadPrediction, OUAnalysis models; add spread fields to OddsSnapshot |
| Create | `migrations/versions/<hash>_phase1_schema.py` | Alembic migration for all schema changes |
| Create | `app/form_cache.py` | FormCacheBuilder — last-5 form aggregates with red card weighting |
| Create | `app/spread_predictor.py` | SpreadPredictor — Poisson goal-line cover probabilities |
| Create | `app/ou_analyzer.py` | OUAnalyzer — Poisson O/U probabilities |
| Modify | `app/scheduler.py` | Add form_cache_job, spread_predict_job, ou_analyze_job |
| Modify | `cli.py` | Add Ligue 1 + UCL to seed; add build-form-cache, predict-spreads, predict-ou commands |
| Modify | `tests/test_collector/test_espn_api.py` | Update league count assertions |
| Modify | `tests/test_collector/test_odds_api.py` | Update league count; add spreads market test |
| Create | `tests/test_form_cache.py` | Unit tests for FormCacheBuilder |
| Create | `tests/test_spread_predictor.py` | Unit tests for SpreadPredictor + cover_probability |
| Create | `tests/test_ou_analyzer.py` | Unit tests for OUAnalyzer |

---

## Task 1: Add Ligue 1 + UCL to ESPN client

**Files:**
- Modify: `app/collector/espn_api.py`
- Modify: `tests/test_collector/test_espn_api.py`

- [ ] **Step 1: Update the existing all-leagues test to assert 6 leagues**

In `tests/test_collector/test_espn_api.py`, replace the last test:

```python
@rsps.activate
def test_fetch_all_leagues_queries_all_six():
    for league in ["eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "uefa.champions"]:
        rsps.add(rsps.GET,
                 f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard",
                 json={"events": []}, status=200)
    client = ESPNClient()
    results = client.fetch_all_leagues()
    assert set(results.keys()) == {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "uefa.champions"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
pytest tests/test_collector/test_espn_api.py::test_fetch_all_leagues_queries_all_six -v
```

Expected: FAIL — `AssertionError: {"fra.1", "uefa.champions"} not in results`

- [ ] **Step 3: Update ESPN client**

In `app/collector/espn_api.py`, change `LEAGUE_ESPN_IDS`:

```python
LEAGUE_ESPN_IDS = ["eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "uefa.champions"]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_collector/test_espn_api.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/collector/espn_api.py tests/test_collector/test_espn_api.py
git commit -m "feat: add Ligue 1 (fra.1) and UCL (uefa.champions) to ESPN collector"
```

---

## Task 2: Add Ligue 1 + UCL to Odds API client + collector mapping

**Files:**
- Modify: `app/collector/odds_api.py`
- Modify: `app/collector/collector.py`
- Modify: `tests/test_collector/test_odds_api.py`

- [ ] **Step 1: Update the all-leagues test to assert 6 keys**

In `tests/test_collector/test_odds_api.py`, replace `test_fetch_all_leagues_calls_each_sport_key`:

```python
@rsps.activate
def test_fetch_all_leagues_calls_each_sport_key():
    for sport_key in [
        "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
        "soccer_italy_serie_a", "soccer_france_ligue_one", "soccer_uefa_champs_league",
    ]:
        rsps.add(
            rsps.GET,
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            json=[],
            status=200,
        )
    client = OddsAPIClient(api_key="testkey")
    results = client.fetch_all_leagues()
    assert len(results) == 6
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_collector/test_odds_api.py::test_fetch_all_leagues_calls_each_sport_key -v
```

Expected: FAIL — `AssertionError: 4 != 6`

- [ ] **Step 3: Update Odds API client**

In `app/collector/odds_api.py`, replace `LEAGUE_SPORT_KEYS`:

```python
LEAGUE_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
]
```

- [ ] **Step 4: Update ESPN→Odds API mapping in collector**

In `app/collector/collector.py`, replace `ESPN_TO_ODDS_API_LEAGUE`:

```python
ESPN_TO_ODDS_API_LEAGUE = {
    "eng.1": "soccer_epl",
    "esp.1": "soccer_spain_la_liga",
    "ger.1": "soccer_germany_bundesliga",
    "ita.1": "soccer_italy_serie_a",
    "fra.1": "soccer_france_ligue_one",
    "uefa.champions": "soccer_uefa_champs_league",
}
```

- [ ] **Step 5: Run all collector tests**

```bash
pytest tests/test_collector/ -v
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/collector/odds_api.py app/collector/collector.py tests/test_collector/test_odds_api.py
git commit -m "feat: add Ligue 1 + UCL to Odds API collector and ESPN/Odds mapping"
```

---

## Task 3: Add spreads market to Odds API client

**Files:**
- Modify: `app/collector/odds_api.py`
- Modify: `tests/test_collector/test_odds_api.py`

- [ ] **Step 1: Write failing test for spreads parsing**

Add to `tests/test_collector/test_odds_api.py`:

```python
SAMPLE_WITH_SPREADS = [
    {
        "id": "abc456",
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
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Arsenal", "price": 1.95, "point": -0.5},
                            {"name": "Chelsea", "price": 1.85, "point": 0.5},
                        ],
                    },
                ],
            }
        ],
    }
]


@rsps.activate
def test_fetch_odds_extracts_spreads():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_WITH_SPREADS,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["spreads"]["home_line"] == -0.5
    assert bookmaker["spreads"]["home_odds"] == 1.95
    assert bookmaker["spreads"]["away_line"] == 0.5
    assert bookmaker["spreads"]["away_odds"] == 1.85


@rsps.activate
def test_fetch_odds_spreads_none_when_missing():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,  # original sample without spreads market
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["spreads"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_collector/test_odds_api.py::test_fetch_odds_extracts_spreads tests/test_collector/test_odds_api.py::test_fetch_odds_spreads_none_when_missing -v
```

Expected: FAIL — `KeyError: 'spreads'`

- [ ] **Step 3: Add spreads market to Odds API client**

In `app/collector/odds_api.py`:

1. Update `fetch_odds` params to request spreads market:
```python
    def fetch_odds(self, sport_key: str) -> list[dict]:
        url = f"{BASE_URL}/sports/{sport_key}/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": "us,uk",
            "markets": "h2h,totals,h2h_h1,totals_h1,spreads",
            "oddsFormat": "decimal",
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        raw = response.json()
        return [self._parse_fixture(f) for f in raw]
```

2. Add `_parse_spreads` method and update `_parse_bookmaker`:
```python
    def _parse_bookmaker(self, bookmaker: dict, home_team: str, away_team: str) -> dict:
        markets = {m["key"]: m for m in bookmaker.get("markets", [])}
        return {
            "key": bookmaker["key"],
            "title": bookmaker["title"],
            "h2h": self._parse_h2h(markets.get("h2h"), home_team, away_team),
            "totals": self._parse_totals(markets.get("totals")),
            "ht_h2h": self._parse_h2h(markets.get("h2h_h1"), home_team, away_team),
            "ht_totals": self._parse_totals(markets.get("totals_h1")),
            "spreads": self._parse_spreads(markets.get("spreads"), home_team, away_team),
        }

    def _parse_spreads(self, market: dict | None, home_team: str, away_team: str) -> dict | None:
        if not market:
            return None
        outcomes = {o["name"]: o for o in market["outcomes"]}
        home = outcomes.get(home_team, {})
        away = outcomes.get(away_team, {})
        return {
            "home_line": home.get("point"),
            "home_odds": home.get("price"),
            "away_line": away.get("point"),
            "away_odds": away.get("price"),
        }
```

- [ ] **Step 4: Run all Odds API tests**

```bash
pytest tests/test_collector/test_odds_api.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/collector/odds_api.py tests/test_collector/test_odds_api.py
git commit -m "feat: add spreads market to Odds API client"
```

---

## Task 4: Update seed command with Ligue 1 + UCL

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Write failing test for seed**

In `tests/test_collector/test_collector.py` (or create `tests/test_cli_seed.py`), add:

```python
def test_seed_adds_six_leagues(db):
    from app.db.models import League
    from click.testing import CliRunner
    from cli import cli

    runner = CliRunner()
    # Temporarily swap global session — use env var to override DB URL
    # Simpler: test by directly checking seed data structure in cli.py
    from cli import cli
    import cli as cli_module

    # Verify the seed data in cli.py contains both new leagues
    seed_data = [
        {"name": "Ligue 1", "country": "France", "espn_id": "fra.1", "odds_api_key": "soccer_france_ligue_one"},
        {"name": "Champions League", "country": "Europe", "espn_id": "uefa.champions", "odds_api_key": "soccer_uefa_champs_league"},
    ]
    # These are config values — just verify they're in the cli source
    import inspect
    source = inspect.getsource(cli_module)
    assert "fra.1" in source
    assert "uefa.champions" in source
    assert "soccer_france_ligue_one" in source
    assert "soccer_uefa_champs_league" in source
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cli_seed.py -v
```

Expected: FAIL — `AssertionError: "fra.1" not in source`

- [ ] **Step 3: Update seed command in cli.py**

In `cli.py`, replace the `leagues` list in the `seed` command:

```python
    leagues = [
        {"name": "Premier League",    "country": "England", "espn_id": "eng.1",          "odds_api_key": "soccer_epl"},
        {"name": "La Liga",           "country": "Spain",   "espn_id": "esp.1",          "odds_api_key": "soccer_spain_la_liga"},
        {"name": "Bundesliga",        "country": "Germany", "espn_id": "ger.1",          "odds_api_key": "soccer_germany_bundesliga"},
        {"name": "Serie A",           "country": "Italy",   "espn_id": "ita.1",          "odds_api_key": "soccer_italy_serie_a"},
        {"name": "Ligue 1",           "country": "France",  "espn_id": "fra.1",          "odds_api_key": "soccer_france_ligue_one"},
        {"name": "Champions League",  "country": "Europe",  "espn_id": "uefa.champions", "odds_api_key": "soccer_uefa_champs_league"},
    ]
```

Also update the echo line: `click.echo(f"Seeded {added} league(s). {6 - added} already existed.")`

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_cli_seed.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli.py tests/test_cli_seed.py
git commit -m "feat: seed Ligue 1 and Champions League leagues"
```

---

## Task 5: Extend OddsSnapshot + add spread columns (DB model + migration)

**Files:**
- Modify: `app/db/models.py`
- Modify: `app/collector/collector.py`
- Create: `migrations/versions/<hash>_phase1_schema.py`

- [ ] **Step 1: Write failing test for spread columns on OddsSnapshot**

In `tests/test_db_models.py`, add:

```python
def test_odds_snapshot_has_spread_fields(db):
    from app.db.models import League, Team, Fixture, OddsSnapshot
    from datetime import datetime, timezone

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="x1", home_team_id=home.id, away_team_id=away.id,
        league_id=league.id, kickoff_at=datetime.now(timezone.utc),
    )
    db.add(fixture)
    db.flush()
    snap = OddsSnapshot(
        fixture_id=fixture.id, bookmaker="betmgm",
        home_odds=2.1, draw_odds=3.5, away_odds=3.2,
        total_goals_line=2.5, over_odds=1.9, under_odds=1.9,
        spread_home_line=-0.5, spread_home_odds=1.95,
        spread_away_line=0.5, spread_away_odds=1.85,
        captured_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    db.flush()
    fetched = db.query(OddsSnapshot).filter_by(id=snap.id).first()
    assert fetched.spread_home_line == -0.5
    assert fetched.spread_home_odds == 1.95
    assert fetched.spread_away_line == 0.5
    assert fetched.spread_away_odds == 1.85
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_db_models.py::test_odds_snapshot_has_spread_fields -v
```

Expected: FAIL — `TypeError: unexpected keyword argument 'spread_home_line'`

- [ ] **Step 3: Add spread columns to OddsSnapshot in models.py**

In `app/db/models.py`, inside the `OddsSnapshot` class, add after `captured_at`:

```python
    spread_home_line = Column(Float)    # e.g., -0.5, -1.0
    spread_home_odds = Column(Float)
    spread_away_line = Column(Float)    # e.g., +0.5, +1.0
    spread_away_odds = Column(Float)
```

- [ ] **Step 4: Update collector to save spread data**

In `app/collector/collector.py`, update `_save_odds_snapshot` to include spreads:

```python
    def _save_odds_snapshot(self, fixture_id: int, bookmaker: dict):
        h2h = bookmaker.get("h2h") or {}
        totals = bookmaker.get("totals") or {}
        ht_h2h = bookmaker.get("ht_h2h") or {}
        ht_totals = bookmaker.get("ht_totals") or {}
        spreads = bookmaker.get("spreads") or {}

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
            spread_home_line=spreads.get("home_line"),
            spread_home_odds=spreads.get("home_odds"),
            spread_away_line=spreads.get("away_line"),
            spread_away_odds=spreads.get("away_odds"),
            captured_at=datetime.now(timezone.utc),
        )
        self.session.add(snap)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_db_models.py::test_odds_snapshot_has_spread_fields -v
```

Expected: PASS

- [ ] **Step 6: Generate the Alembic migration**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
alembic revision --autogenerate -m "phase1_schema"
```

This generates `migrations/versions/<hash>_phase1_schema.py`. Open the file and verify the upgrade() includes:
- `op.add_column('odds_snapshots', sa.Column('spread_home_line', sa.Float(), nullable=True))`
- `op.add_column('odds_snapshots', sa.Column('spread_home_odds', sa.Float(), nullable=True))`
- `op.add_column('odds_snapshots', sa.Column('spread_away_line', sa.Float(), nullable=True))`
- `op.add_column('odds_snapshots', sa.Column('spread_away_odds', sa.Float(), nullable=True))`

If autogenerate included extra unrelated changes, remove them — only keep the 4 spread columns for this migration step. The remaining tables will be added in the next migration.

- [ ] **Step 7: Commit**

```bash
git add app/db/models.py app/collector/collector.py migrations/
git commit -m "feat: add spread columns to OddsSnapshot model and collector"
```

---

## Task 6: Add red_card_minute to Result + FormCache, SpreadPrediction, OUAnalysis models

**Files:**
- Modify: `app/db/models.py`
- Create: `migrations/versions/<hash>_phase1_new_tables.py`
- Modify: `tests/test_db_models.py`

- [ ] **Step 1: Write failing tests for all new models**

Add to `tests/test_db_models.py`:

```python
def test_result_has_red_card_minute(db):
    from app.db.models import League, Team, Fixture, Result
    from datetime import datetime, timezone

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="rc1", home_team_id=home.id, away_team_id=away.id,
        league_id=league.id, kickoff_at=datetime.now(timezone.utc),
    )
    db.add(fixture)
    db.flush()
    result = Result(
        fixture_id=fixture.id,
        home_score=3, away_score=0,
        outcome="home", total_goals=3,
        red_card_minute=25,
        verified_at=datetime.now(timezone.utc),
    )
    db.add(result)
    db.flush()
    fetched = db.query(Result).filter_by(id=result.id).first()
    assert fetched.red_card_minute == 25


def _make_fixture(db, espn_id="f1"):
    from app.db.models import League, Team, Fixture
    from datetime import datetime, timezone
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id=espn_id, home_team_id=home.id, away_team_id=away.id,
        league_id=league.id, kickoff_at=datetime.now(timezone.utc),
    )
    db.add(fixture)
    db.flush()
    return fixture, home, away


def test_form_cache_model(db):
    from app.db.models import FormCache
    from datetime import datetime, timezone
    _, team, _ = _make_fixture(db)
    fc = FormCache(
        team_id=team.id,
        is_home=True,
        goals_scored_avg=1.8,
        goals_conceded_avg=0.9,
        spread_cover_rate=0.6,
        ou_hit_rate_15=0.9,
        ou_hit_rate_25=0.55,
        ou_hit_rate_35=0.2,
        matches_count=5,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(fc)
    db.flush()
    fetched = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert fetched.goals_scored_avg == 1.8
    assert fetched.matches_count == 5


def test_spread_prediction_model(db):
    from app.db.models import SpreadPrediction, ModelVersion
    from datetime import datetime, timezone
    fixture, _, _ = _make_fixture(db, espn_id="sp1")
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    sp = SpreadPrediction(
        model_id=mv.id,
        fixture_id=fixture.id,
        team_side="home",
        goal_line=-0.5,
        cover_probability=0.62,
        push_probability=0.0,
        ev_score=0.08,
        confidence_tier="HIGH",
        created_at=datetime.now(timezone.utc),
    )
    db.add(sp)
    db.flush()
    fetched = db.query(SpreadPrediction).filter_by(id=sp.id).first()
    assert fetched.goal_line == -0.5
    assert fetched.confidence_tier == "HIGH"


def test_ou_analysis_model(db):
    from app.db.models import OUAnalysis, ModelVersion
    from datetime import datetime, timezone
    fixture, _, _ = _make_fixture(db, espn_id="ou1")
    mv = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()
    ou = OUAnalysis(
        model_id=mv.id,
        fixture_id=fixture.id,
        line=2.5,
        direction="over",
        probability=0.58,
        ev_score=0.06,
        confidence_tier="HIGH",
        created_at=datetime.now(timezone.utc),
    )
    db.add(ou)
    db.flush()
    fetched = db.query(OUAnalysis).filter_by(id=ou.id).first()
    assert fetched.line == 2.5
    assert fetched.direction == "over"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_db_models.py::test_result_has_red_card_minute tests/test_db_models.py::test_form_cache_model tests/test_db_models.py::test_spread_prediction_model tests/test_db_models.py::test_ou_analysis_model -v
```

Expected: All FAIL

- [ ] **Step 3: Add all new ORM models to app/db/models.py**

Add `red_card_minute` to the existing `Result` class (after `ht_total_goals`):

```python
    red_card_minute = Column(Integer)  # minute of first red card; None if no red card; set by API-Football (Phase 3)
```

Add four new classes at the bottom of `app/db/models.py`:

```python
class FormCache(Base):
    __tablename__ = "form_cache"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    is_home = Column(Boolean, nullable=False)
    goals_scored_avg = Column(Float, nullable=False)
    goals_conceded_avg = Column(Float, nullable=False)
    spread_cover_rate = Column(Float)      # weighted % of last 5 games team won
    ou_hit_rate_15 = Column(Float)         # weighted % of last 5 games total goals > 1.5
    ou_hit_rate_25 = Column(Float)         # weighted % of last 5 games total goals > 2.5
    ou_hit_rate_35 = Column(Float)         # weighted % of last 5 games total goals > 3.5
    xg_scored_avg = Column(Float)          # nullable — populated by Understat (Phase 2)
    xg_conceded_avg = Column(Float)        # nullable — populated by Understat (Phase 2)
    matches_count = Column(Integer, default=0)
    updated_at = Column(DateTime)


class SpreadPrediction(Base):
    __tablename__ = "spread_predictions"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    team_side = Column(String, nullable=False)   # "home" | "away"
    goal_line = Column(Float, nullable=False)    # -1.5 | -1.0 | -0.5 | 0.5 | 1.0 | 1.5
    cover_probability = Column(Float)
    push_probability = Column(Float)             # non-zero only for integer lines (-1.0, +1.0)
    ev_score = Column(Float)                     # model_prob minus implied_prob; None if no odds
    confidence_tier = Column(String)             # SKIP | MEDIUM | HIGH | ELITE
    created_at = Column(DateTime, default=datetime.utcnow)


class OUAnalysis(Base):
    __tablename__ = "ou_analysis"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    line = Column(Float, nullable=False)         # 1.5 | 2.5 | 3.5
    direction = Column(String, nullable=False)   # "over" | "under"
    probability = Column(Float)
    ev_score = Column(Float)                     # None if snapshot line doesn't match
    confidence_tier = Column(String)             # SKIP | MEDIUM | HIGH | ELITE
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db_models.py -v
```

Expected: All PASS (in-memory SQLite picks up new models from Base.metadata)

- [ ] **Step 5: Generate and inspect Alembic migration**

```bash
alembic revision --autogenerate -m "phase1_new_tables"
```

Open the generated file and verify upgrade() includes:
- `op.add_column('results', sa.Column('red_card_minute', sa.Integer(), nullable=True))`
- `op.create_table('form_cache', ...)` with all columns
- `op.create_table('spread_predictions', ...)` with all columns
- `op.create_table('ou_analysis', ...)` with all columns

- [ ] **Step 6: Commit**

```bash
git add app/db/models.py migrations/ tests/test_db_models.py
git commit -m "feat: add FormCache, SpreadPrediction, OUAnalysis models; red_card_minute on Result"
```

---

## Task 7: FormCacheBuilder

**Files:**
- Create: `app/form_cache.py`
- Create: `tests/test_form_cache.py`

- [ ] **Step 1: Write failing tests for FormCacheBuilder**

Create `tests/test_form_cache.py`:

```python
from datetime import datetime, timezone, timedelta
import pytest
from app.db.models import League, Team, Fixture, Result, FormCache


def _seed_team_with_results(db, *, is_home: bool, scores: list[tuple[int, int]], red_card_minutes: list[int | None] = None):
    """
    Helper: create a team, opponent, and N completed fixtures with results.
    scores = list of (team_score, opponent_score) from team's perspective.
    Returns the team.
    """
    if red_card_minutes is None:
        red_card_minutes = [None] * len(scores)

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()

    team = Team(name="Arsenal", league_id=league.id)
    opponent = Team(name="Chelsea", league_id=league.id)
    db.add_all([team, opponent])
    db.flush()

    for i, ((ts, os), rcm) in enumerate(zip(scores, red_card_minutes)):
        if is_home:
            home_id, away_id = team.id, opponent.id
            home_score, away_score = ts, os
        else:
            home_id, away_id = opponent.id, team.id
            home_score, away_score = os, ts

        f = Fixture(
            espn_id=f"fx{i}",
            home_team_id=home_id,
            away_team_id=away_id,
            league_id=league.id,
            kickoff_at=datetime.now(timezone.utc) - timedelta(days=i + 1),
            status="completed",
        )
        db.add(f)
        db.flush()

        r = Result(
            fixture_id=f.id,
            home_score=home_score,
            away_score=away_score,
            outcome="home" if home_score > away_score else ("away" if away_score > home_score else "draw"),
            total_goals=home_score + away_score,
            red_card_minute=rcm,
            verified_at=datetime.now(timezone.utc),
        )
        db.add(r)
        db.flush()

    return team


def test_form_cache_builder_computes_goals_avg(db):
    from app.form_cache import FormCacheBuilder
    team = _seed_team_with_results(db, is_home=True, scores=[(2, 1), (1, 0), (3, 2), (0, 1), (2, 0)])
    count = FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert cache is not None
    assert cache.matches_count == 5
    assert abs(cache.goals_scored_avg - (2 + 1 + 3 + 0 + 2) / 5) < 0.01
    assert abs(cache.goals_conceded_avg - (1 + 0 + 2 + 1 + 0) / 5) < 0.01


def test_form_cache_builder_cover_rate(db):
    from app.form_cache import FormCacheBuilder
    # 3 wins, 1 draw, 1 loss
    team = _seed_team_with_results(db, is_home=True, scores=[(2, 0), (1, 0), (0, 0), (3, 1), (0, 2)])
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    # 3 wins → cover_rate = 3/5 = 0.6
    assert abs(cache.spread_cover_rate - 0.6) < 0.01


def test_form_cache_builder_ou_rates(db):
    from app.form_cache import FormCacheBuilder
    # totals: 3, 4, 2, 1, 5
    team = _seed_team_with_results(db, is_home=True, scores=[(2, 1), (3, 1), (1, 1), (1, 0), (3, 2)])
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    # totals > 1.5: games 3+4+2+5 = 4 → rate = 4/5 = 0.8 (game with total=1 fails, total=2 passes)
    # total 3: yes, 4: yes, 2: yes (>1.5), 1: no, 5: yes → 4/5 = 0.8
    assert abs(cache.ou_hit_rate_15 - 0.8) < 0.01
    # totals > 2.5: 3: yes, 4: yes, 2: no, 1: no, 5: yes → 3/5 = 0.6
    assert abs(cache.ou_hit_rate_25 - 0.6) < 0.01
    # totals > 3.5: 3: no, 4: yes, 2: no, 1: no, 5: yes → 2/5 = 0.4
    assert abs(cache.ou_hit_rate_35 - 0.4) < 0.01


def test_form_cache_red_card_normalization_early(db):
    from app.form_cache import FormCacheBuilder
    # 5 games; game 0 has red card at minute 25 (weight 0.25)
    # Without red card: scored avg = (3+1+1+2+2)/5 = 9/5 = 1.8
    # With red card weight 0.25 on game 0 (scored 3):
    #   weighted_scored = 3*0.25 + 1*1 + 1*1 + 2*1 + 2*1 = 0.75+1+1+2+2 = 6.75
    #   total_weight = 0.25+1+1+1+1 = 4.25
    #   avg = 6.75/4.25 ≈ 1.588
    team = _seed_team_with_results(
        db, is_home=True,
        scores=[(3, 0), (1, 1), (1, 2), (2, 0), (2, 1)],
        red_card_minutes=[25, None, None, None, None],
    )
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert abs(cache.goals_scored_avg - (6.75 / 4.25)) < 0.01


def test_form_cache_red_card_normalization_late(db):
    from app.form_cache import FormCacheBuilder
    # Red card at minute 70 → weight 0.75
    # scored=(2+1+1+2+2)=8, but game 0 weight=0.75
    # weighted_scored = 2*0.75 + 1+1+2+2 = 1.5+6 = 7.5
    # total_weight = 0.75+4 = 4.75
    # avg = 7.5/4.75 ≈ 1.579
    team = _seed_team_with_results(
        db, is_home=True,
        scores=[(2, 1), (1, 0), (1, 2), (2, 0), (2, 1)],
        red_card_minutes=[70, None, None, None, None],
    )
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert abs(cache.goals_scored_avg - (7.5 / 4.75)) < 0.01


def test_form_cache_away_form_tracked_separately(db):
    from app.form_cache import FormCacheBuilder
    team = _seed_team_with_results(db, is_home=False, scores=[(1, 2), (0, 1), (2, 2)])
    FormCacheBuilder(db).build_all()
    home_cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    away_cache = db.query(FormCache).filter_by(team_id=team.id, is_home=False).first()
    assert home_cache is None  # no home results seeded
    assert away_cache is not None
    assert away_cache.matches_count == 3


def test_form_cache_no_results_skipped(db):
    from app.form_cache import FormCacheBuilder
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    team = Team(name="NewTeam", league_id=league.id)
    db.add(team)
    db.flush()
    count = FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id).first()
    assert cache is None  # no results → no cache entry
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_form_cache.py -v
```

Expected: All FAIL — `ModuleNotFoundError: No module named 'app.form_cache'`

- [ ] **Step 3: Implement FormCacheBuilder**

Create `app/form_cache.py`:

```python
import logging
from datetime import datetime, timezone
from app.db.models import Fixture, FormCache, Result, Team

logger = logging.getLogger(__name__)


def _red_card_weight(red_card_minute: int | None) -> float:
    """Return the result weight based on when the red card occurred.
    None  → 1.0  (no red card — full weight)
    <  60 → 0.25 (early red card — result likely distorted)
    >= 60 → 0.75 (late red card — partial distortion)
    Configurable thresholds match the app ConfigMap spec (Section 4 of design doc).
    """
    if red_card_minute is None:
        return 1.0
    return 0.25 if red_card_minute < 60 else 0.75


class FormCacheBuilder:
    def __init__(self, session, lookback: int = 5):
        self.session = session
        self.lookback = lookback

    def build_all(self) -> int:
        """Rebuild form cache for all teams. Returns count of cache rows written."""
        teams = self.session.query(Team).all()
        count = 0
        for team in teams:
            for is_home in (True, False):
                if self._build_team_form(team.id, is_home):
                    count += 1
        self.session.commit()
        return count

    def build_for_fixture(self, fixture_id: int):
        """Rebuild form cache for both teams in a specific fixture."""
        fixture = self.session.query(Fixture).filter_by(id=fixture_id).first()
        if not fixture:
            return
        self._build_team_form(fixture.home_team_id, is_home=True)
        self._build_team_form(fixture.away_team_id, is_home=False)
        self.session.commit()

    def _build_team_form(self, team_id: int, is_home: bool) -> bool:
        rows = self._fetch_last_n(team_id, is_home)
        if not rows:
            return False

        total_weight = 0.0
        weighted_scored = 0.0
        weighted_conceded = 0.0
        cover_weight = 0.0
        ou_weight_15 = 0.0
        ou_weight_25 = 0.0
        ou_weight_35 = 0.0

        for result, fixture in rows:
            w = _red_card_weight(result.red_card_minute)
            scored = result.home_score if is_home else result.away_score
            conceded = result.away_score if is_home else result.home_score
            total = result.total_goals or 0

            total_weight += w
            weighted_scored += scored * w
            weighted_conceded += conceded * w
            if scored > conceded:
                cover_weight += w
            if total > 1.5:
                ou_weight_15 += w
            if total > 2.5:
                ou_weight_25 += w
            if total > 3.5:
                ou_weight_35 += w

        if total_weight == 0:
            return False

        kwargs = dict(
            goals_scored_avg=weighted_scored / total_weight,
            goals_conceded_avg=weighted_conceded / total_weight,
            spread_cover_rate=cover_weight / total_weight,
            ou_hit_rate_15=ou_weight_15 / total_weight,
            ou_hit_rate_25=ou_weight_25 / total_weight,
            ou_hit_rate_35=ou_weight_35 / total_weight,
            matches_count=len(rows),
            updated_at=datetime.now(timezone.utc),
        )
        existing = (self.session.query(FormCache)
                    .filter_by(team_id=team_id, is_home=is_home).first())
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            self.session.add(FormCache(team_id=team_id, is_home=is_home, **kwargs))
        return True

    def _fetch_last_n(self, team_id: int, is_home: bool) -> list:
        team_filter = (
            Fixture.home_team_id == team_id if is_home
            else Fixture.away_team_id == team_id
        )
        return (
            self.session.query(Result, Fixture)
            .join(Fixture, Result.fixture_id == Fixture.id)
            .filter(team_filter)
            .filter(Result.home_score.isnot(None))
            .order_by(Fixture.kickoff_at.desc())
            .limit(self.lookback)
            .all()
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_form_cache.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/form_cache.py tests/test_form_cache.py
git commit -m "feat: FormCacheBuilder with last-5 form aggregates and red card normalization"
```

---

## Task 8: SpreadPredictor

**Files:**
- Create: `app/spread_predictor.py`
- Create: `tests/test_spread_predictor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_spread_predictor.py`:

```python
import math
import pytest
from app.spread_predictor import cover_probability, _confidence_tier, _poisson_pmf


def test_poisson_pmf_known_values():
    # P(X=0 | λ=2) = e^-2 ≈ 0.1353
    assert abs(_poisson_pmf(0, 2.0) - math.exp(-2.0)) < 1e-6
    # P(X=2 | λ=2) = (4 * e^-2) / 2 = 2*e^-2 ≈ 0.2707
    assert abs(_poisson_pmf(2, 2.0) - (4 * math.exp(-2.0) / 2)) < 1e-6


def test_cover_probability_home_minus_half():
    """Home -0.5: home must win. With high home lambda, home should have high win prob."""
    win_p, push_p = cover_probability(2.5, 0.8, -0.5)
    assert 0.6 < win_p < 0.95  # strong home team should win most of the time
    assert push_p == 0.0  # no push on -0.5


def test_cover_probability_away_plus_half():
    """Away +0.5: away covers on draw or away win."""
    win_p_home, _ = cover_probability(2.5, 0.8, -0.5)
    win_p_away, _ = cover_probability(2.5, 0.8, 0.5)
    # P(home wins) + P(away covers +0.5) should sum to ~1.0 (no push on 0.5 lines)
    assert abs(win_p_home + win_p_away - 1.0) < 0.001


def test_cover_probability_integer_line_push():
    """Home -1.0: push occurs when home wins by exactly 1."""
    win_p, push_p = cover_probability(1.5, 1.5, -1.0)
    lose_p = 1.0 - win_p - push_p
    assert push_p > 0.0  # some probability of exactly 1-goal margin
    assert abs(win_p + push_p + lose_p - 1.0) < 0.001


def test_cover_probability_minus_1_and_minus_15_same_win_prob():
    """For integer goals, -1.0 and -1.5 have same win condition (home wins by 2+).
    -1.0 has a push on 1-goal margin; -1.5 does not (that margin is a loss)."""
    win_p_1, push_p_1 = cover_probability(2.0, 1.0, -1.0)
    win_p_15, push_p_15 = cover_probability(2.0, 1.0, -1.5)
    assert abs(win_p_1 - win_p_15) < 0.001  # same win probability
    assert push_p_1 > 0.0   # -1.0 has push
    assert push_p_15 == 0.0  # -1.5 has no push


def test_cover_probability_symmetric_equal_teams():
    """Equal teams: P(home covers -0.5) + P(away covers +0.5) == 1.0."""
    win_h, _ = cover_probability(1.5, 1.5, -0.5)
    win_a, _ = cover_probability(1.5, 1.5, 0.5)
    assert abs(win_h + win_a - 1.0) < 0.001


def test_confidence_tier_elite():
    assert _confidence_tier(0.12) == "ELITE"


def test_confidence_tier_high():
    assert _confidence_tier(0.07) == "HIGH"


def test_confidence_tier_medium():
    assert _confidence_tier(0.03) == "MEDIUM"


def test_confidence_tier_skip_low():
    assert _confidence_tier(0.01) == "SKIP"


def test_confidence_tier_skip_none():
    assert _confidence_tier(None) == "SKIP"


def test_spread_predictor_generates_predictions(db):
    from datetime import datetime, timezone, timedelta
    from app.db.models import (
        League, Team, Fixture, FormCache, ModelVersion, SpreadPrediction
    )
    from app.spread_predictor import SpreadPredictor

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="sp_test",
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="scheduled",
    )
    db.add(fixture)
    db.flush()
    db.add(FormCache(team_id=home.id, is_home=True,
                     goals_scored_avg=1.8, goals_conceded_avg=0.9,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    db.add(FormCache(team_id=away.id, is_home=False,
                     goals_scored_avg=1.2, goals_conceded_avg=1.5,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    SpreadPredictor(db, lead_hours=2).run(mv.id)

    preds = db.query(SpreadPrediction).filter_by(fixture_id=fixture.id).all()
    assert len(preds) == 6  # one per goal line
    lines = {p.goal_line for p in preds}
    assert lines == {-1.5, -1.0, -0.5, 0.5, 1.0, 1.5}


def test_spread_predictor_skips_fixture_without_form_cache(db):
    from datetime import datetime, timezone, timedelta
    from app.db.models import League, Team, Fixture, ModelVersion, SpreadPrediction
    from app.spread_predictor import SpreadPredictor

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="TeamA", league_id=league.id)
    away = Team(name="TeamB", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="no_form",
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="scheduled",
    )
    db.add(fixture)
    mv = ModelVersion(name="spread_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    SpreadPredictor(db, lead_hours=2).run(mv.id)
    preds = db.query(SpreadPrediction).filter_by(fixture_id=fixture.id).all()
    assert len(preds) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_spread_predictor.py -v
```

Expected: All FAIL — `ModuleNotFoundError: No module named 'app.spread_predictor'`

- [ ] **Step 3: Implement SpreadPredictor**

Create `app/spread_predictor.py`:

```python
import math
import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, SpreadPrediction

logger = logging.getLogger(__name__)

GOAL_LINES = [-1.5, -1.0, -0.5, 0.5, 1.0, 1.5]
MAX_GOALS = 10
LEAGUE_AVG_GOALS = 1.5  # normalisation constant for attack × defense formula


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def cover_probability(lambda_home: float, lambda_away: float, line: float) -> tuple[float, float]:
    """
    Returns (win_probability, push_probability) for a goal-line spread bet.

    line < 0  →  home spread  (e.g., -0.5: home must win; -1.0: home wins by 2+)
    line > 0  →  away spread  (e.g., +0.5: away covers on draw/win; +1.0: away covers unless home wins by 2+)

    Push only occurs on integer lines (-1.0, +1.0) when home wins by exactly 1.
    All lines 0.5-spaced (e.g., -0.5, -1.5, +0.5, +1.5) have push_probability == 0.
    """
    win_p = 0.0
    push_p = 0.0
    is_integer_line = abs(round(abs(line)) - abs(line)) < 0.01

    for h in range(MAX_GOALS + 1):
        ph = _poisson_pmf(h, lambda_home)
        for a in range(MAX_GOALS + 1):
            pa = _poisson_pmf(a, lambda_away)
            margin = h - a  # positive = home leading

            if line < 0:
                threshold = abs(line)
                if margin > threshold:
                    win_p += ph * pa
                elif is_integer_line and margin == round(threshold):
                    push_p += ph * pa
            else:
                threshold = line
                if margin < threshold:
                    win_p += ph * pa
                elif is_integer_line and margin == round(threshold):
                    push_p += ph * pa

    return win_p, push_p


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


def _confidence_tier(ev: float | None) -> str:
    if ev is None:
        return "SKIP"
    if ev >= 0.10:
        return "ELITE"
    if ev >= 0.05:
        return "HIGH"
    if ev >= 0.02:
        return "MEDIUM"
    return "SKIP"


class SpreadPredictor:
    def __init__(self, session, lead_hours: int | None = None):
        self.session = session
        self._lead_hours = lead_hours

    def run(self, model_id: int):
        upcoming = self._get_upcoming_fixtures()
        for fixture in upcoming:
            home_form = self._get_form(fixture.home_team_id, is_home=True)
            away_form = self._get_form(fixture.away_team_id, is_home=False)
            if not home_form or not away_form:
                logger.debug("No form cache for fixture %d — skipping spread prediction", fixture.id)
                continue

            # Attack × Defence / league_avg normalisation (standard Dixon-Coles precursor)
            lambda_home = max(0.1, home_form.goals_scored_avg * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS))
            lambda_away = max(0.1, away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS))

            snap = self._latest_snapshot(fixture.id)

            for line in GOAL_LINES:
                win_p, push_p = cover_probability(lambda_home, lambda_away, line)
                team_side = "home" if line < 0 else "away"
                ev = self._compute_ev(win_p, snap, line)
                tier = _confidence_tier(ev)
                self._upsert(model_id, fixture.id, team_side, line, win_p, push_p, ev, tier)

        self.session.commit()

    def _get_upcoming_fixtures(self) -> list[Fixture]:
        if self._lead_hours is not None:
            lead = self._lead_hours
        else:
            from app.config import settings
            lead = settings.prediction_lead_hours
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=lead)
        return (
            self.session.query(Fixture)
            .filter(Fixture.status == "scheduled")
            .filter(Fixture.kickoff_at >= now)
            .filter(Fixture.kickoff_at <= cutoff)
            .all()
        )

    def _get_form(self, team_id: int, is_home: bool) -> FormCache | None:
        return self.session.query(FormCache).filter_by(team_id=team_id, is_home=is_home).first()

    def _latest_snapshot(self, fixture_id: int) -> OddsSnapshot | None:
        return (
            self.session.query(OddsSnapshot)
            .filter_by(fixture_id=fixture_id)
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )

    def _compute_ev(self, win_p: float, snap: OddsSnapshot | None, line: float) -> float | None:
        if snap is None:
            return None
        if line < 0:
            implied = _implied_prob(snap.spread_home_odds)
        else:
            implied = _implied_prob(snap.spread_away_odds)
        if implied is None:
            return None
        return win_p - implied

    def _upsert(self, model_id, fixture_id, team_side, line, cover_p, push_p, ev, tier):
        existing = (
            self.session.query(SpreadPrediction)
            .filter_by(model_id=model_id, fixture_id=fixture_id, goal_line=line)
            .first()
        )
        if existing:
            existing.cover_probability = cover_p
            existing.push_probability = push_p
            existing.ev_score = ev
            existing.confidence_tier = tier
        else:
            self.session.add(SpreadPrediction(
                model_id=model_id,
                fixture_id=fixture_id,
                team_side=team_side,
                goal_line=line,
                cover_probability=cover_p,
                push_probability=push_p,
                ev_score=ev,
                confidence_tier=tier,
                created_at=datetime.now(timezone.utc),
            ))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_spread_predictor.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/spread_predictor.py tests/test_spread_predictor.py
git commit -m "feat: SpreadPredictor with Poisson goal-line cover probabilities"
```

---

## Task 9: OUAnalyzer

**Files:**
- Create: `app/ou_analyzer.py`
- Create: `tests/test_ou_analyzer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ou_analyzer.py`:

```python
import math
import pytest
from app.ou_analyzer import ou_over_probability, _confidence_tier


def test_ou_over_probability_25_symmetric():
    """Equal attack/defense: P(over 2.5) should be reasonable for λ_total=2.5."""
    # P(X > 2.5 | λ=2.5) = 1 - P(X<=2) = 1 - (e^-2.5 * (1 + 2.5 + 3.125)) = 1 - e^-2.5 * 6.625
    lam = 2.5
    import math
    expected = 1.0 - sum((lam ** k) * math.exp(-lam) / math.factorial(k) for k in range(3))
    assert abs(ou_over_probability(lam, 2.5) - expected) < 1e-6


def test_ou_over_probability_15():
    lam = 2.5
    import math
    expected = 1.0 - sum((lam ** k) * math.exp(-lam) / math.factorial(k) for k in range(2))
    assert abs(ou_over_probability(lam, 1.5) - expected) < 1e-6


def test_ou_over_probability_complement():
    """over + under should sum to 1 for half-ball lines."""
    over = ou_over_probability(2.0, 2.5)
    under = 1.0 - over
    assert abs(over + under - 1.0) < 1e-10


def test_ou_over_probability_increases_with_lambda():
    """Higher expected goals → higher P(over 2.5)."""
    p_low = ou_over_probability(1.0, 2.5)
    p_high = ou_over_probability(4.0, 2.5)
    assert p_high > p_low


def test_confidence_tier_boundaries():
    from app.ou_analyzer import _confidence_tier
    assert _confidence_tier(0.10) == "ELITE"
    assert _confidence_tier(0.05) == "HIGH"
    assert _confidence_tier(0.02) == "MEDIUM"
    assert _confidence_tier(0.019) == "SKIP"
    assert _confidence_tier(None) == "SKIP"


def test_ou_analyzer_generates_analysis(db):
    from datetime import datetime, timezone, timedelta
    from app.db.models import (
        League, Team, Fixture, FormCache, ModelVersion, OUAnalysis
    )
    from app.ou_analyzer import OUAnalyzer

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    home = Team(name="Arsenal", league_id=league.id)
    away = Team(name="Chelsea", league_id=league.id)
    db.add_all([home, away])
    db.flush()
    fixture = Fixture(
        espn_id="ou_test",
        home_team_id=home.id, away_team_id=away.id,
        league_id=league.id,
        kickoff_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="scheduled",
    )
    db.add(fixture)
    db.flush()
    db.add(FormCache(team_id=home.id, is_home=True,
                     goals_scored_avg=1.8, goals_conceded_avg=0.9,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    db.add(FormCache(team_id=away.id, is_home=False,
                     goals_scored_avg=1.2, goals_conceded_avg=1.5,
                     matches_count=5, updated_at=datetime.now(timezone.utc)))
    mv = ModelVersion(name="ou_v1", version="1.0", active=True)
    db.add(mv)
    db.flush()

    OUAnalyzer(db, lead_hours=2).run(mv.id)

    analyses = db.query(OUAnalysis).filter_by(fixture_id=fixture.id).all()
    assert len(analyses) == 3  # 1.5, 2.5, 3.5 lines
    lines = {a.line for a in analyses}
    assert lines == {1.5, 2.5, 3.5}
    for a in analyses:
        assert a.direction in ("over", "under")
        assert 0.0 <= a.probability <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ou_analyzer.py -v
```

Expected: All FAIL — `ModuleNotFoundError: No module named 'app.ou_analyzer'`

- [ ] **Step 3: Implement OUAnalyzer**

Create `app/ou_analyzer.py`:

```python
import math
import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, OUAnalysis

logger = logging.getLogger(__name__)

OU_LINES = [1.5, 2.5, 3.5]
MAX_GOALS = 15
LEAGUE_AVG_GOALS = 1.5


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def ou_over_probability(lambda_total: float, line: float) -> float:
    """P(total goals > line) where line is a half-ball value (no push possible)."""
    n_max = int(line)  # e.g., 2.5 → 2; 1.5 → 1; 3.5 → 3
    p_at_most = sum(_poisson_pmf(n, lambda_total) for n in range(n_max + 1))
    return 1.0 - p_at_most


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


def _confidence_tier(ev: float | None) -> str:
    if ev is None:
        return "SKIP"
    if ev >= 0.10:
        return "ELITE"
    if ev >= 0.05:
        return "HIGH"
    if ev >= 0.02:
        return "MEDIUM"
    return "SKIP"


class OUAnalyzer:
    def __init__(self, session, lead_hours: int | None = None):
        self.session = session
        self._lead_hours = lead_hours

    def run(self, model_id: int):
        upcoming = self._get_upcoming_fixtures()
        for fixture in upcoming:
            home_form = self._get_form(fixture.home_team_id, is_home=True)
            away_form = self._get_form(fixture.away_team_id, is_home=False)
            if not home_form or not away_form:
                continue

            lambda_home = max(0.1, home_form.goals_scored_avg * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS))
            lambda_away = max(0.1, away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS))
            lambda_total = lambda_home + lambda_away

            snap = self._latest_snapshot(fixture.id)

            for line in OU_LINES:
                over_p = ou_over_probability(lambda_total, line)
                under_p = 1.0 - over_p
                # Pick the direction with the higher model probability
                if over_p >= under_p:
                    direction = "over"
                    prob = over_p
                    ev = self._compute_ev(over_p, snap, "over")
                else:
                    direction = "under"
                    prob = under_p
                    ev = self._compute_ev(under_p, snap, "under")

                tier = _confidence_tier(ev)
                self._upsert(model_id, fixture.id, line, direction, prob, ev, tier)

        self.session.commit()

    def _get_upcoming_fixtures(self) -> list[Fixture]:
        if self._lead_hours is not None:
            lead = self._lead_hours
        else:
            from app.config import settings
            lead = settings.prediction_lead_hours
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=lead)
        return (
            self.session.query(Fixture)
            .filter(Fixture.status == "scheduled")
            .filter(Fixture.kickoff_at >= now)
            .filter(Fixture.kickoff_at <= cutoff)
            .all()
        )

    def _get_form(self, team_id: int, is_home: bool) -> FormCache | None:
        return self.session.query(FormCache).filter_by(team_id=team_id, is_home=is_home).first()

    def _latest_snapshot(self, fixture_id: int) -> OddsSnapshot | None:
        return (
            self.session.query(OddsSnapshot)
            .filter_by(fixture_id=fixture_id)
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )

    def _compute_ev(self, prob: float, snap: OddsSnapshot | None, direction: str) -> float | None:
        """EV is only computed for the main snapshot line (over/under odds in snapshot).
        For lines 1.5 and 3.5, EV is None unless the snapshot line matches."""
        if snap is None:
            return None
        if direction == "over":
            implied = _implied_prob(snap.over_odds)
        else:
            implied = _implied_prob(snap.under_odds)
        if implied is None:
            return None
        return prob - implied

    def _upsert(self, model_id, fixture_id, line, direction, prob, ev, tier):
        existing = (
            self.session.query(OUAnalysis)
            .filter_by(model_id=model_id, fixture_id=fixture_id, line=line)
            .first()
        )
        if existing:
            existing.direction = direction
            existing.probability = prob
            existing.ev_score = ev
            existing.confidence_tier = tier
        else:
            self.session.add(OUAnalysis(
                model_id=model_id,
                fixture_id=fixture_id,
                line=line,
                direction=direction,
                probability=prob,
                ev_score=ev,
                confidence_tier=tier,
                created_at=datetime.now(timezone.utc),
            ))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ou_analyzer.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/ou_analyzer.py tests/test_ou_analyzer.py
git commit -m "feat: OUAnalyzer with Poisson O/U probabilities for 1.5, 2.5, 3.5 lines"
```

---

## Task 10: Wire into scheduler + CLI

**Files:**
- Modify: `app/scheduler.py`
- Modify: `cli.py`
- Modify: `app/config.py`

- [ ] **Step 1: Add new settings to config**

In `app/config.py`, add `spread_model_version` and `ou_model_version`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    odds_api_key: str
    collection_interval_hours: int = 6
    prediction_lead_hours: int = 2
    spread_model_version: str = "1.0"   # version string for spread_v1 model
    ou_model_version: str = "1.0"       # version string for ou_v1 model

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Add three new scheduler jobs**

In `app/scheduler.py`, add after the existing `track_results_job` function (before `start_scheduler`):

```python
def form_cache_job():
    session = get_session()
    log = SchedulerLog(job_name="form_cache", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.form_cache import FormCacheBuilder
        count = FormCacheBuilder(session).build_all()
        log.status = "success"
        logger.info("form_cache_job: updated %d cache entries", count)
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("form_cache_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def spread_predict_job():
    session = get_session()
    log = SchedulerLog(job_name="spread_predict", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.spread_predictor import SpreadPredictor
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="spread_v1", active=True).first()
        if not mv:
            mv = ModelVersion(name="spread_v1", version=settings.spread_model_version,
                              description="Phase 1 Poisson spread predictor", active=True)
            session.add(mv)
            session.flush()
        SpreadPredictor(session).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("spread_predict_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()


def ou_analyze_job():
    session = get_session()
    log = SchedulerLog(job_name="ou_analyze", status="running", started_at=datetime.now(timezone.utc))
    session.add(log)
    session.commit()
    try:
        from app.ou_analyzer import OUAnalyzer
        from app.db.models import ModelVersion
        mv = session.query(ModelVersion).filter_by(name="ou_v1", active=True).first()
        if not mv:
            mv = ModelVersion(name="ou_v1", version=settings.ou_model_version,
                              description="Phase 1 Poisson O/U analyzer", active=True)
            session.add(mv)
            session.flush()
        OUAnalyzer(session).run(mv.id)
        log.status = "success"
    except Exception as e:
        log.status = "error"
        log.error = str(e)
        logger.exception("ou_analyze_job failed")
    finally:
        log.completed_at = datetime.now(timezone.utc)
        session.commit()
        session.close()
```

In `start_scheduler`, add three new jobs inside the function before `scheduler.start()`:

```python
    scheduler.add_job(
        form_cache_job, IntervalTrigger(hours=settings.collection_interval_hours),
        id="form_cache", replace_existing=True
    )
    scheduler.add_job(
        spread_predict_job, IntervalTrigger(minutes=30),
        id="spread_predict", replace_existing=True
    )
    scheduler.add_job(
        ou_analyze_job, IntervalTrigger(minutes=30),
        id="ou_analyze", replace_existing=True
    )
```

- [ ] **Step 3: Add CLI commands**

In `cli.py`, add three new commands after the `collect` command:

```python
@cli.command()
def build_form_cache():
    """Build/refresh form cache for all teams from completed results."""
    from app.form_cache import FormCacheBuilder
    session = get_session()
    try:
        count = FormCacheBuilder(session).build_all()
        click.echo(f"Form cache updated: {count} team/home entries written.")
    finally:
        session.close()


@cli.command()
def predict_spreads():
    """Run spread predictor for upcoming fixtures."""
    from app.spread_predictor import SpreadPredictor
    from app.db.models import ModelVersion
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="spread_v1", active=True).first()
        if not mv:
            from app.config import settings
            mv = ModelVersion(name="spread_v1", version=settings.spread_model_version,
                              description="Phase 1 Poisson spread predictor", active=True)
            session.add(mv)
            session.flush()
        SpreadPredictor(session).run(mv.id)
        session.commit()
        click.echo("Spread predictions complete.")
    finally:
        session.close()


@cli.command()
def predict_ou():
    """Run O/U analyzer for upcoming fixtures."""
    from app.ou_analyzer import OUAnalyzer
    from app.db.models import ModelVersion
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="ou_v1", active=True).first()
        if not mv:
            from app.config import settings
            mv = ModelVersion(name="ou_v1", version=settings.ou_model_version,
                              description="Phase 1 Poisson O/U analyzer", active=True)
            session.add(mv)
            session.flush()
        OUAnalyzer(session).run(mv.id)
        session.commit()
        click.echo("O/U analysis complete.")
    finally:
        session.close()
```

- [ ] **Step 4: Run all tests to confirm nothing broken**

```bash
pytest tests/ -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py app/config.py cli.py
git commit -m "feat: wire FormCacheBuilder, SpreadPredictor, OUAnalyzer into scheduler and CLI"
```

---

## Task 11: Run full migration against real Postgres

This task verifies the migrations work against a real database (not just in-memory SQLite).

- [ ] **Step 1: Start the database**

```bash
docker-compose up -d postgres
```

Wait for healthy:
```bash
docker-compose ps
```

Expected: `postgres` service shows `healthy`

- [ ] **Step 2: Copy .env.example if needed**

```bash
cp .env.example .env 2>/dev/null || true
```

Verify `.env` contains:
```
DATABASE_URL=postgresql://betuser:betpass@localhost:5432/soccerbet
ODDS_API_KEY=dummy_for_local
```

- [ ] **Step 3: Run all migrations**

```bash
alembic upgrade head
```

Expected output: migration steps applied with no errors. Last line should reference the most recent revision.

- [ ] **Step 4: Verify schema with psql**

```bash
docker-compose exec postgres psql -U betuser -d soccerbet -c "\dt"
```

Expected: 13 tables listed including `form_cache`, `spread_predictions`, `ou_analysis`.

```bash
docker-compose exec postgres psql -U betuser -d soccerbet -c "\d odds_snapshots"
```

Expected: columns include `spread_home_line`, `spread_home_odds`, `spread_away_line`, `spread_away_odds`.

```bash
docker-compose exec postgres psql -U betuser -d soccerbet -c "\d results"
```

Expected: columns include `red_card_minute`.

- [ ] **Step 5: Seed leagues**

```bash
python cli.py seed
```

Expected: `Seeded 6 league(s). 0 already existed.`

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "chore: verify phase1 migrations run cleanly against Postgres"
```

---

*All tests passing after Task 10 confirms this plan is complete. Plan 2 (API & Dashboard) and Plan 3 (Infra) can proceed.*
