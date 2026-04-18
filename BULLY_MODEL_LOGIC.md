# Bully Model Logic

This document describes the current implementation of the standalone `Bully-Model` used in this codebase.

Its purpose is to identify strong-team-vs-weak-team spots using Elo as the primary signal, then adjust that view with recent expected-goals form. It is intentionally separate from the Alpha and Market-Edge models.

## 1. High-Level Goal

The model is designed to answer:

- Which team is materially stronger than its opponent?
- Is that strength gap large enough to qualify as a bully spot?
- Is recent xG form supporting or weakening that favorite?
- How likely is the favorite to:
  - win
  - score 2 or more goals
  - keep a clean sheet

## 2. Separation From Other Models

The Bully model is standalone.

- It writes to `elo_form_predictions`
- It does not write to `moneyline_predictions`, `spread_predictions`, or `ou_analysis`
- It has its own schedule endpoint and backtest path
- It is surfaced in the UI as `Bully-Model`

Core implementation files:

- [app/elo_form_predictor.py](/home/fred/apps/sbm-codex/app/elo_form_predictor.py)
- [api/routers/fixtures.py](/home/fred/apps/sbm-codex/api/routers/fixtures.py)
- [app/pick_backtester.py](/home/fred/apps/sbm-codex/app/pick_backtester.py)
- [app/tracker.py](/home/fred/apps/sbm-codex/app/tracker.py)

## 3. Inputs

The model uses:

- Historical match results within a league to build Elo ratings
- Upcoming scheduled fixtures
- Understat league match data, when available
- Latest market odds only for display, tracking, ROI, and backtesting

Important: market odds do not currently drive the Bully probability model itself. Elo and xG context drive the probabilities.

## 4. Core Constants

Current implementation constants:

```text
BASE_ELO = 1500.0
DEFAULT_HOME_ADVANTAGE_ELO = 60.0
DEFAULT_K_FACTOR = 24.0
BASE_DRAW_PROBABILITY = 0.27
MIN_DRAW_PROBABILITY = 0.18
MAX_TREND_SHIFT = 0.06
TREND_SCALE = 0.35
LOOKBACK_MATCHES = 5
BULLY_GAP_THRESHOLD = 120.0

BASE_TOTAL_GOALS = 2.6
MIN_EXPECTED_GOALS = 0.2
MAX_EXPECTED_GOALS = 3.6
```

## 5. Step 1: Build Elo Ratings

For each league, the model rebuilds Elo ratings from completed historical fixtures in chronological order.

Initial rating:

```text
all teams start at 1500
```

Expected home score:

```text
expected_home = 1 / (1 + 10 ^ ( -((home_elo + home_advantage) - away_elo) / 400 ))
```

Observed result is mapped to:

```text
home win = 1.0
draw = 0.5
away win = 0.0
```

Elo update:

```text
delta = K * (actual_home - expected_home)
home_elo = home_elo + delta
away_elo = away_elo - delta
```

Notes:

- Home advantage is baked into expectation, not into stored team ratings
- Elo is built within each league from the historical results available in the database

## 6. Step 2: Baseline Match Probabilities From Elo

For an upcoming fixture:

```text
elo_diff = (home_elo + home_advantage) - away_elo
home_share = 1 / (1 + 10 ^ (-elo_diff / 400))
```

Draw probability shrinks as the Elo gap grows:

```text
draw_prob = clamp(
  0.27 - 0.10 * min(1.0, abs(elo_diff) / 300),
  0.18,
  0.27
)
```

Then the remaining mass is split between home and away:

```text
decisive_mass = 1 - draw_prob
home_prob = decisive_mass * home_share
away_prob = decisive_mass * (1 - home_share)
```

This gives a 3-way outcome distribution:

- `home_probability`
- `draw_probability`
- `away_probability`

## 7. Step 3: Recent xG Form Context

The model looks at the last 5 Understat matches for each team before kickoff.

For each prior match, it computes:

```text
xg_diff = team_xG - opponent_xG
```

It then derives:

- `avg_xg_diff`: average xG differential over the last 5 matches
- `trend`: slope of xG differential over time across those matches
- `matches_used`: number of valid Understat matches used

Trend is computed as a simple linear slope over the ordered last-five xG differential values.

If Understat data is unavailable for the league or team match mapping fails:

- `avg_xg_diff = null`
- `trend = null`
- `matches_used = 0`
- no xG adjustment is applied

## 8. Step 4: xG Trend Adjustment To Win Probabilities

The Bully model uses trend, not just record.

Relative trend:

```text
relative_trend = home_trend - away_trend
normalized_signal = clamp(relative_trend / 0.35, -1.0, 1.0)
shift = normalized_signal * 0.06
```

That shift is applied only to the home/away split:

```text
home_prob = home_prob + shift
away_prob = away_prob - shift
draw_prob = unchanged
```

Shift is bounded so probabilities cannot go negative.

Interpretation:

- Strong favorite with worsening xG trend gets penalized
- Weaker side with improving xG trend gains probability
- If both trends are missing, the model remains pure Elo

## 9. Step 5: Bully Spot Classification

The favorite is whichever side has the higher home-adjusted Elo:

```text
favorite_side = home if (home_elo + 60) >= away_elo else away
```

The Elo gap is:

```text
elo_gap = abs((home_elo + 60) - away_elo)
```

A game is tagged as a bully spot when:

```text
elo_gap >= 120
```

This is the main hard filter for "strong vs weak" mismatch games.

## 10. Step 6: 2+ Goals And Clean-Sheet Projections

