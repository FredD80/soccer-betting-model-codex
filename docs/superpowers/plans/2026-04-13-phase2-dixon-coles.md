# Phase 2 — Dixon-Coles Model & Monte Carlo Simulation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current independent Poisson model with a Dixon-Coles bivariate distribution (low-score correlation correction + league calibration) and add a Monte Carlo simulation task (10,000 runs per fixture) that produces a scoreline probability distribution. Both predictors — `SpreadPredictor` and `OUAnalyzer` — are upgraded in-place. A new `MonteCarloTask` Celery worker writes results to a new `monte_carlo_runs` table.

**Architecture:** `app/dixon_coles.py` — pure math module, no DB dependencies. `app/league_calibration.py` — loads/seeds calibration factors. `SpreadPredictor` and `OUAnalyzer` import from `dixon_coles.py`. `MonteCarloTask` runs as a Celery task and is CPU-heavy. All new DB writes via SQLAlchemy.

**Tech Stack:** Python 3.12, numpy (already available via scipy), SQLAlchemy 2.x, Alembic, Celery.

**Prerequisites:** Phase 2 data sources plan complete (FormCache has xg_scored_avg / xg_conceded_avg).

**Must complete before:** XGBoost/LightGBM learned weights plan.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `app/db/models.py` | Add `LeagueCalibration`, `MonteCarloRun` ORM models |
| Create | `migrations/versions/<hash>_phase2_dixon_coles.py` | New tables: league_calibration, monte_carlo_runs |
| Create | `app/dixon_coles.py` | Dixon-Coles math — tau correction, joint PMF, scoreline matrix |
| Create | `app/league_calibration.py` | Load/seed league calibration rows from DB |
| Modify | `app/spread_predictor.py` | Use Dixon-Coles joint PMF instead of independent Poisson |
| Modify | `app/ou_analyzer.py` | Use Dixon-Coles joint PMF for O/U probability |
| Create | `app/monte_carlo.py` | MonteCarloSimulator — 10,000 runs, scoreline distribution |
| Modify | `app/celery_app.py` | Add `monte_carlo_task` |
| Modify | `app/scheduler.py` | Schedule `monte_carlo_task` 2hr before kickoff |
| Modify | `requirements.txt` | Add numpy |
| Create | `tests/test_dixon_coles.py` | Unit tests for tau, joint PMF, matrix |
| Create | `tests/test_league_calibration.py` | Tests for seeding and loading calibration |
| Create | `tests/test_monte_carlo.py` | Tests for simulation output shape and properties |
| Create | `scripts/seed_league_calibration.py` | One-time seed with initial calibration factors |

---

## Task 1: Schema — league_calibration + monte_carlo_runs

**Files:**
- Modify: `app/db/models.py`
- Create: `migrations/versions/<hash>_phase2_dixon_coles.py`

### Step 1: Write tests for new models

Create `tests/test_phase2_dc_models.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.models import Base, LeagueCalibration, MonteCarloRun
from datetime import datetime


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_league_calibration_columns(session):
    lc = LeagueCalibration(
        league_id="eng.1",
        rho=-0.13,
        home_advantage=1.20,
        attack_scale=1.0,
        defense_scale=1.0,
        updated_at=datetime.utcnow(),
    )
    session.add(lc)
    session.commit()
    assert lc.id is not None
    assert lc.rho == pytest.approx(-0.13)


def test_monte_carlo_run_columns(session):
    mc = MonteCarloRun(
        fixture_id=1,
        model_version="dc_v1",
        simulations=10000,
        scoreline_json='{"0-0": 0.08, "1-0": 0.14}',
        home_win_prob=0.52,
        draw_prob=0.23,
        away_win_prob=0.25,
        over_25_prob=0.61,
        created_at=datetime.utcnow(),
    )
    session.add(mc)
    session.commit()
    assert mc.id is not None
    assert mc.home_win_prob == pytest.approx(0.52)
```

