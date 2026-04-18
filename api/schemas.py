from datetime import date, datetime
from pydantic import BaseModel, Field


class SpreadPickResponse(BaseModel):
    model_name: str | None = None
    model_version: str | None = None
    team_side: str               # "home" | "away"
    goal_line: float             # -1.5 | -1.0 | -0.5 | 0.5 | 1.0 | 1.5
    cover_probability: float
    push_probability: float
    ev_score: float | None
    confidence_tier: str         # SKIP | MEDIUM | HIGH | ELITE
    final_probability: float | None = None
    edge_pct: float | None = None
    kelly_fraction: float | None = None
    steam_downgraded: bool = False
    decimal_odds: float | None = None
    american_odds: int | None = None


class OUPickResponse(BaseModel):
    model_name: str | None = None
    model_version: str | None = None
    line: float                  # 1.5 | 2.5 | 3.5
    direction: str               # "over" | "under"
    probability: float
    ev_score: float | None
    confidence_tier: str
    final_probability: float | None = None
    edge_pct: float | None = None
    kelly_fraction: float | None = None
    steam_downgraded: bool = False
    decimal_odds: float | None = None
    american_odds: int | None = None


class MoneylinePickResponse(BaseModel):
    model_name: str | None = None
    model_version: str | None = None
    outcome: str                 # "home" | "draw" | "away"
    probability: float
    ev_score: float | None
    confidence_tier: str
    final_probability: float | None = None
    edge_pct: float | None = None
    kelly_fraction: float | None = None
    steam_downgraded: bool = False
    decimal_odds: float | None = None
    american_odds: int | None = None


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
    model_view: str = "best"
    best_spread: SpreadPickResponse | None   # highest EV spread pick
    best_ou: OUPickResponse | None           # highest EV O/U pick
    best_moneyline: MoneylinePickResponse | None = None  # highest EV 3-way moneyline pick
    top_ev: float | None                     # max of best_spread/ou/moneyline ev for sorting


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


class ScheduleLineResponse(BaseModel):
    home_odds: float | None = None
    draw_odds: float | None = None
    away_odds: float | None = None
    spread_home_line: float | None = None
    spread_home_odds: float | None = None
    spread_away_line: float | None = None
    spread_away_odds: float | None = None
    total_goals_line: float | None = None
    over_odds: float | None = None
    under_odds: float | None = None
    bookmaker: str | None = None
    captured_at: datetime | None = None


class ScheduledFixtureResponse(BaseModel):
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    kickoff_at: datetime
    lines: ScheduleLineResponse | None = None


class EloFormScheduleResponse(BaseModel):
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    kickoff_at: datetime
    model_name: str
    model_version: str
    favorite_side: str
    underdog_side: str
    favorite_team: str
    underdog_team: str
    elo_gap: float
    is_bully_spot: bool
    home_elo: float
    away_elo: float
    home_probability: float
    draw_probability: float
    away_probability: float
    home_expected_goals: float
    away_expected_goals: float
    home_two_plus_probability: float
    away_two_plus_probability: float
    home_clean_sheet_probability: float
    away_clean_sheet_probability: float
    favorite_probability: float
    underdog_probability: float
    favorite_expected_goals: float
    underdog_expected_goals: float
    expected_goals_delta: float
    favorite_two_plus_probability: float
    underdog_two_plus_probability: float
    favorite_clean_sheet_probability: float
    underdog_clean_sheet_probability: float
    home_xg_diff_avg: float | None = None
    away_xg_diff_avg: float | None = None
    home_xg_trend: float | None = None
    away_xg_trend: float | None = None
    trend_adjustment: float = 0.0
    lines: ScheduleLineResponse | None = None


class ModelPerformanceResponse(BaseModel):
    model_name: str
    version: str
    bet_type: str
    total_predictions: int
    correct: int
    accuracy: float
    roi: float