The model also derives scoring and shutout probabilities from the 3-way probabilities plus xG context.

First build intermediate signals:

```text
strength_signal = clamp(home_probability - away_probability, -0.75, 0.75)
trend_signal = clamp(home_xg_trend - away_xg_trend, -0.4, 0.4)
form_signal = clamp(home_xg_diff_avg - away_xg_diff_avg, -2.0, 2.0)
total_signal = clamp(home_xg_diff_avg + away_xg_diff_avg, -2.0, 2.0)
```

Projected total goals:

```text
total_goals = clamp(
  2.6 + 0.12 * total_signal + 0.18 * abs(trend_signal),
  1.8,
  3.8
)
```

Projected home share of goals:

```text
home_share = clamp(
  0.5 + 0.42 * strength_signal + 0.08 * form_signal + 0.20 * trend_signal,
  0.18,
  0.82
)
```

Draw-heavy games are slightly suppressed:

```text
draw_drag = clamp((draw_probability - 0.22) * 0.6, 0.0, 0.08)
```

Expected goals:

```text
home_xg_exp = clamp((total_goals * home_share) - draw_drag, 0.2, 3.6)
away_xg_exp = clamp(total_goals - home_xg_exp - draw_drag, 0.2, 3.6)
```

Then Poisson is used:

```text
P(clean sheet) = exp(-opponent_expected_goals)
P(2+ goals) = 1 - exp(-lambda) * (1 + lambda)
```

This produces:

- `home_two_plus_probability`
- `away_two_plus_probability`
- `home_clean_sheet_probability`
- `away_clean_sheet_probability`

And also favorite/underdog versions of those same outputs.

## 11. Stored Outputs Per Fixture

The model stores, at minimum:

- favorite side
- Elo gap
- bully-spot flag
- home and away Elo
- home and away xG differential averages
- home and away xG trends
- trend adjustment applied
- home/draw/away probabilities

Derived schedule/UI outputs also include:

- favorite probability
- underdog probability
- favorite 2+ goals probability
- favorite clean-sheet probability
- underdog 2+ goals probability
- underdog clean-sheet probability

## 12. How Tracking Treats The Bully Model

For grading and `My Picks` comparison, the Bully model is treated as a moneyline-style selection on the favorite side.

Selection used for tracking:

```text
selection = favorite_side
model_probability = favorite side win probability
```

Confidence tier for tracked bully outcomes:

```text
ELITE if is_bully_spot and model_probability >= 0.68
HIGH  if is_bully_spot or model_probability >= 0.60
MEDIUM otherwise
```

Tracking result rule:

```text
win  if favorite_side == actual_result
loss otherwise
```

ROI uses the latest available favorite-side moneyline odds.

## 13. How Backtesting Treats The Bully Model

The backtest market name is:

```text
bully
```

A historical Bully backtest currently:

- scans completed fixtures in the chosen date range
- pulls stored `EloFormPrediction` rows
- keeps only rows where `is_bully_spot == True`
- grades favorite-side win/loss
- uses favorite-side moneyline odds for ROI
- also records:
  - `two_plus_hit_rate`
  - `clean_sheet_hit_rate`

Backtest event definitions:

```text
favorite win hit      = favorite_side == actual match winner
2+ goals hit          = favorite goals >= 2
clean-sheet hit       = underdog goals == 0
```

Important limitation:

The current backtest does not replay the model historically from raw data. It backtests stored Bully predictions that already exist in the database.

## 14. What The Model Prioritizes

In plain language, the model is optimized to find:

- big Elo gaps
- favorites whose xG form is not deteriorating
- weaker teams whose improving xG trend should reduce blind trust in the favorite
- favorites likely not only to win, but to win with scoreboard authority

It is not designed primarily for:

- balanced games
- draw hunting
- price-first value betting
- market efficiency modeling

## 15. Known Weaknesses / Critique Targets

These are the main areas another model or reviewer could critique:

- Elo is league-local and depends on the historical result set present in the DB
- Home advantage is static at `+60 Elo`
- Draw probability is heuristic, not estimated from a fitted draw model
- xG adjustment uses trend only for the win-probability shift, not xG average directly
- the maximum xG trend impact on win probability is capped at 6 percentage points
- expected-goals and shutout projections are derived heuristically from win probabilities and xG context, not from a full scoring model fit
- current backtests use stored historical predictions, not a full historical replay
- if Understat data is missing, the model collapses toward pure Elo

## 16. Minimal Pseudocode

```text
for each upcoming fixture:
    build/retrieve league Elo ratings
    home_elo = team Elo
    away_elo = team Elo

    favorite_side = argmax(home_elo + home_advantage, away_elo)
    elo_gap = abs((home_elo + home_advantage) - away_elo)

    base_probs = elo_to_home_draw_away_probs(home_elo, away_elo)

    home_form = last_5_understat_xg_diff(home_team)
    away_form = last_5_understat_xg_diff(away_team)

    adjusted_probs = apply_trend_shift(base_probs, home_form.trend, away_form.trend)

    bully_spot = (elo_gap >= 120)

    goal_projection = derive_expected_goals_and_poisson_probs(
        adjusted_probs,
        home_form,
        away_form
    )

    store:
        favorite_side
        elo_gap
        bully_spot
        adjusted_probs
        xg context
```

## 17. One-Sentence Summary

The Bully model is a standalone Elo-first mismatch detector that upgrades or downgrades the favorite using last-five xG trend, then derives favorite win, 2+ goals, and clean-sheet probabilities to identify dominant-team spots.
