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
    spread_home_line = Column(Float)    # e.g., -0.5, -1.0
    spread_home_odds = Column(Float)
    spread_away_line = Column(Float)    # e.g., +0.5, +1.0
    spread_away_odds = Column(Float)


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
    red_card_minute = Column(Integer)  # minute of first red card; None if no red card; set by API-Football (Phase 3)
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
    final_probability = Column(Float)            # Phase 3: blended (w1*model + w2*market)
    edge_pct = Column(Float)                     # Phase 3: final_p - implied_p
    kelly_fraction = Column(Float)               # Phase 3: fractional Kelly stake
    steam_downgraded = Column(Boolean, default=False)
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
    final_probability = Column(Float)            # Phase 3: blended probability
    edge_pct = Column(Float)                     # Phase 3: final_p - implied_p
    kelly_fraction = Column(Float)               # Phase 3: fractional Kelly stake
    steam_downgraded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    psxg_plus_minus = Column(Float)                # GK overperformance vs expected
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


class LeagueCalibration(Base):
    """Per-league Dixon-Coles parameters fitted by the backtester."""
    __tablename__ = "league_calibration"
    id = Column(Integer, primary_key=True)
    league_espn_id = Column(String, nullable=False, unique=True)
    rho = Column(Float, nullable=False, default=-0.13)       # DC low-score correlation
    home_advantage = Column(Float, nullable=False, default=1.10)
    attack_scale = Column(Float, nullable=False, default=1.0)
    defense_scale = Column(Float, nullable=False, default=1.0)
    fitted_at = Column(DateTime)                              # None = manually seeded


class MonteCarloRun(Base):
    """Stores the outcome of a Monte Carlo simulation run for a fixture."""
    __tablename__ = "monte_carlo_runs"
    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    lambda_home = Column(Float, nullable=False)
    lambda_away = Column(Float, nullable=False)
    rho = Column(Float, nullable=False)
    home_win_prob = Column(Float)
    draw_prob = Column(Float)
    away_win_prob = Column(Float)
    over_15_prob = Column(Float)
    over_25_prob = Column(Float)
    over_35_prob = Column(Float)
    scoreline_json = Column(Text)                 # JSON array of top-20 {h, a, p} dicts
    run_at = Column(DateTime, default=datetime.utcnow)


class TeamAlias(Base):
    """Cross-provider team name normalisation.

    Given a raw team name as emitted by an external source (e.g. the Odds API
    returns "Man Utd" while ESPN returns "Manchester United"), resolve to the
    canonical Team row.
    """
    __tablename__ = "team_aliases"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    alias = Column(String, nullable=False)      # raw external name (case-insensitive match)
    source = Column(String, nullable=False)     # "odds_api" | "espn" | "api_football" | ...


class MarketWeights(Base):
    """Per-league, per-bet-type blend weights fit offline by fit_market_weights.py."""
    __tablename__ = "market_weights"
    id = Column(Integer, primary_key=True)
    league_espn_id = Column(String, nullable=False)
    bet_type = Column(String, nullable=False)     # "spread" | "ou"
    w_model = Column(Float, nullable=False)
    w_market = Column(Float, nullable=False)
    n_samples = Column(Integer)
    fitted_at = Column(DateTime)


class CalibrationRun(Base):
    """Rolling Brier score + reliability curve per (model, bet_type)."""
    __tablename__ = "calibration_runs"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    bet_type = Column(String, nullable=False)
    window_days = Column(Integer, default=30)
    brier_score = Column(Float)
    n_samples = Column(Integer)
    reliability_json = Column(Text)               # JSON-encoded reliability curve
    computed_at = Column(DateTime, default=datetime.utcnow)


class MLArtifact(Base):
    """Registry of trained ML model artifacts (e.g. XGBoost λ regressors)."""
    __tablename__ = "ml_artifacts"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # e.g. "ml_lambda"
    version = Column(String, nullable=False)       # e.g. "20260413_223145"
    path = Column(String, nullable=False)          # filesystem path to .pkl
    mae_home = Column(Float)
    mae_away = Column(Float)
    n_samples = Column(Integer)
    active = Column(Boolean, default=False)
    trained_at = Column(DateTime, default=datetime.utcnow)
