export type ModelView = 'best' | 'main' | 'parallel'

export interface SpreadPick {
  model_name: string | null
  model_version: string | null
  team_side: 'home' | 'away'
  goal_line: number
  cover_probability: number
  push_probability: number
  ev_score: number | null
  confidence_tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
  final_probability: number | null
  edge_pct: number | null
  kelly_fraction: number | null
  steam_downgraded: boolean
  decimal_odds: number | null
  american_odds: number | null
}

export interface OUPick {
  model_name: string | null
  model_version: string | null
  line: number
  direction: 'over' | 'under'
  probability: number
  ev_score: number | null
  confidence_tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
  final_probability: number | null
  edge_pct: number | null
  kelly_fraction: number | null
  steam_downgraded: boolean
  decimal_odds: number | null
  american_odds: number | null
}

export interface MoneylinePick {
  model_name: string | null
  model_version: string | null
  outcome: 'home' | 'draw' | 'away'
  probability: number
  ev_score: number | null
  confidence_tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
  final_probability: number | null
  edge_pct: number | null
  kelly_fraction: number | null
  steam_downgraded: boolean
  decimal_odds: number | null
  american_odds: number | null
}

export interface FixturePick {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  kickoff_at: string         // ISO-8601 string
  model_view: ModelView
  best_spread: SpreadPick | null
  best_ou: OUPick | null
  best_moneyline: MoneylinePick | null
  top_ev: number | null
}

export interface FormSummary {
  goals_scored_avg: number
  goals_conceded_avg: number
  spread_cover_rate: number | null
  ou_hit_rate_25: number | null
  matches_count: number
}

export interface FixtureDetail {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  kickoff_at: string
  home_form: FormSummary | null
  away_form: FormSummary | null
  spread_picks: SpreadPick[]
  ou_picks: OUPick[]
}

export interface ScheduleLine {
  home_odds: number | null
  draw_odds: number | null
  away_odds: number | null
  spread_home_line: number | null
  spread_home_odds: number | null
  spread_away_line: number | null
  spread_away_odds: number | null
  total_goals_line: number | null
  over_odds: number | null
  under_odds: number | null
  bookmaker: string | null
  captured_at: string | null
}

export interface ScheduledFixture {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  kickoff_at: string
  lines: ScheduleLine | null
}

export interface ManualPickCreateRequest {
  fixture_id: number
  market_type: 'moneyline' | 'spread' | 'ou'
  selection: string
  line?: number | null
  decimal_odds?: number | null
  american_odds?: number | null
  stake_units: number
  bookmaker?: string | null
  notes?: string | null
}

export interface ManualPick {
  id: number
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  market_type: 'moneyline' | 'spread' | 'ou'
  selection: string
  line: number | null
  decimal_odds: number | null
  american_odds: number | null
  stake_units: number
  bookmaker: string | null
  notes: string | null
  result_status: 'open' | 'win' | 'loss' | 'push' | 'void'
  profit_units: number | null
  graded_at: string | null
  created_at: string | null
}

export interface ManualPickSummary {
  market_type: string
  league: string
  settled_count: number
  wins: number
  losses: number
  pushes: number
  total_stake_units: number
  profit_units: number
  win_rate: number
  roi: number
}

export interface ManualVsModelComparison {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  market_type: string
  selection: string
  line: number | null
  manual_pick_id: number
  manual_result_status: string
  manual_profit_units: number | null
  manual_stake_units: number
  model_name: string
  version: string
  model_result_status: string
  model_profit_units: number | null
  model_probability: number | null
  model_final_probability: number | null
  model_edge_pct: number | null
  model_confidence_tier: string | null
  graded_at: string | null
}

export interface ManualVsModelSummary {
  model_name: string
  version: string
  market_type: string
  league: string
  compared_picks: number
  manual_wins: number
  model_wins: number
  manual_profit_units: number
  model_profit_units: number
  manual_roi: number
  model_roi: number
}

export interface FixtureModelTopPick {
  model_name: string
  version: string
  market_type: string
  selection: string
  line: number | null
  result_status: string
  profit_units: number | null
  model_probability: number | null
  final_probability: number | null
  edge_pct: number | null
  confidence_tier: string | null
}

export interface FixtureManualComparison {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  manual_pick_id: number
  manual_market_type: string
  manual_selection: string
  manual_line: number | null
  manual_result_status: string
  manual_profit_units: number | null
  manual_stake_units: number
  graded_at: string | null
  compared_models: FixtureModelTopPick[]
}

export interface BacktestRun {
  market: 'spread' | 'ou' | 'moneyline'
  model_id: number
  model_name: string
  model_version: string
  total: number
  correct: number
  accuracy: number
  roi: number
  date_from: string
  date_to: string
  run_at: string | null
}

export interface BacktestRunRequest {
  from_date: string
  to_date: string
  markets: Array<'spread' | 'ou' | 'moneyline'>
}
