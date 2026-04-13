# Soccer Prediction Application — Extension Design

**Date:** 2026-04-12
**Extends:** `2026-03-27-soccer-betting-model-design.md`
**Architecture:** FastAPI + React (Vite) — Two Services + Celery/Redis Workers
**Deployment:** Multiverse K8s Cluster — Tenant B (`tenant-b` namespace)
**Primary Backtest League:** Premier League (highest data availability, sharpest lines, highest parity)

---

## 1. Goals

Extend the existing soccer betting model into a professional-grade prediction system focused on:

- American-style spread picks (goal-line: -0.5, +0.5, -1, +1, -1.5, +1.5)
- Over/Under total goals with in-depth statistical analysis
- Combined spread + O/U analysis per fixture
- Data-learned weights via XGBoost/LightGBM (replacing heuristic weighting)
- Dixon-Coles model replacing standard Poisson (industry-standard upgrade)
- Monte Carlo simulation (10,000 runs per fixture) for probability distributions
- Market blending (model probability + Pinnacle implied probability)
- Web dashboard showing only high-confidence picks ranked by expected value
- Personal bet tracking with P&L history

---

## 2. League Scope

| League | Country | xG Source | Notes |
|---|---|---|---|
| Premier League | England | Understat | Existing — already collecting |
| La Liga | Spain | Understat | Existing — already collecting |
| Bundesliga | Germany | Understat | Existing — already collecting |
| Serie A | Italy | Understat | Existing — already collecting |
| Ligue 1 | France | Understat | New — add league key to collector |
| Champions League | Europe | FBref | New — requires separate xG source |

---

## 3. Data Sources

| Source | Purpose | Method | Cost |
|---|---|---|---|
| The Odds API *(existing)* | Spread + O/U lines, multi-book odds, Pinnacle sharp line, line movement | REST API | Paid (existing key) |
| ESPN API *(existing)* | Fixtures, results, basic team data, injury reports | REST API | Free |
| Understat *(new)* | xG, xG per shot, big chances, PPDA pressing metrics — top 5 leagues | Scrape | Free |
| FBref *(new)* | UCL xG, PSxG for keepers, game state stats, set piece data | Scrape | Free |
| API-Football *(new)* | Confirmed lineups (~1hr pre-kickoff), referee data, player stats, red card events | REST API | Paid (new key required) |
| OpenWeatherMap *(new)* | Match day weather per stadium | REST API | Free tier sufficient |

### 3.1 Scraping Strategy (Understat + FBref)

- Rate limiting: 2-3 second delay between page fetches
- Aggressive caching: only fetch data changed since last collection, not full re-scrapes
- Rotating user agents: cycle through common browser user-agent strings
- Retry with exponential backoff on 429/503 responses
- Collection frequency: every 6 hours for match/stat data (low traffic, unlikely to trigger Cloudflare)
- No proxy service needed initially — upgrade path available if collection frequency increases

---

## 4. Prediction Algorithm

Every fixture runs through 6 signal layers, producing an expected goals value per team that feeds into the Dixon-Coles model. XGBoost/LightGBM learns the optimal weighting across all layers from historical data.

### Layer 1 — Recent Form (Last 5 Games)

Primary signal. Home and away form tracked separately.

| Signal | Applied To |
|---|---|
| Goals scored per game | O/U projection |
| Goals conceded per game | O/U projection |
| xG scored per game | O/U projection (truer than raw goals) |
| xG conceded per game | O/U projection |
| xG per shot + big chances created/conceded | Shot quality distribution — differentiates 10 low-quality shots from 3 big chances |
| Home form (last 5 home) | Spread pick |
| Away form (last 5 away) | Spread pick |
| Spread cover rate last 5 | Spread pick confidence |
| O/U hit rate last 5 | O/U confidence |
| Goals scored/conceded after 70th minute | Late game O/U signal |

**Red Card Normalization:** Matches where a red card occurred before the 60th minute are flagged in `form_cache`. These matches receive 0.25x weight in form calculations (effectively treated as 1/4 of a normal match). Matches with a red card after the 60th minute receive 0.75x weight. This prevents outlier results (e.g., 4-0 loss with 10 men from 10th minute) from poisoning the model's form assessment and XGBoost training data. Weights are configurable in the app ConfigMap.