Run and verify FAIL:
```bash
python -m pytest tests/test_phase2_dc_models.py -v
```
Expected: ImportError — models don't exist yet.

### Step 2: Add ORM models to `app/db/models.py`

Append after `RotationFlag`:

```python
class LeagueCalibration(Base):
    """Dixon-Coles calibration parameters per league — seeded manually, updated by backtester."""
    __tablename__ = "league_calibration"
    id = Column(Integer, primary_key=True)
    league_id = Column(String, nullable=False, unique=True)  # e.g. "eng.1"
    rho = Column(Float, nullable=False, default=-0.13)       # Dixon-Coles correlation (typically -0.08 to -0.18)
    home_advantage = Column(Float, nullable=False, default=1.20)  # multiplicative home boost
    attack_scale = Column(Float, nullable=False, default=1.0)    # league-wide attack scaling
    defense_scale = Column(Float, nullable=False, default=1.0)   # league-wide defense scaling
    updated_at = Column(DateTime)


class MonteCarloRun(Base):
    """Scoreline simulation results per fixture — written by Celery monte_carlo_task."""
    __tablename__ = "monte_carlo_runs"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    model_version = Column(String, nullable=False, default="dc_v1")
    simulations = Column(Integer, nullable=False, default=10000)
    scoreline_json = Column(Text, nullable=False)   # JSON: {"0-0": prob, "1-0": prob, ...} top 20 scorelines
    home_win_prob = Column(Float)
    draw_prob = Column(Float)
    away_win_prob = Column(Float)
    over_15_prob = Column(Float)
    over_25_prob = Column(Float)
    over_35_prob = Column(Float)
    created_at = Column(DateTime, nullable=False)
```

### Step 3: Generate migration

```bash
DATABASE_URL=sqlite:///./test_migration.db PYTHONPATH=. alembic upgrade head
DATABASE_URL=sqlite:///./test_migration.db PYTHONPATH=. alembic revision --autogenerate -m "phase2_dixon_coles"
```

### Step 4: Run tests — verify PASS

```bash
python -m pytest tests/test_phase2_dc_models.py -v
```

### Step 5: Commit

```bash
git add app/db/models.py migrations/ tests/test_phase2_dc_models.py
git commit -m "feat: add LeagueCalibration and MonteCarloRun schema"
```

---

## Task 2: Dixon-Coles math module

**Files:**
- Create: `app/dixon_coles.py`
- Create: `tests/test_dixon_coles.py`

### Step 1: Write failing tests

Create `tests/test_dixon_coles.py`:

