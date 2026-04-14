# Phase 3 — Confidence System: Steam Resistance, Market Blending, Edge Tiers, Calibration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the raw `ev_score` → `confidence_tier` mapping into a professional-grade confidence system. Four layers sit between model output and the dashboard pick: (1) **Market Blending** combines model probability with Pinnacle's implied probability using backtested weights, (2) **Edge Tier Buckets** replace hard EV thresholds with calibrated edge-vs-market buckets and per-tier Kelly fractions, (3) **Steam Resistance** downgrades tiers when sharp money has already moved the line, (4) **Calibration / Brier Score** tracks reliability per model so tiers can be retuned as drift appears. Monte Carlo was already shipped in Phase 2 and is not in scope here.

**Architecture:** Thin composable modules, each pure and testable in isolation. `app/market_blend.py` — stateless blender given (model_p, implied_p, weights). `app/steam_resistance.py` — queries `line_movement` for opening-vs-current spread/total, emits a downgrade flag. `app/edge_tiers.py` — replaces `_confidence_tier` with bucketed tiering + Kelly sizing. `app/calibration.py` — given (prediction, result) pairs compute Brier + reliability curve. `SpreadPredictor` / `OUAnalyzer` are modified to call blend → edge_tier → steam_resistance in that order and persist the new fields. Backtester gains a market-weight fitter (`scripts/fit_market_weights.py`) that writes into a new `market_weights` table.

**Tech Stack:** Python 3.12, numpy, SQLAlchemy 2.x, scipy (for reliability curve binning — already a transitive dep of sklearn from Phase 2).

**Prerequisites:**
- Phase 2 Dixon-Coles plan complete (DC matrix in place).
- Phase 2 ML λ plan complete (ml_enabled path supplies λ when active).
- Phase 2 Data Sources plan complete — `line_movement` hypertable exists and is being populated every 30 min. Steam Resistance is a no-op without it.
- Pinnacle odds flowing into `odds_snapshots` with bookmaker="pinnacle" (used as the market anchor for implied probability).

**Must complete before:** Phase 4 (signal depth) — calibration curves from this phase are what make Phase 4 signal additions measurable.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `app/market_blend.py` | `blend(model_p, implied_p, w1, w2) -> float`; weight lookup from DB |
| Create | `app/steam_resistance.py` | `steam_move_pct(session, fixture_id, market, line, side)`; `downgrade_tier(tier, move_pct)` |
| Create | `app/edge_tiers.py` | `edge_tier(edge_pct)`; `kelly_fraction(tier, edge_pct, odds)`; replaces `_confidence_tier` in both predictors |
| Create | `app/calibration.py` | `brier_score(preds, outcomes)`; `reliability_curve(preds, outcomes, n_bins=10)`; rolling 30-day aggregator |
| Create | `scripts/fit_market_weights.py` | Offline: grid-search w1/w2 on historical spread + O/U predictions, write to `market_weights` |
| Create | `scripts/compute_calibration.py` | Nightly: compute Brier + reliability per (model, bet_type), persist to `calibration_runs` |
| Modify | `app/db/models.py` | Add `MarketWeights`, `CalibrationRun` ORM models; add `kelly_fraction`, `final_probability`, `edge_pct`, `steam_downgraded` columns to `SpreadPrediction` + `OUAnalysis` |
| Create | `migrations/versions/<hash>_phase3_confidence.py` | New tables + prediction column additions |
| Modify | `app/spread_predictor.py` | After DC cover_p, call blend → edge_tier → steam_resistance; persist new fields |
| Modify | `app/ou_analyzer.py` | Same pipeline as spread_predictor |
| Modify | `app/celery_app.py` | Add `calibration_task` (nightly) |
| Modify | `app/scheduler.py` | Schedule `calibration_task` at 03:00 UTC |
| Create | `tests/test_market_blend.py` | Blend math, weight lookup, fallback to (1, 0) when no fit |
| Create | `tests/test_steam_resistance.py` | Line movement queries, downgrade ladder, no-data no-op |
| Create | `tests/test_edge_tiers.py` | Bucket boundaries, Kelly math |
| Create | `tests/test_calibration.py` | Brier properties, reliability binning, monotonicity |
| Create | `tests/test_fit_market_weights.py` | Grid search converges on synthetic data |
| Modify | `tests/test_spread_predictor.py` | Cover new pipeline: blended probability, tier downgrades, Kelly field populated |
| Modify | `tests/test_ou_analyzer.py` | Same |

---

## Task 1: Market Blending

**Files:**
- Create: `app/market_blend.py`
- Create: `tests/test_market_blend.py`
- Add `MarketWeights` ORM to `app/db/models.py`