### Layer 2 — Team Context

| Signal | Applied To |
|---|---|
| H2H record (last 6 meetings, low weight) | Both — minimal weight, mostly noise except extreme rivalries |
| Rest days since last match (both teams) | Performance modifier |
| Fixture congestion (games in last 14 days) | Performance modifier |
| Motivation index — title race, relegation, dead rubber, cup priority | Spread + O/U modifier |
| Manager tenure modifier — new manager (<3 games): discard pre-appointment form, apply intensity boost | Layer 1 override |
| Travel distance (km) — away team travel | Performance modifier (UCL primary, domestic reduced weight) |
| Travel fatigue flag — UCL midweek + domestic weekend within 72hrs | High fatigue penalty |
| Back-to-back travel — 2+ long-haul trips in 7 days | Cumulative fatigue penalty |
| Draw Propensity Score (see Section 4.1) | Spread + O/U modifier |
| UCL Sandwich Rotation Probability (see Section 4.2) | Expected strength modifier |
| Game state behavior — does team shut down or keep attacking when leading? | Late O/U accuracy |

### Layer 3 — Key Player Impact

| Signal | Applied To |
|---|---|
| Player xG contribution % — absent player's % of team season xG | Precise spread + O/U modifier |
| Primary playmaker absent (5+ assists/season) | O/U modifier |
| First-choice GK absent | Spread + O/U modifier |
| PSxG +/- (keeper over/under performance vs expected) | O/U modifier — hot keeper flagged for mean reversion |
| Confirmed lineup (API-Football, ~1hr pre-kickoff) | Overrides injury estimates when available |
| Bench quality index — proxy for late game substitution impact | Late O/U modifier |

### Layer 4 — Style, Tactics & Officials

| Signal | Applied To |
|---|---|
| Tactical archetype — High Press / Low Block / Counter-Attack / Possession | xG adjustment |
| Style clash penalty — High Press vs high Press Resistance (PPDA + dribble success) | Downward xG modifier for pressing team |
| PPDA (Passes Allowed Per Defensive Action) | Tactical archetype input (from Understat) |
| Set piece % of goals scored/conceded | O/U upward modifier |
| Aerial duel win rate | Set piece threat signal |
| Referee profile — fouls/tackle, penalty rate, cards/game | O/U modifier + volatility flag |
| Referee + aggressive defense pairing — strict ref + high-foul team | Penalty/red card risk — O/U upward modifier |
| UCL aggregate context — team down on aggregate plays more open | Spread + O/U modifier |

### Layer 5 — Market Intelligence

| Signal | Applied To |
|---|---|
| Pinnacle opening line — sharpest baseline for implied probability | EV calculation baseline |
| Current spread line (all books) | EV calculation |
| Current O/U line (all books) | EV calculation |
| Line movement — direction + magnitude since open | Sharp action signal |
| Sharp vs soft book divergence — Pinnacle vs recreational books | Confidence signal |
| Multi-book best available number | Output — show best odds |
| CLV tracking — model odds vs closing odds per bet | Edge validation metric |
| Steam Resistance (see Section 4.3) | Confidence tier downgrade when value is gone |

### Layer 6 — Environment

| Signal | Applied To |
|---|---|
| Wind speed at stadium x enclosure rating | O/U downward modifier (adjusted for stadium architecture) |
| Precipitation (rain/snow) | O/U downward modifier |
| Temperature extremes | Minor performance modifier |

**Stadium Enclosure Rating:** A static `stadium_profiles` table maps each stadium to an enclosure rating (Open / Semi-Enclosed / Closed). The wind modifier is multiplied by this rating — 20mph wind at an open-bowl stadium has full impact, the same wind at a roofed stadium (e.g., Tottenham Hotspur Stadium) has near-zero impact. This prevents artificially dropping xG for enclosed venues.

Note: Weather signals receive reduced weight overall for top leagues — sharp books already price this. Primary value is in UCL fixtures at unusual venues and open-bowl domestic stadiums.

---

### 4.1 Draw Propensity Score

A composite signal identifying fixtures where one or both teams are tactically targeting a draw.

**Inputs:**

