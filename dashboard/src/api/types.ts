export interface SpreadPick {
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
