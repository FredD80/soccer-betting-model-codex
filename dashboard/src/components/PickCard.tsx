import type { FixturePick } from '../api/types'
import ConfidenceBadge from './ConfidenceBadge'

interface Props {
  pick: FixturePick
}

function formatKickoff(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function evLabel(ev: number | null): string {
  if (ev === null) return '—'
  return `+${(ev * 100).toFixed(1)}%`
}

export default function PickCard({ pick }: Props) {
  const { home_team, away_team, league, kickoff_at, best_spread, best_ou, top_ev } = pick

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-900 p-4 space-y-3">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <p className="font-semibold">{home_team} <span className="text-gray-400">vs</span> {away_team}</p>
          <p className="text-xs text-gray-500">{league} · {formatKickoff(kickoff_at)}</p>
        </div>
        {top_ev !== null && (
          <span className="text-sm font-mono text-green-400">{evLabel(top_ev)} edge</span>
        )}
      </div>

      {/* Spread pick */}
      {best_spread && (
        <div className="flex items-center gap-2 text-sm">
          <ConfidenceBadge tier={best_spread.confidence_tier} />
          <span className="font-medium">
            {best_spread.team_side === 'home' ? home_team : away_team}
            {' '}{best_spread.goal_line > 0 ? '+' : ''}{best_spread.goal_line}
          </span>
          <span className="text-gray-400">
            {(best_spread.cover_probability * 100).toFixed(0)}% cover
          </span>
          {best_spread.ev_score !== null && (
            <span className="text-green-400 text-xs">{evLabel(best_spread.ev_score)}</span>
          )}
        </div>
      )}

      {/* O/U pick */}
      {best_ou && (
        <div className="flex items-center gap-2 text-sm">
          <ConfidenceBadge tier={best_ou.confidence_tier} />
          <span className="font-medium capitalize">{best_ou.direction} {best_ou.line}</span>
          <span className="text-gray-400">
            {(best_ou.probability * 100).toFixed(0)}%
          </span>
          {best_ou.ev_score !== null && (
            <span className="text-green-400 text-xs">{evLabel(best_ou.ev_score)}</span>
          )}
        </div>
      )}
    </div>
  )
}