| Signal | Measurement |
|---|---|
| Manager draw tendency as underdog | Historical draw % vs top-6 opponents away |
| Table utility calculation | Is a draw mathematically optimal given standings? |
| Match importance asymmetry | One team needs 3pts, the other is fine with 1 |
| Defensive setup trend | xG conceded trend last 3 games — increasingly defensive? |
| UCL aggregate context | Team holding advantage in second leg |
| Historical tactical pattern | Manager's setup against this specific opponent |

**When the score is HIGH:**
- Spread: reduces cover probability for the favorite — team playing for draw won't press to cover -1.5
- O/U: shifts toward under — 0-0, 1-0, 1-1 weighted higher in Dixon-Coles matrix
- Dashboard: surfaces as `Draw Propensity: HIGH` flag

**Example:** Arsenal leading the league table, visiting Man City who must win all remaining games. Arsenal's motivation is to protect the lead (draw = good result). Arteta's historical setup at the Etihad is defensive. Model flags Draw Propensity HIGH for Arsenal, adjusts Dixon-Coles to weight 0-0, 1-0, 1-1 scorelines higher, downgrades City -1.5 confidence, flags Under 2.5 as the stronger play.

---

### 4.2 UCL Sandwich Rotation Probability

Identifies domestic fixtures where a top team is likely to field a weakened squad due to an upcoming or recent Champions League match.

**Trigger conditions:**
- Team has a UCL fixture within 72 hours (before or after)
- The UCL fixture is knockout stage
- The domestic fixture is NOT flagged as "Must Win" by the Motivation Index

**When triggered:**
- Apply Rotation Penalty to the team's expected strength before confirmed lineups are available
- Dashboard flag: `UCL Rotation Risk: HIGH`
- Once confirmed lineup drops (API-Football, ~1hr pre-kickoff), the actual lineup overrides this estimate

**Why this differs from travel fatigue:** Travel fatigue is physical. Rotation risk is tactical — the manager chooses to field a weaker team. Both can apply simultaneously.

---

### 4.3 Steam Resistance

Protects against betting on stale value where sharp money has already moved the line.

**Rule:** If the current line has moved >2% from the opening line in the same direction as the model's pick, downgrade confidence one tier:
- ELITE → HIGH
- HIGH → MEDIUM
- MEDIUM → SKIP

**Dashboard flag:** `Steam Resistance: line already moved [X]% in your direction`

**Rationale:** If your model finds +5% EV but Pinnacle has already moved 4% in that direction in the last few hours, the alpha is likely gone. You'd be arriving at the tail end of a sharp move.

---

### 4.4 Dixon-Coles Model

Replaces standard Poisson distribution. Adds:
- Correlation correction for low-scoring results (0-0, 1-0, 0-1, 1-1 — systematically underestimated by standard Poisson)
- Time decay weighting — recent matches automatically weighted more heavily
- League-specific calibration factors (EPL high parity/fast tempo, Serie A tactical/low scoring, Bundesliga high scoring, etc.)
- Generates full scoreline probability matrix feeding spread cover probability and O/U probability

---

### 4.5 XGBoost/LightGBM Learned Weights

Replaces heuristic weighting of signal layers.

**Training:**
- Historical matches across all leagues as training data
- Input features: all Layer 1–6 signals
- Output targets: spread cover (1/0), O/U hit (1/0)
- Learns nonlinear interactions automatically (fatigue x travel, referee x aggressive team, weather x playstyle, red card context x form)

**Training run history and feature importance stored in `backtest_ml` table.**

---

### 4.6 Market Blending

Final probability is a blend of model output and market signal:

```
Final Prob = w1 x Model Prob + w2 x Pinnacle Implied Prob
```

Weights (`w1`, `w2`) learned via backtesting — prevents the model from being overconfident against an efficient market. Stabilizes long-term ROI.

---

### 4.7 Monte Carlo Simulation

Instead of a single Dixon-Coles output, simulate 10,000 matches per fixture:
- Includes randomness and variance
- Produces a probability distribution for spread outcomes and total goals
- Captures tail risk (e.g., 5% chance of a 5+ goal blowout)
- Primary method for O/U line value assessment
- Executed by Celery workers (CPU-heavy, must not block API)

---

### 4.8 Confidence System — Calibration + Edge Buckets

Replaces simple probability threshold with Brier Score calibration curves.