class PredictionOutcomeResponse(BaseModel):
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    model_name: str
    version: str
    market_type: str
    selection: str
    line: float | None = None
    result_status: str
    profit_units: float | None = None
    model_probability: float | None = None
    final_probability: float | None = None
    edge_pct: float | None = None
    kelly_fraction: float | None = None
    confidence_tier: str | None = None
    decimal_odds: float | None = None
    american_odds: int | None = None
    graded_at: datetime | None = None


class PredictionOutcomeSummaryResponse(BaseModel):
    model_name: str
    version: str
    market_type: str
    league: str
    confidence_tier: str | None = None
    settled_count: int
    wins: int
    losses: int
    pushes: int
    win_rate: float
    roi: float


class ManualPickCreateRequest(BaseModel):
    fixture_id: int
    market_type: str
    selection: str
    line: float | None = None
    decimal_odds: float | None = None
    american_odds: int | None = None
    stake_units: float = 1.0
    bookmaker: str | None = None
    notes: str | None = None


class ManualPickResponse(BaseModel):
    id: int
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    market_type: str
    selection: str
    line: float | None = None
    decimal_odds: float | None = None
    american_odds: int | None = None
    stake_units: float
    bookmaker: str | None = None
    notes: str | None = None
    result_status: str
    profit_units: float | None = None
    graded_at: datetime | None = None
    created_at: datetime | None = None


class ManualPickSummaryResponse(BaseModel):
    market_type: str
    league: str
    settled_count: int
    wins: int
    losses: int
    pushes: int
    total_stake_units: float
    profit_units: float
    win_rate: float
    roi: float


class ManualVsModelComparisonResponse(BaseModel):
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    market_type: str
    selection: str
    line: float | None = None
    manual_pick_id: int
    manual_result_status: str
    manual_profit_units: float | None = None
    manual_stake_units: float
    model_name: str
    version: str
    model_result_status: str
    model_profit_units: float | None = None
    model_probability: float | None = None
    model_final_probability: float | None = None
    model_edge_pct: float | None = None
    model_confidence_tier: str | None = None
    graded_at: datetime | None = None


class ManualVsModelSummaryResponse(BaseModel):
    model_name: str
    version: str
    market_type: str
    league: str
    compared_picks: int
    manual_wins: int
    model_wins: int
    manual_profit_units: float
    model_profit_units: float
    manual_roi: float
    model_roi: float


class FixtureModelTopPickResponse(BaseModel):
    model_name: str
    version: str
    market_type: str
    selection: str
    line: float | None = None
    result_status: str
    profit_units: float | None = None
    model_probability: float | None = None
    final_probability: float | None = None
    edge_pct: float | None = None
    confidence_tier: str | None = None


class FixtureManualComparisonResponse(BaseModel):
    fixture_id: int
    home_team: str
    away_team: str
    league: str
    manual_pick_id: int
    manual_market_type: str
    manual_selection: str
    manual_line: float | None = None
    manual_result_status: str
    manual_profit_units: float | None = None
    manual_stake_units: float
    graded_at: datetime | None = None
    compared_models: list[FixtureModelTopPickResponse]


class BacktestRunRequest(BaseModel):
    from_date: date
    to_date: date
    markets: list[str] = ["spread", "ou", "moneyline", "bully"]


class BacktestRunResponse(BaseModel):
    market: str
    model_id: int
    model_name: str
    model_version: str
    total: int
    correct: int
    accuracy: float
    roi: float
    win_two_plus_hit_rate: float | None = None
    two_plus_hit_rate: float | None = None
    clean_sheet_hit_rate: float | None = None
    two_plus_given_win_rate: float | None = None
    clean_sheet_given_win_rate: float | None = None
    date_from: datetime
    date_to: datetime
    run_at: datetime | None = None


class BacktestJobResponse(BaseModel):
    id: int
    task_id: str | None = None
    status: str
    requested_markets: list[str] = Field(default_factory=list)
    date_from: datetime
    date_to: datetime
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    results: list[BacktestRunResponse] = Field(default_factory=list)