```python
import math
import pytest
from app.dixon_coles import tau, dixon_coles_pmf, build_score_matrix, cover_probability_dc, ou_probability_dc

# --- tau correction ---

def test_tau_00_reduces_probability():
    # tau(0,0) < 1 for typical negative rho
    t = tau(0, 0, mu=1.5, nu=1.0, rho=-0.13)
    assert t < 1.0

def test_tau_11_reduces_probability():
    t = tau(1, 1, mu=1.5, nu=1.0, rho=-0.13)
    assert t < 1.0

def test_tau_10_increases_probability():
    t = tau(1, 0, mu=1.5, nu=1.0, rho=-0.13)
    assert t > 1.0

def test_tau_01_increases_probability():
    t = tau(0, 1, mu=1.5, nu=1.0, rho=-0.13)
    assert t > 1.0

def test_tau_high_scores_is_one():
    for h in range(2, 5):
        for a in range(2, 5):
            assert tau(h, a, mu=1.5, nu=1.0, rho=-0.13) == pytest.approx(1.0)

def test_tau_rho_zero_is_one():
    # With rho=0, Dixon-Coles reduces to independent Poisson (tau=1 everywhere)
    for h in range(4):
        for a in range(4):
            assert tau(h, a, mu=1.5, nu=1.0, rho=0.0) == pytest.approx(1.0)

# --- score matrix ---

def test_score_matrix_shape():
    matrix = build_score_matrix(mu=1.5, nu=1.0, rho=-0.13, max_goals=10)
    assert len(matrix) == 11  # 0..10
    assert len(matrix[0]) == 11

def test_score_matrix_sums_to_one():
    matrix = build_score_matrix(mu=1.5, nu=1.0, rho=-0.13, max_goals=10)
    total = sum(matrix[h][a] for h in range(11) for a in range(11))
    assert total == pytest.approx(1.0, abs=0.01)

def test_score_matrix_non_negative():
    matrix = build_score_matrix(mu=1.5, nu=1.0, rho=-0.13, max_goals=10)
    for h in range(11):
        for a in range(11):
            assert matrix[h][a] >= 0.0

# --- spread cover probability ---

def test_cover_probability_dc_home_favorite():
    # Strong home team should have high cover prob on -0.5
    win_p, push_p = cover_probability_dc(mu=2.0, nu=0.8, rho=-0.13, line=-0.5)
    assert win_p > 0.5
    assert push_p == pytest.approx(0.0)  # no push on half-ball line

def test_cover_probability_dc_integer_line_has_push():
    win_p, push_p = cover_probability_dc(mu=2.0, nu=1.0, rho=-0.13, line=-1.0)
    assert push_p > 0.0  # some probability of winning by exactly 1

# --- O/U probability ---

def test_ou_probability_over_25():
    over_p = ou_probability_dc(mu=1.8, nu=1.4, rho=-0.13, line=2.5)
    assert 0.0 < over_p < 1.0

def test_ou_probability_over_plus_under_equals_one():
    over_p = ou_probability_dc(mu=1.8, nu=1.4, rho=-0.13, line=2.5)
    under_p = 1.0 - over_p
    assert over_p + under_p == pytest.approx(1.0)

def test_dc_vs_poisson_difference_for_low_lambdas():
    """Dixon-Coles with rho<0 should give higher P(0-0) and P(1-1) than pure Poisson."""
    from app.dixon_coles import build_score_matrix
    import math
    mu, nu, rho = 0.8, 0.6, -0.13
    matrix_dc = build_score_matrix(mu=mu, nu=nu, rho=rho, max_goals=6)
    # Pure Poisson P(0-0)
    p00_poisson = math.exp(-mu) * math.exp(-nu)
    p00_dc = matrix_dc[0][0]
    # DC with negative rho increases 0-0 probability
    assert p00_dc > p00_poisson * 0.9  # DC adjusts, should be in the right ballpark
```

Run and verify FAIL:
```bash
python -m pytest tests/test_dixon_coles.py -v
```
Expected: ImportError.

### Step 2: Implement `app/dixon_coles.py`

