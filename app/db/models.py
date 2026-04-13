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
