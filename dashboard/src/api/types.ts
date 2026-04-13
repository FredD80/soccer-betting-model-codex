export interface SpreadPick {
  team_side: 'home' | 'away'
  goal_line: number          // -1.5 | -1.0 | -0.5 | 0.5 | 1.0 | 1.5
  cover_probability: number
  push_probability: number
  ev_score: number | null
  confidence_tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
}

export interface OUPick {
  line: number               // 1.5 | 2.5 | 3.5
  direction: 'over' | 'under'
  probability: number
  ev_score: number | null
  confidence_tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
}

export interface FixturePick {
  fixture_id: number
  home_team: string
  away_team: string
  league: string
  kickoff_at: string         // ISO-8601 string
  best_spread: SpreadPick | null
  best_ou: OUPick | null
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