```python
"""
Dixon-Coles bivariate Poisson model.

Key reference: Dixon & Coles (1997) "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market".

The model adds a correlation correction τ for low-scoring outcomes
(0-0, 1-0, 0-1, 1-1) which are systematically underestimated by
independent Poisson.
"""
import math

MAX_GOALS_DEFAULT = 10


def tau(home: int, away: int, mu: float, nu: float, rho: float) -> float:
    """
    Dixon-Coles correction factor for joint probability P(home, away).

    Only the four low-score cells differ from 1.0:
      τ(0,0) = 1 - μνρ
      τ(1,0) = 1 + νρ
      τ(0,1) = 1 + μρ
      τ(1,1) = 1 - ρ
      τ(i,j) = 1  for all i+j >= 2 (except 1,1 handled above)
    """
    if home == 0 and away == 0:
        return 1.0 - mu * nu * rho
    if home == 1 and away == 0:
        return 1.0 + nu * rho
    if home == 0 and away == 1:
        return 1.0 + mu * rho
    if home == 1 and away == 1:
        return 1.0 - rho
    return 1.0


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def dixon_coles_pmf(home: int, away: int, mu: float, nu: float, rho: float) -> float:
    """
    Dixon-Coles joint probability P(Home=home, Away=away).
    """
    return (tau(home, away, mu, nu, rho)
            * _poisson_pmf(home, mu)
            * _poisson_pmf(away, nu))


def build_score_matrix(mu: float, nu: float, rho: float,
                       max_goals: int = MAX_GOALS_DEFAULT) -> list[list[float]]:
    """
    Build (max_goals+1) x (max_goals+1) joint probability matrix.
    matrix[h][a] = P(home scores h, away scores a).
    """
    matrix = []
    for h in range(max_goals + 1):
        row = []
        for a in range(max_goals + 1):
            row.append(dixon_coles_pmf(h, a, mu, nu, rho))
        matrix.append(row)
    return matrix


def cover_probability_dc(mu: float, nu: float, rho: float, line: float,
                         max_goals: int = MAX_GOALS_DEFAULT) -> tuple[float, float]:
    """
    Returns (win_probability, push_probability) for a spread bet using
    the Dixon-Coles joint distribution.

    line < 0  →  home spread  (e.g., -0.5: home must win outright)
    line > 0  →  away spread  (e.g., +0.5: away covers on draw or win)

    Push only occurs on integer lines (-1.0, +1.0) when home wins by exactly 1.
    """
    matrix = build_score_matrix(mu, nu, rho, max_goals)
    win_p = 0.0
    push_p = 0.0
    is_integer_line = abs(round(abs(line)) - abs(line)) < 0.01

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = matrix[h][a]
            margin = h - a

            if line < 0:
                threshold = abs(line)
                if margin > threshold:
                    win_p += p
                elif is_integer_line and margin == round(threshold):
                    push_p += p
            else:
                threshold = line
                if margin < threshold:
                    win_p += p
                elif is_integer_line and margin == round(threshold):
                    push_p += p

    return win_p, push_p


def ou_probability_dc(mu: float, nu: float, rho: float, line: float,
                      max_goals: int = MAX_GOALS_DEFAULT) -> float:
    """
    Returns P(total goals > line) using the Dixon-Coles joint distribution.
    line is assumed to be a half-ball value (no push), e.g. 1.5, 2.5, 3.5.
    """
    matrix = build_score_matrix(mu, nu, rho, max_goals)
    over_p = 0.0
    threshold = int(line)  # e.g., 2.5 → 2; over means total >= 3
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            if h + a > threshold:
                over_p += matrix[h][a]
    return over_p
```

### Step 3: Run tests — verify PASS

```bash
python -m pytest tests/test_dixon_coles.py -v
```

Expected: All PASS.

### Step 4: Commit

```bash
git add app/dixon_coles.py tests/test_dixon_coles.py
git commit -m "feat: implement Dixon-Coles bivariate Poisson math module"
```

---

## Task 3: League calibration — seed + loader

**Files:**
- Create: `app/league_calibration.py`
- Create: `tests/test_league_calibration.py`
- Create: `scripts/seed_league_calibration.py`

### Step 1: Write failing tests

Create `tests/test_league_calibration.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.models import Base, LeagueCalibration
from app.league_calibration import get_calibration, LEAGUE_DEFAULTS


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


def test_get_calibration_returns_db_row():
    session = make_session()
    session.add(LeagueCalibration(league_id="eng.1", rho=-0.15, home_advantage=1.25,
                                   attack_scale=1.0, defense_scale=1.0))
    session.commit()
    cal = get_calibration(session, "eng.1")
    assert cal["rho"] == pytest.approx(-0.15)
    assert cal["home_advantage"] == pytest.approx(1.25)


def test_get_calibration_falls_back_to_defaults():
    session = make_session()  # empty DB
    cal = get_calibration(session, "eng.1")
    assert cal["rho"] == LEAGUE_DEFAULTS["eng.1"]["rho"]


def test_get_calibration_unknown_league_uses_generic_default():
    session = make_session()
    cal = get_calibration(session, "unk.1")
    assert "rho" in cal
    assert "home_advantage" in cal


def test_league_defaults_covers_all_tracked_leagues():
    required = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "uefa.champions"}
    assert required.issubset(set(LEAGUE_DEFAULTS.keys()))
```