| Edge vs Pinnacle | Tier | Kelly Fraction |
|---|---|---|
| 0–2% | SKIP | No bet |
| 2–5% | MEDIUM | 0.10 Kelly |
| 5–10% | HIGH | 0.15 Kelly |
| 10%+ | ELITE | 0.25 Kelly |

Kelly fraction is configurable. Default is 1/4 Kelly at the ELITE tier. Full Kelly is mathematically optimal but emotionally brutal during variance streaks.

Steam Resistance (Section 4.3) can downgrade a tier regardless of edge calculation.

---

### 4.9 Model Decay and Data Drift Detection

Soccer metas shift — rule changes, referee instruction changes, tactical trends. XGBoost weights trained on historical data will decay over time.

**Automated monitoring:**
- Rolling 30-day Brier Score evaluation via cron job
- If Brier Score degrades beyond configurable threshold → alert triggered
- Alert triggers retraining pipeline with heavier time decay on historical data (recent matches weighted more)
- Jenkins pipeline stage for automated retraining with human approval gate before deploying new weights to production
- Feature importance drift tracking — flag when a signal's importance changes significantly (e.g., referee penalties spike due to rule change)

---

### 4.10 Output Per Fixture

| Output | Description |
|---|---|
| Spread pick | Best goal-line + cover probability % |
| O/U pick | Over or Under + probability % |
| EV score | Model prob minus Pinnacle implied prob |
| Kelly fraction | Recommended bet size by confidence tier |
| Confidence tier | ELITE / HIGH / MEDIUM / SKIP |
| Key flags | Draw Propensity, UCL Rotation Risk, Steam Resistance, travel fatigue, lineup confirmed, referee alert, mean reversion risk, sharp line movement, motivation asymmetry, red card normalization applied |
| Best available odds | Book showing best number for this pick |
| Dixon-Coles top 5 scorelines | Most probable exact scores with percentages |

---

## 5. Dashboard

### 5.1 Architecture

React (Vite) SPA served by nginx container. Connects to FastAPI REST API within the cluster. Mobile responsive — designed for checking picks on your phone before kickoff.

### 5.2 Main View — Today's Picks

Default landing page. Filtered to HIGH and ELITE only, sorted by edge tier then EV.

Each pick card shows:
- Confidence tier badge (ELITE / HIGH)
- Spread pick + cover probability + EV
- O/U pick + probability + EV
- Kelly fraction (recommended units)
- Kickoff time
- Key flags inline — travel fatigue, lineup confirmed, sharp movement, draw propensity, UCL rotation risk, steam resistance, referee alert

Expandable to full signal breakdown on click.

### 5.3 Expanded Pick View

Full fixture breakdown on click:

- **Form table** — last 5, home/away split, xG, goals, cover rate, O/U rate, shot quality, late goals
- **Red card normalization** — flagged if any recent match was de-weighted
- **Key player impact** — absent players with xG contribution %, PSxG for keepers
- **Tactical matchup** — archetype vs archetype, style clash assessment, PPDA
- **Market data** — Pinnacle line, best book, line movement chart, sharp/soft divergence, steam resistance status
- **Dixon-Coles scorelines** — top 5 most probable exact scores with percentages
- **Draw Propensity** — score with input breakdown
- **UCL Rotation Risk** — flag with reasoning
- **League calibration** — which factor was applied
- **Referee profile** — fouls/tackle, penalty rate, cards/game
- **Weather** — conditions at stadium with enclosure rating context (if material)
- **Motivation context** — table position, what each team is playing for

### 5.4 Secondary Views

| View | Content |
|---|---|
| This Week | 7-day lookahead, grouped by league and day |
| UCL | Champions League only — aggregate context in knockout rounds, rotation risk flags |
| My Bets (Unit Tracker) | Log bets, track P&L by league, bet type, confidence tier |
| Model Performance | Accuracy + ROI per model, CLV % trend, calibration curve, Brier Score, feature importance chart |

### 5.5 Unit Tracker

Separate from model predictions — tracks actual bets placed by the user.

**Records per bet:** fixture, bet type (spread/O/U), pick, stake (units), odds, book, confidence tier, result