**Goal:** Given a model probability and the Pinnacle implied probability for the same outcome, return a blended final probability using weights fit offline per (bet_type, league). Fall back to `(w1=1.0, w2=0.0)` (pure model) when no weights row exists for the league/bet_type — new leagues should not be silently zero'd out.

### Step 1: Write blend tests first

- `test_blend_convex_combination`: output strictly between min and max of inputs when w1,w2 both > 0
- `test_blend_defaults_to_model_when_no_implied`: if implied_p is None, return model_p
- `test_blend_weights_must_sum_to_one`: raise ValueError if |w1 + w2 - 1| > 1e-6
- `test_get_weights_falls_back_when_missing`: (1.0, 0.0) for unknown league/bet_type
- `test_get_weights_reads_db_row`: returns stored (w1, w2) when MarketWeights row exists

### Step 2: Implement `app/market_blend.py`

```python
def blend(model_p: float, implied_p: float | None, w1: float, w2: float) -> float:
    if implied_p is None:
        return model_p
    if abs(w1 + w2 - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1: {w1} + {w2}")
    return w1 * model_p + w2 * implied_p


def get_weights(session, league_espn_id: str, bet_type: str) -> tuple[float, float]:
    row = session.query(MarketWeights).filter_by(
        league_espn_id=league_espn_id, bet_type=bet_type
    ).first()
    if row is None:
        return 1.0, 0.0
    return row.w_model, row.w_market
```

### Step 3: Add `MarketWeights` ORM

```python
class MarketWeights(Base):
    __tablename__ = "market_weights"
    id = Column(Integer, primary_key=True)
    league_espn_id = Column(String, nullable=False)
    bet_type = Column(String, nullable=False)  # "spread" | "ou"
    w_model = Column(Float, nullable=False)
    w_market = Column(Float, nullable=False)
    fitted_at = Column(DateTime)
    n_samples = Column(Integer)
    # unique per (league, bet_type)
```

**Acceptance:** `pytest tests/test_market_blend.py` green.

---

## Task 2: Edge Tier Buckets + Kelly Sizing

**Files:**
- Create: `app/edge_tiers.py`
- Create: `tests/test_edge_tiers.py`