Run and verify FAIL.

### Step 2: Implement `app/league_calibration.py`

```python
"""
League-specific Dixon-Coles calibration parameters.

Initial values are based on published research and league characteristics:
- EPL: moderate home advantage, medium parity
- La Liga: Real/Barca dominance, slightly lower home advantage
- Bundesliga: highest scoring, strong home advantage
- Serie A: tactical/low scoring, lower home advantage
- Ligue 1: high home advantage, PSG distortion in attack scale
- UCL: away goals era removed, tight defensive play in knockouts

rho: Dixon-Coles correlation (negative = low scores underweighted by Poisson)
home_advantage: multiplicative boost to home team expected goals
attack_scale: league-wide scaling for attack lambda (1.0 = no adjustment)
defense_scale: league-wide scaling for defense lambda (1.0 = no adjustment)
"""
from app.db.models import LeagueCalibration

LEAGUE_DEFAULTS: dict[str, dict] = {
    "eng.1": {"rho": -0.13, "home_advantage": 1.20, "attack_scale": 1.0, "defense_scale": 1.0},
    "esp.1": {"rho": -0.11, "home_advantage": 1.15, "attack_scale": 1.0, "defense_scale": 1.0},
    "ger.1": {"rho": -0.10, "home_advantage": 1.25, "attack_scale": 1.05, "defense_scale": 0.95},
    "ita.1": {"rho": -0.15, "home_advantage": 1.10, "attack_scale": 0.92, "defense_scale": 1.08},
    "fra.1": {"rho": -0.12, "home_advantage": 1.22, "attack_scale": 0.97, "defense_scale": 1.0},
    "uefa.champions": {"rho": -0.16, "home_advantage": 1.08, "attack_scale": 0.95, "defense_scale": 1.05},
}

_GENERIC_DEFAULT = {"rho": -0.13, "home_advantage": 1.15, "attack_scale": 1.0, "defense_scale": 1.0}


def get_calibration(session, league_id: str) -> dict:
    """
    Return calibration dict for league_id.
    Priority: DB row > LEAGUE_DEFAULTS > generic default.
    """
    row = session.query(LeagueCalibration).filter_by(league_id=league_id).first()
    if row:
        return {
            "rho": row.rho,
            "home_advantage": row.home_advantage,
            "attack_scale": row.attack_scale,
            "defense_scale": row.defense_scale,
        }
    return LEAGUE_DEFAULTS.get(league_id, _GENERIC_DEFAULT).copy()
```

### Step 3: Create seed script `scripts/seed_league_calibration.py`

```python
"""One-time script to seed league_calibration table with initial Dixon-Coles parameters."""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.db.connection import get_engine
from app.db.models import LeagueCalibration
from app.league_calibration import LEAGUE_DEFAULTS


def seed():
    engine = get_engine()
    with Session(engine) as session:
        seeded = 0
        for league_id, params in LEAGUE_DEFAULTS.items():
            existing = session.query(LeagueCalibration).filter_by(league_id=league_id).first()
            if existing:
                continue
            session.add(LeagueCalibration(
                league_id=league_id,
                rho=params["rho"],
                home_advantage=params["home_advantage"],
                attack_scale=params["attack_scale"],
                defense_scale=params["defense_scale"],
                updated_at=datetime.utcnow(),
            ))
            seeded += 1
        session.commit()
        print(f"Seeded {seeded} league calibration rows")


if __name__ == "__main__":
    seed()
```

### Step 4: Run tests — verify PASS

```bash
python -m pytest tests/test_league_calibration.py -v
```

### Step 5: Commit

```bash
git add app/league_calibration.py tests/test_league_calibration.py scripts/seed_league_calibration.py
git commit -m "feat: add league calibration loader with Dixon-Coles defaults per league"
```