**Displays:**
- Win/loss record (overall and per league)
- P&L by league — are you profitable in Serie A but losing in Ligue 1?
- P&L by bet type — spread vs O/U, where is your edge?
- P&L by confidence tier — are ELITE picks actually outperforming HIGH?
- Streak tracking — current win/loss streak
- ROI % over time
- CLV validation — did your picks beat the closing line?
- Model vs You — how do your actual bets compare to what the model recommended? Shows whether you add edge by filtering picks (good) or leave money on the table by second-guessing (bad)

---

## 6. FastAPI Service

### 6.1 Endpoints

```
GET  /picks/today          — HIGH + ELITE picks, sorted by EV
GET  /picks/week           — 7-day lookahead
GET  /picks/ucl            — UCL only with aggregate context
GET  /fixture/{id}         — full signal breakdown for expanded view
GET  /performance          — model accuracy, CLV, Brier Score, feature importance
GET  /units                — unit tracker P&L summary
GET  /units/history        — full bet history with filters
POST /units/bet            — log a bet
GET  /jobs/{id}/status     — check Celery task status (Monte Carlo, retraining)
```

### 6.2 Deployment

- Separate K8s Deployment in `tenant-b` namespace
- ClusterIP service — only reachable within the cluster
- Ingress routes `soccer.yourdomain.com/api/` to this service
- Does NOT execute heavy compute — triggers Celery tasks and returns 202 Accepted

---

## 7. Infrastructure

### 7.1 Kubernetes Layout

All services in `tenant-b` namespace on the Multiverse cluster.

```
tenant-b namespace
├── prediction-engine/
│   ├── deployment.yaml       (existing — extended with new collectors + signals)
│   ├── configmap.yaml        (add Ligue 1, UCL league keys + schedules)
│   └── secret.yaml           (add API-Football key, OpenWeatherMap key)
├── postgres/
│   ├── statefulset.yaml      (existing — TimescaleDB extension added)
│   └── service.yaml          (existing — unchanged, ClusterIP)
├── redis/
│   ├── deployment.yaml       (new — message broker for Celery)
│   └── service.yaml          (new — ClusterIP)
├── celery-worker/
│   ├── deployment.yaml       (new — scalable replicas for background compute)
│   └── configmap.yaml        (new — worker concurrency + queue config)
├── fastapi/
│   ├── deployment.yaml       (new)
│   └── service.yaml          (new — ClusterIP)
├── dashboard/
│   ├── deployment.yaml       (new — nginx serving React build)
│   └── service.yaml          (new — ClusterIP)
└── ingress.yaml              (existing placeholder — activated)
```

### 7.2 Async Task Queue — Celery + Redis

Heavy background processing runs in dedicated Celery workers, not in FastAPI or the prediction engine.

**Tasks handled by Celery:**
- Monte Carlo simulation (10,000 runs per fixture — CPU-heavy)
- Understat + FBref scraping (I/O-bound, rate-limited)
- Line movement polling (every 30 minutes across all tracked fixtures)
- XGBoost/LightGBM retraining (triggered by drift alerts or manual)
- Dixon-Coles calibration recalculation

**Flow:**
```
FastAPI / Scheduler → triggers task → Redis queue → Celery worker → writes to PostgreSQL
```

**Redis deployment:** Single pod, minimal memory footprint — used only as a message broker, not as a cache. Longhorn PVC for persistence so queued tasks survive pod restarts.

**Celery worker scaling:** Start with 2 replicas. Scale up during peak fixture windows (Saturday 3pm EPL + UCL midweek). Worker concurrency configurable via ConfigMap.

### 7.3 Ingress Routes

```
soccer.yourdomain.com/        → React dashboard (dashboard service)
soccer.yourdomain.com/api/    → FastAPI service (fastapi service)
```

NGINX Ingress class, MetalLB external IP (192.168.1.240 range).

### 7.4 TimescaleDB Extension

The `line_movement` table tracks odds snapshots every 30 minutes across 6 leagues. At ~60-80 fixtures per week with spread + O/U lines across multiple books, this table accumulates millions of rows per season.

**TimescaleDB** is a PostgreSQL extension (not a separate database) — installed on the existing Postgres StatefulSet:
- Converts `line_movement` to a hypertable — time-series queries stay fast regardless of table size
- Automatic compression for data older than 30 days
- Retention policies — drop or archive data older than 2 seasons
- No architectural change — just `CREATE EXTENSION timescaledb` and `SELECT create_hypertable()`

### 7.5 New API Keys Required

