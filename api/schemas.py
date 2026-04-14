from datetime import datetime
from pydantic import BaseModel


class SpreadPickResponse(BaseModel):
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


class OUPickResponse(BaseModel):
    line: float                  # 1.5 | 2.5 | 3.5
    direction: str               # "over" | "under"
    probability: float
    ev_score: float | None
    confidence_tier: str
    final_probability: float | None = None
    edge_pct: float | None = None
    kelly_fraction: float | None = None
    steam_downgraded: bool = False


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