**Goal:** Replace the `_confidence_tier(ev)` helpers in both predictors with a shared module that buckets on **edge vs market** (not raw EV) and returns both a tier and a Kelly fraction. Edge = `final_p - implied_p` (i.e., the blended probability minus Pinnacle's implied probability).

### Bucket definition (from design spec §4.8)

| Edge | Tier | Kelly fraction |
|---|---|---|
| < 2% | SKIP | 0.0 |
| 2–5% | MEDIUM | 0.10 × full_kelly |
| 5–10% | HIGH | 0.15 × full_kelly |
| ≥ 10% | ELITE | 0.25 × full_kelly |

`full_kelly = (b*p - q) / b` where `b = decimal_odds - 1`, `p = final_p`, `q = 1 - p`. Clamp Kelly to ≥ 0 (never short).

### Step 1: Write tier tests first

- Bucket boundaries (exactly 0.02, 0.05, 0.10) fall into the upper tier
- Negative edge → SKIP, Kelly = 0.0
- Kelly math matches analytic formula for a known case
- Kelly clamped to 0 when full_kelly is negative

### Step 2: Implement `app/edge_tiers.py`

```python
def edge_tier(edge_pct: float) -> str:
    if edge_pct < 0.02: return "SKIP"
    if edge_pct < 0.05: return "MEDIUM"
    if edge_pct < 0.10: return "HIGH"
    return "ELITE"


TIER_KELLY_MULT = {"SKIP": 0.0, "MEDIUM": 0.10, "HIGH": 0.15, "ELITE": 0.25}


def kelly_fraction(tier: str, final_p: float, decimal_odds: float) -> float:
    if tier == "SKIP" or decimal_odds <= 1.0:
        return 0.0
    b = decimal_odds - 1.0
    full = (b * final_p - (1.0 - final_p)) / b
    return max(0.0, full * TIER_KELLY_MULT[tier])
```

**Acceptance:** `pytest tests/test_edge_tiers.py` green; all boundary tests pass.

---

## Task 3: Steam Resistance

**Files:**
- Create: `app/steam_resistance.py`
- Create: `tests/test_steam_resistance.py`

**Goal:** Given a fixture and the model's pick direction, measure how much the Pinnacle line has already moved since it opened. If movement is ≥2% in the model's favour, downgrade one tier.

### Logic

- Query `line_movement` for `(fixture_id, book="pinnacle", market="spread"|"ou")` ordered by `recorded_at`.
- `opening = first row`, `current = last row`.
- **Spread:** move_pct = fraction of line shift toward pick's side, measured in American odds terms — `(current_odds - opening_odds) / abs(opening_odds)`. Positive if odds shortened on the pick side.
- **O/U:** same formula applied to over_odds (if pick is "over") or under_odds (if pick is "under").
- If move_pct ≥ 0.02 AND same direction as pick → downgrade.

### Step 1: Write steam tests first

- `test_no_movement_no_change`: move_pct 0, tier unchanged
- `test_move_below_threshold_no_change`: move_pct 0.01, tier unchanged
- `test_move_at_threshold_downgrades`: move_pct exactly 0.02 downgrades one step
- `test_opposite_direction_no_change`: line moved against pick, tier unchanged
- `test_no_line_movement_rows_is_noop`: missing data never raises, returns original tier
- `test_elite_downgrades_to_high`, `test_high_to_medium`, `test_medium_to_skip`

### Step 2: Implement `app/steam_resistance.py`

```python
DOWNGRADE_LADDER = {"ELITE": "HIGH", "HIGH": "MEDIUM", "MEDIUM": "SKIP", "SKIP": "SKIP"}
THRESHOLD = 0.02


def steam_move_pct(session, fixture_id, market, pick_side) -> float:
    # returns signed move pct in pick's direction, or 0.0 if no data
    ...


def apply_steam(tier: str, move_pct: float) -> tuple[str, bool]:
    if move_pct >= THRESHOLD:
        return DOWNGRADE_LADDER[tier], True
    return tier, False
```

**Acceptance:** `pytest tests/test_steam_resistance.py` green.

---

## Task 4: Wire New Pipeline Into Predictors

**Files:**
- Modify: `app/spread_predictor.py`
- Modify: `app/ou_analyzer.py`
- Modify: `tests/test_spread_predictor.py`, `tests/test_ou_analyzer.py`

**Goal:** Replace the current `ev_score → _confidence_tier` path with the full Phase 3 pipeline:

1. DC matrix → raw `cover_p` (or `over_p`) — unchanged.
2. `implied_p = 1 / pinnacle_odds` for the matching line.
3. `w1, w2 = get_weights(session, league_espn_id, bet_type)`.
4. `final_p = blend(cover_p, implied_p, w1, w2)`.
5. `edge = final_p - implied_p` (None if no odds snapshot).
6. `tier = edge_tier(edge)`.
7. `tier, downgraded = apply_steam(tier, steam_move_pct(...))`.
8. `kelly = kelly_fraction(tier, final_p, decimal_odds)`.
9. Persist: `cover_probability` (raw DC), `final_probability` (blended), `edge_pct`, `ev_score` (kept for compat = edge), `confidence_tier`, `steam_downgraded`, `kelly_fraction`.

### New columns on `SpreadPrediction` and `OUAnalysis`

- `final_probability: Float`  (blended)
- `edge_pct: Float`  (final_p - implied_p)
- `kelly_fraction: Float`
- `steam_downgraded: Boolean`

`ev_score` stays — now redundantly equals `edge_pct`, but preserved so legacy API consumers don't break in one shot.

### Tests

- `test_spread_predictor_applies_blend_when_weights_exist`
- `test_spread_predictor_falls_back_to_model_when_no_weights`
- `test_spread_predictor_downgrades_on_steam`
- `test_spread_predictor_sets_kelly_on_high_tier`
- Mirror tests for `ou_analyzer.py`.

**Acceptance:** Existing suite still green; new assertions on blended probability / steam / kelly pass.

---

## Task 5: Offline Market-Weight Fitter

**Files:**
- Create: `scripts/fit_market_weights.py`
- Create: `tests/test_fit_market_weights.py`

**Goal:** For each (league, bet_type) pair with ≥200 settled predictions, find `(w1, w2)` on the simplex `{w1+w2=1, w1,w2 ≥ 0}` minimising Brier score against realised outcomes. Grid search at 0.05 resolution is sufficient (21 points) — no need for gradient methods.

### Algorithm

```python
def fit(session, league_espn_id, bet_type, min_samples=200):
    triples = _load_settled(session, league_espn_id, bet_type)  # (model_p, implied_p, outcome)
    if len(triples) < min_samples:
        raise InsufficientDataError(...)
    best = None
    for w1 in np.arange(0, 1.01, 0.05):
        w2 = 1 - w1
        preds = np.array([w1*m + w2*i for m, i, _ in triples])
        outs = np.array([o for _, _, o in triples])
        brier = np.mean((preds - outs)**2)
        if best is None or brier < best[2]:
            best = (w1, w2, brier)
    _upsert_weights(session, league_espn_id, bet_type, *best, n=len(triples))
    return best
```

Outcomes for spread: `1` if home cover, `0` otherwise, keyed to the pick side on the stored prediction. For O/U: `1` if over hit, `0` otherwise, keyed to `direction`.

### Tests

- Converges to `(1, 0)` on synthetic data where model is perfectly calibrated and market is noise
- Converges to `(0, 1)` where model is noise and market is perfectly calibrated
- Raises `InsufficientDataError` below min_samples
- Upsert replaces existing row for same (league, bet_type)

**Acceptance:** `pytest tests/test_fit_market_weights.py` green.

---

## Task 6: Calibration & Brier Tracking

**Files:**
- Create: `app/calibration.py`
- Create: `tests/test_calibration.py`
- Create: `scripts/compute_calibration.py`
- Add `CalibrationRun` ORM to `app/db/models.py`

**Goal:** Nightly job computes rolling-30-day Brier + reliability curve per (model_id, bet_type) and persists it. Phase 3 exit criterion is a recorded baseline Brier; Phase 5 will alert on drift.

### `app/calibration.py`

```python
def brier_score(preds: np.ndarray, outcomes: np.ndarray) -> float:
    return float(np.mean((preds - outcomes) ** 2))


def reliability_curve(preds, outcomes, n_bins=10) -> list[dict]:
    # returns [{"bin_low":0.0,"bin_high":0.1,"mean_pred":...,"hit_rate":...,"n":...}, ...]
```

### `CalibrationRun` ORM

```python
class CalibrationRun(Base):
    __tablename__ = "calibration_runs"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    bet_type = Column(String, nullable=False)
    window_days = Column(Integer, default=30)
    brier_score = Column(Float)
    n_samples = Column(Integer)
    reliability_json = Column(Text)  # JSON-encoded reliability curve
    computed_at = Column(DateTime, default=datetime.utcnow)
```

### Tests

- `brier_score` matches analytic value on known case (0.25 for 50/50 prediction on coin flip)
- Perfect predictions → 0
- Reliability curve: n_bins buckets, hit_rate monotonic on well-calibrated synthetic data
- Empty bins excluded

### Scheduler

- `calibration_task` dispatched from `app/celery_app.py`
- APScheduler cron at 03:00 UTC daily in `app/scheduler.py`

**Acceptance:** Nightly run writes a row per (active model, bet_type); tests green.

---

## Task 7: Alembic Migration

**Files:**
- Create: `migrations/versions/<hash>_phase3_confidence.py`

**Contents:**
- `CREATE TABLE market_weights` with unique index on `(league_espn_id, bet_type)`
- `CREATE TABLE calibration_runs`
- `ALTER TABLE spread_predictions ADD COLUMN final_probability`, `edge_pct`, `kelly_fraction`, `steam_downgraded`
- `ALTER TABLE ou_analysis ADD COLUMN final_probability`, `edge_pct`, `kelly_fraction`, `steam_downgraded`

Generate with `alembic revision --autogenerate -m "phase3_confidence"` after ORM updates land; hand-edit if autogen misses the hypertable-aware bits.

**Acceptance:** `alembic upgrade head` applies cleanly on a fresh SQLite and on the Postgres dev DB.

---

## Task 8: Dashboard + API Exposure (lightweight)

**Files:**
- Modify: `app/api/picks.py` (or whichever FastAPI route returns picks)
- Modify: `tests/test_api/test_picks.py`

**Goal:** Add `final_probability`, `edge_pct`, `kelly_fraction`, `steam_downgraded` to the picks response schema. Dashboard rendering is out of scope for this plan — the frontend work belongs in the Phase 5 dashboard plan.

**Acceptance:** API contract tests updated; response JSON includes new fields; existing consumers don't break.

---

## Exit Criteria

- [ ] All new tests green; full suite ≥ current count, 100% pass.
- [ ] Alembic migration applies both up and down.
- [ ] A single `market_weights` row exists per tracked league+bet_type (from `scripts/fit_market_weights.py`), OR falls back to (1.0, 0.0) cleanly.
- [ ] One `calibration_runs` row written by the nightly job (or a manual invocation).
- [ ] `ev_score` values on new predictions equal `edge_pct` (final_p - implied_p), not raw EV.
- [ ] At least one fixture in testing demonstrates a Steam Resistance tier downgrade.
- [ ] Kelly fraction is populated and non-negative for all non-SKIP picks.
- [ ] Commit pushed to origin/main: `feat: Phase 3 confidence system — market blending, edge tiers, steam resistance, calibration`.

---

## Out of Scope (Deferred to Phase 5)

- Calibration **alerting** — drift detection cron, Slack/email hooks.
- Reliability-curve **rendering** — dashboard chart.
- Unit Tracker — per-pick bankroll simulation using the new Kelly field.
- Model-retraining pipeline triggered by Brier drift.
