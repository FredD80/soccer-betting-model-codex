import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { SeasonTrackerGroup, SeasonTrackerPick, SeasonTrackerResponse } from '../api/types'

interface Props {
  refreshKey: number
}

function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function signed(v: number | null | undefined, digits = 2): string {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}u`
}

function formatWeekStart(value: string): string {
  const d = new Date(`${value}T00:00:00Z`)
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function formatKickoff(value: string): string {
  const d = new Date(value)
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function pickLabel(pick: SeasonTrackerPick): string {
  const line = pick.line == null ? '' : ` ${pick.line > 0 ? '+' : ''}${pick.line}`
  return `${pick.market_type} · ${pick.selection}${line}`
}

function GroupSection({ group }: { group: SeasonTrackerGroup }) {
  return (
    <section className="space-y-3 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">{group.label}</h3>
          <p className="mt-1 text-xs text-slate-500">{group.total_picks} picks · {group.settled_count} settled</p>
        </div>
        <div className="grid grid-cols-2 gap-3 text-right text-sm text-slate-300 md:grid-cols-4">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Win</p>
            <p className="font-mono text-slate-100">{pct(group.win_rate)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">ROI</p>
            <p className="font-mono text-emerald-300">{pct(group.roi)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">W-L-P</p>
            <p className="font-mono text-slate-100">{group.wins}-{group.losses}-{group.pushes}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Type</p>
            <p className="font-mono text-slate-100">{group.group_type}</p>
          </div>
        </div>
      </div>

      {group.weeks.length === 0 ? (
        <p className="text-sm text-slate-500">No tracked picks yet.</p>
      ) : (
        <div className="space-y-3">
          {group.weeks.map(week => (
            <div key={`${group.key}-${week.week_start}`} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Week Of</p>
                  <p className="mt-1 text-sm font-semibold text-slate-100">{formatWeekStart(week.week_start)}</p>
                </div>
                <div className="grid grid-cols-2 gap-3 text-right text-xs text-slate-400 md:grid-cols-5">
                  <span>{week.total_picks} picks</span>
                  <span>{week.settled_count} settled</span>
                  <span>Win {pct(week.win_rate)}</span>
                  <span>ROI {pct(week.roi)}</span>
                  <span>{week.wins}-{week.losses}-{week.pushes}</span>
                </div>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {week.picks.map(pick => (
                  <div key={`${group.key}-${week.week_start}-${pick.id}`} className="rounded-lg border border-slate-800 bg-slate-900/80 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-slate-100">
                          {pick.home_team} <span className="text-slate-500">vs</span> {pick.away_team}
                        </p>
                        <p className="text-xs text-slate-500">{pick.league} · {formatKickoff(pick.kickoff_at)}</p>
                      </div>
                      <div className="text-right">
                        {pick.rank != null && <p className="text-xs uppercase tracking-wide text-slate-500">#{pick.rank}</p>}
                        <p className="text-sm font-mono text-slate-100">{signed(pick.profit_units)}</p>
                        <p className="text-xs uppercase tracking-wide text-slate-500">{pick.result_status}</p>
                      </div>
                    </div>
                    <div className="mt-3 grid gap-1 text-sm text-slate-300">
                      <div>{pickLabel(pick)}</div>
                      <div className="flex flex-wrap gap-3 text-xs text-slate-400">
                        {pick.american_odds != null && <span>Odds {pick.american_odds > 0 ? `+${pick.american_odds}` : pick.american_odds}</span>}
                        {pick.confidence_tier && <span>{pick.confidence_tier}</span>}
                        {pick.final_probability != null && <span>Prob {pct(pick.final_probability)}</span>}
                        {pick.edge_pct != null && <span>Edge {pct(pick.edge_pct)}</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

export default function SeasonTrackingPage({ refreshKey }: Props) {
  const [data, setData] = useState<SeasonTrackerResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.seasonTracker()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [refreshKey])

  if (loading) return <p className="text-slate-400">Loading season tracking…</p>
  if (error) return <p className="text-rose-400">Error: {error}</p>
  if (!data) return <p className="text-slate-500">No season tracking data yet.</p>

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
        <h2 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-300">Season Tracker</h2>
        <p className="mt-2 text-sm text-slate-400">
          Locked top-5 weekly model picks are tracked across the full season. Your normal manual picks are grouped into the same season view by fixture week.
        </p>
        <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
          <span>Season {data.season_key}</span>
          <span>{data.available_weeks.length} tracked weeks</span>
        </div>
      </section>

      {data.model_groups.map(group => (
        <GroupSection key={group.key} group={group} />
      ))}

      <GroupSection group={data.manual_group} />
    </div>
  )
}