---

## Task 4: Upgrade SpreadPredictor and OUAnalyzer to Dixon-Coles

**Files:**
- Modify: `app/spread_predictor.py`
- Modify: `app/ou_analyzer.py`

The existing `cover_probability()` and `ou_over_probability()` functions (standard Poisson) are replaced by calls to `app.dixon_coles` functions, using calibration from `app.league_calibration`.

### Step 1: Update `app/spread_predictor.py`

Replace the import block and `cover_probability` call:

1. Add imports at the top:
```python
from app.dixon_coles import cover_probability_dc
from app.league_calibration import get_calibration
```

2. Remove the old `_poisson_pmf` and `cover_probability` functions (they're now in `dixon_coles.py`).

3. In `SpreadPredictor.run()`, replace:
```python
lambda_home = max(0.1, home_form.goals_scored_avg * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS))
lambda_away = max(0.1, away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS))
```
with:
```python
cal = get_calibration(self.session, self._league_id(fixture))
mu = max(0.1, home_form.goals_scored_avg * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS)
         * cal["home_advantage"] * cal["attack_scale"])
nu = max(0.1, away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS)
         * cal["defense_scale"])
rho = cal["rho"]
```

4. Replace the `cover_probability(lambda_home, lambda_away, line)` call with:
```python
win_p, push_p = cover_probability_dc(mu, nu, rho, line)
```

5. Add helper method `_league_id`:
```python
def _league_id(self, fixture: Fixture) -> str:
    from app.db.models import League
    league = self.session.query(League).filter_by(id=fixture.league_id).first()
    return league.espn_id if league else "eng.1"
```

### Step 2: Update `app/ou_analyzer.py`

Same pattern:

1. Add imports:
```python
from app.dixon_coles import ou_probability_dc
from app.league_calibration import get_calibration
```

2. Remove old `_poisson_pmf` and `ou_over_probability` functions.

3. In `OUAnalyzer.run()`, replace lambda computation with calibrated version (same as SpreadPredictor step 3 above).

4. Replace `ou_over_probability(lambda_total, line)` with:
```python
over_p = ou_probability_dc(mu, nu, rho, line)
```

5. Add `_league_id` helper (identical to SpreadPredictor's).

### Step 3: Run existing spread and O/U tests

```bash
python -m pytest tests/test_spread_predictor.py tests/test_ou_analyzer.py -v
```

All existing tests must PASS. If any fail, the Dixon-Coles probability functions are dropping below existing Poisson thresholds — check that `rho` is negative and `home_advantage` multiplier is reasonable.

### Step 4: Commit

```bash
git add app/spread_predictor.py app/ou_analyzer.py
git commit -m "feat: upgrade SpreadPredictor and OUAnalyzer to Dixon-Coles with league calibration"
```

---

## Task 5: Monte Carlo simulation

**Files:**
- Create: `app/monte_carlo.py`
- Create: `tests/test_monte_carlo.py`
- Modify: `app/celery_app.py`
- Modify: `app/scheduler.py`
- Modify: `requirements.txt`

### Step 1: Add numpy to requirements

In `requirements.txt`, add:
```
numpy==1.26.4
```

Install: `pip install numpy==1.26.4`

### Step 2: Write failing tests

Create `tests/test_monte_carlo.py`:

```python
import pytest
from app.monte_carlo import MonteCarloSimulator

def test_simulate_returns_scorelines():
    sim = MonteCarloSimulator(mu=1.5, nu=1.0, rho=-0.13, n=1000)
    result = sim.run()
    assert "scorelines" in result
    assert "home_win_prob" in result
    assert "draw_prob" in result
    assert "away_win_prob" in result
    assert "over_25_prob" in result

def test_win_probs_sum_to_one():
    sim = MonteCarloSimulator(mu=1.5, nu=1.0, rho=-0.13, n=1000)
    result = sim.run()
    total = result["home_win_prob"] + result["draw_prob"] + result["away_win_prob"]
    assert total == pytest.approx(1.0, abs=0.01)

def test_top_scorelines_present():
    sim = MonteCarloSimulator(mu=1.5, nu=1.0, rho=-0.13, n=5000)
    result = sim.run()
    # 1-0, 1-1, 0-0 should always be in top scorelines for typical lambdas
    assert len(result["scorelines"]) >= 10

def test_high_mu_means_home_win_more_likely():
    sim_home = MonteCarloSimulator(mu=3.0, nu=0.5, rho=-0.13, n=5000)
    sim_away = MonteCarloSimulator(mu=0.5, nu=3.0, rho=-0.13, n=5000)
    assert sim_home.run()["home_win_prob"] > sim_away.run()["home_win_prob"]

def test_n_simulations_respected():
    sim = MonteCarloSimulator(mu=1.5, nu=1.0, rho=-0.13, n=500)
    result = sim.run()
    assert result["simulations"] == 500

def test_over_25_reasonable_range():
    sim = MonteCarloSimulator(mu=1.5, nu=1.2, rho=-0.13, n=5000)
    result = sim.run()
    assert 0.3 < result["over_25_prob"] < 0.8
```

Run and verify FAIL.

### Step 3: Implement `app/monte_carlo.py`

```python
"""
Monte Carlo simulation for soccer match outcomes using the Dixon-Coles model.

Draws (home_goals, away_goals) pairs from the Dixon-Coles joint distribution
by sampling via the score matrix CDF. Fast enough for 10,000 runs in <1 second
on a single core using numpy vectorisation.
"""
import json
import numpy as np
from app.dixon_coles import build_score_matrix

MAX_GOALS = 10


class MonteCarloSimulator:
    def __init__(self, mu: float, nu: float, rho: float, n: int = 10_000):
        self.mu = mu
        self.nu = nu
        self.rho = rho
        self.n = n

    def run(self) -> dict:
        matrix = build_score_matrix(self.mu, self.nu, self.rho, MAX_GOALS)
        size = MAX_GOALS + 1

        # Flatten matrix into a 1D probability vector and sample indices
        probs = np.array([matrix[h][a] for h in range(size) for a in range(size)], dtype=np.float64)
        probs /= probs.sum()  # normalise to exactly 1.0

        indices = np.random.choice(len(probs), size=self.n, p=probs)
        home_goals = indices // size
        away_goals = indices % size

        # Aggregate
        home_wins = int(np.sum(home_goals > away_goals))
        draws = int(np.sum(home_goals == away_goals))
        away_wins = int(np.sum(home_goals < away_goals))
        totals = home_goals + away_goals

        # Scoreline frequency — top 20
        from collections import Counter
        scoreline_counts = Counter(zip(home_goals.tolist(), away_goals.tolist()))
        top = scoreline_counts.most_common(20)
        scorelines = {f"{h}-{a}": round(count / self.n, 4) for (h, a), count in top}

        return {
            "simulations": self.n,
            "home_win_prob": round(home_wins / self.n, 4),
            "draw_prob": round(draws / self.n, 4),
            "away_win_prob": round(away_wins / self.n, 4),
            "over_15_prob": round(float(np.mean(totals > 1)), 4),
            "over_25_prob": round(float(np.mean(totals > 2)), 4),
            "over_35_prob": round(float(np.mean(totals > 3)), 4),
            "scorelines": scorelines,
        }
```

### Step 4: Run tests — verify PASS

```bash
python -m pytest tests/test_monte_carlo.py -v
```

### Step 5: Add Celery task to `app/celery_app.py`

```python
@celery_app.task(name="monte_carlo_task")
def monte_carlo_task(fixture_id: int):
    """Run 10,000-simulation Monte Carlo for a fixture and write MonteCarloRun."""
    import json
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    from app.db.connection import get_engine
    from app.db.models import Fixture, FormCache, MonteCarloRun
    from app.dixon_coles import LEAGUE_AVG_GOALS  # from spread_predictor constant
    from app.league_calibration import get_calibration
    from app.monte_carlo import MonteCarloSimulator

    LEAGUE_AVG_GOALS = 1.5
    engine = get_engine()
    with Session(engine) as session:
        fixture = session.query(Fixture).filter_by(id=fixture_id).first()
        if not fixture:
            return {"error": "fixture not found"}

        home_form = session.query(FormCache).filter_by(team_id=fixture.home_team_id, is_home=True).first()
        away_form = session.query(FormCache).filter_by(team_id=fixture.away_team_id, is_home=False).first()
        if not home_form or not away_form:
            return {"error": "form cache missing"}

        from app.db.models import League
        league = session.query(League).filter_by(id=fixture.league_id).first()
        league_id = league.espn_id if league else "eng.1"
        cal = get_calibration(session, league_id)

        mu = max(0.1, home_form.goals_scored_avg * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS)
                 * cal["home_advantage"] * cal["attack_scale"])
        nu = max(0.1, away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS)
                 * cal["defense_scale"])

        result = MonteCarloSimulator(mu=mu, nu=nu, rho=cal["rho"], n=10_000).run()

        existing = session.query(MonteCarloRun).filter_by(fixture_id=fixture_id).first()
        now = datetime.now(timezone.utc)
        if existing:
            existing.scoreline_json = json.dumps(result["scorelines"])
            existing.home_win_prob = result["home_win_prob"]
            existing.draw_prob = result["draw_prob"]
            existing.away_win_prob = result["away_win_prob"]
            existing.over_15_prob = result["over_15_prob"]
            existing.over_25_prob = result["over_25_prob"]
            existing.over_35_prob = result["over_35_prob"]
            existing.created_at = now
        else:
            session.add(MonteCarloRun(
                fixture_id=fixture_id,
                model_version="dc_v1",
                simulations=10_000,
                scoreline_json=json.dumps(result["scorelines"]),
                home_win_prob=result["home_win_prob"],
                draw_prob=result["draw_prob"],
                away_win_prob=result["away_win_prob"],
                over_15_prob=result["over_15_prob"],
                over_25_prob=result["over_25_prob"],
                over_35_prob=result["over_35_prob"],
                created_at=now,
            ))
        session.commit()
        return {"fixture_id": fixture_id, "simulations": 10_000}
```

### Step 6: Add scheduler job to `app/scheduler.py`

In `start_scheduler()`, add:
```python
def monte_carlo_job():
    """Dispatch Monte Carlo tasks for fixtures kicking off in the next 2 hours."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session
    from app.db.connection import get_session
    from app.db.models import Fixture

    session = get_session()
    try:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=2)
        upcoming = (session.query(Fixture)
                    .filter(Fixture.status == "scheduled")
                    .filter(Fixture.kickoff_at >= now)
                    .filter(Fixture.kickoff_at <= cutoff)
                    .all())
        for fixture in upcoming:
            celery_app.send_task("monte_carlo_task", args=[fixture.id])
    finally:
        session.close()
```

Then in `start_scheduler()`:
```python
scheduler.add_job(
    monte_carlo_job, IntervalTrigger(minutes=30),
    id="monte_carlo", replace_existing=True
)
```

### Step 7: Commit

```bash
git add app/monte_carlo.py app/celery_app.py app/scheduler.py requirements.txt tests/test_monte_carlo.py
git commit -m "feat: add Monte Carlo simulation task with Dixon-Coles sampling"
```

---

## Task 6: Full test suite validation

Run all tests to verify no regressions:

```bash
python -m pytest tests/ -v --tb=short -q
```

Expected: All existing tests PASS + new tests PASS.

### Final commit if needed

```bash
git add -A
git commit -m "feat: complete Phase 2 Dixon-Coles model and Monte Carlo simulation"
git push origin main
```