| Service | Purpose | Storage |
|---|---|---|
| API-Football | Lineups, referee, player stats, red card events | K8s Secret |
| OpenWeatherMap | Match day weather per stadium | K8s Secret |

Understat and FBref are scraped — no keys needed.

---

## 8. Database Schema — New Tables

All added via Alembic migrations. Existing tables unchanged.

| Table | Purpose | Notes |
|---|---|---|
| `spread_predictions` | American-style goal-line picks per fixture/model | |
| `ou_analysis` | Deep O/U signal breakdown per fixture | |
| `form_cache` | Last 5 game stats + xG per team, home/away split, shot quality, late goals | Includes red card normalization flag |
| `line_movement` | Odds snapshots every 30min per tracked fixture | TimescaleDB hypertable |
| `player_impact` | Player xG contribution %, injury status, PSxG for keepers | |
| `draw_propensity` | Draw Propensity Score inputs + final score per fixture | |
| `manager_profiles` | Tenure, draw tendency, tactical archetype, rotation history per manager | |
| `referee_profiles` | Fouls/tackle, penalty rate, cards/game per referee | |
| `tactical_profiles` | Team archetype, PPDA, press resistance per team per season | |
| `stadium_profiles` | Stadium name, enclosure rating (Open/Semi-Enclosed/Closed), GPS coordinates | Static — manual seed + updates |
| `unit_tracker` | Logged bets — stake, result, P&L | |
| `backtest_ml` | XGBoost/LightGBM training runs, feature importance, hyperparameters | |
| `league_calibration` | Dixon-Coles calibration factors per league | |
| `monte_carlo_runs` | Simulation results — scoreline distribution per fixture | |
| `market_blend` | Blended probabilities (model + Pinnacle) per fixture | |
| `steam_resistance_log` | Line movement alerts + confidence downgrades | |
| `rotation_flags` | UCL sandwich rotation probability per fixture | |
| `model_drift` | Rolling Brier Score, drift alerts, retraining trigger history | |

---

## 9. CI/CD — Jenkins

Extends existing Jenkinsfile with new stages:

```
1. Checkout              (existing)
2. Test                  (existing — extended with new test suites)
3. Build Engine          (existing — prediction engine image)
4. Build API             (new — FastAPI service image)
5. Build Worker          (new — Celery worker image, shares codebase with engine)
6. Build Dashboard       (new — npm build → nginx Docker image)
7. Push                  (push all images to registry)
8. Deploy                (kubectl apply covers all services)
```

**Model retraining pipeline** (separate Jenkinsfile):
```
1. Trigger               (manual or automated via drift alert)
2. Pull training data    (export from PostgreSQL)
3. Train XGBoost         (run training script)
4. Evaluate              (compare Brier Score vs current production model)
5. Approval gate         (human review of metrics before promotion)
6. Deploy weights        (update model weights ConfigMap, rolling restart)
```

---

## 10. Implementation Phases

| Phase | Work | Impact |
|---|---|---|
| 1 | Ligue 1 + UCL data collection, spread predictions, enhanced O/U, red card normalization, FastAPI + React scaffold, Redis + Celery infrastructure | Core functionality live |
| 2 | Dixon-Coles model, XGBoost/LightGBM learned weights, CLV validation, TimescaleDB migration | Model accuracy leap |
| 3 | Market blending, calibration curves, edge tiers, Monte Carlo simulation, Steam Resistance | Professional-grade confidence system |
| 4 | Shot quality, game state behavior, late goals, league calibration, Draw Propensity Score, UCL Sandwich Rotation, tactical archetypes + PPDA, stadium enclosure ratings | Signal depth |
| 5 | Unit Tracker, full dashboard views, model performance charts, referee profiles, model decay/drift alerting, retraining pipeline | User-facing completeness + MLOps |

---

## 11. Out of Scope (This Phase)

- Automated bet placement (manual review + unit tracker only)
- Live in-game betting signals
- Additional leagues beyond the six listed
- Mobile native app (dashboard is mobile responsive via web)
- Social/sharing features
- Bivariate Poisson (future upgrade path beyond Dixon-Coles)
- Bayesian continuous team strength updating (future upgrade path)
- News sentiment / injury leak scraper from social media (future upgrade — complex NLP + API costs)
