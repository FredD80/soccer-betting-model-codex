import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  ManualPick,
  ManualPickSummary,
  ManualVsModelSummary,
  FixtureManualComparison,
} from '../api/types'

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

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function pickLabel(pick: ManualPick): string {
  const linePart = pick.line == null ? '' : ` ${pick.line > 0 ? '+' : ''}${pick.line}`
  return `${pick.market_type} · ${pick.selection}${linePart}`
}

export default function MyPicks({ refreshKey }: Props) {
  const [manualPicks, setManualPicks] = useState<ManualPick[]>([])
  const [manualSummary, setManualSummary] = useState<ManualPickSummary[]>([])
  const [modelSummary, setModelSummary] = useState<ManualVsModelSummary[]>([])
  const [fixtureComparisons, setFixtureComparisons] = useState<FixtureManualComparison[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      api.manualPicks(),
      api.manualPickSummary(),
      api.compareManualVsModelsSummary(),
      api.compareFixtures(),
    ])
      .then(([manualRows, manualSummaryRows, modelSummaryRows, fixtureRows]) => {
        setManualPicks(manualRows)
        setManualSummary(manualSummaryRows)
        setModelSummary(modelSummaryRows)
        setFixtureComparisons(fixtureRows)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [refreshKey])

  if (loading) return <p className="text-slate-400">Loading tracked picks…</p>
  if (error) return <p className="text-rose-400">Error: {error}</p>

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-400">My Picks</h2>
        {manualPicks.length === 0 ? (
          <p className="rounded-xl border border-slate-800 bg-slate-900/70 p-4 text-sm text-slate-500">
            No manual picks yet. Add one from any fixture card in the picks tabs.
          </p>
        ) : (
          <div className="grid gap-3">
            {manualPicks.map(row => (
              <div key={row.id} className="rounded-xl border border-slate-800 bg-slate-900/80 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-100">{row.home_team} <span className="text-slate-500">vs</span> {row.away_team}</p>
                    <p className="text-xs text-slate-500">{row.league} · {pickLabel(row)}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-mono text-slate-100">{signed(row.profit_units)}</p>
                    <p className="text-xs uppercase tracking-wide text-slate-500">{row.result_status}</p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-400">
                  <span>Stake {row.stake_units}u</span>
                  {row.american_odds != null && <span>Odds {row.american_odds > 0 ? `+${row.american_odds}` : row.american_odds}</span>}
                  {row.bookmaker && <span>{row.bookmaker}</span>}
                  <span>{formatDateTime(row.created_at)}</span>
                </div>
                {row.notes && <p className="mt-2 text-sm text-slate-300">{row.notes}</p>}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-400">My Results By Market</h2>
        {manualSummary.length === 0 ? (
          <p className="text-sm text-slate-500">No settled manual picks yet.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {manualSummary.map(row => (
              <div key={`${row.market_type}-${row.league}`} className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 space-y-2">
                <p className="text-sm font-semibold text-slate-100">{row.market_type} <span className="text-slate-500">·</span> {row.league}</p>
                <div className="grid grid-cols-2 gap-2 text-sm text-slate-300">
                  <span>Settled</span><span className="text-right font-mono">{row.settled_count}</span>
                  <span>Win rate</span><span className="text-right font-mono">{pct(row.win_rate)}</span>
                  <span>Profit</span><span className="text-right font-mono">{signed(row.profit_units)}</span>
                  <span>ROI</span><span className="text-right font-mono">{pct(row.roi)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-400">Main Vs Parallel Vs Me</h2>
        {modelSummary.length === 0 ? (
          <p className="text-sm text-slate-500">No exact pick matches against model outcomes yet.</p>
        ) : (
          <div className="space-y-3">
            {modelSummary.map(row => (
              <div key={`${row.model_name}-${row.version}-${row.market_type}-${row.league}`} className="rounded-xl border border-slate-800 bg-slate-900/80 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="font-semibold text-slate-100">{row.model_name} <span className="text-slate-500">v{row.version}</span></p>
                  <p className="text-xs uppercase tracking-wide text-slate-500">{row.market_type} · {row.league}</p>
                </div>
                <div className="mt-3 grid gap-2 text-sm text-slate-300 md:grid-cols-3">
                  <div className="rounded-lg bg-slate-950/70 p-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Compared Picks</p>
                    <p className="mt-1 font-mono text-slate-100">{row.compared_picks}</p>
                  </div>
                  <div className="rounded-lg bg-slate-950/70 p-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">My ROI</p>
                    <p className="mt-1 font-mono text-emerald-300">{pct(row.manual_roi)}</p>
                    <p className="text-xs text-slate-500">{signed(row.manual_profit_units)}</p>
                  </div>
                  <div className="rounded-lg bg-slate-950/70 p-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Model ROI</p>
                    <p className="mt-1 font-mono text-sky-300">{pct(row.model_roi)}</p>
                    <p className="text-xs text-slate-500">{signed(row.model_profit_units)}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-400">Fixture-Level View</h2>
        {fixtureComparisons.length === 0 ? (
          <p className="text-sm text-slate-500">No fixture-level comparisons yet.</p>
        ) : (
          <div className="space-y-3">
            {fixtureComparisons.map(row => (
              <div key={row.manual_pick_id} className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-100">{row.home_team} <span className="text-slate-500">vs</span> {row.away_team}</p>
                    <p className="text-xs text-slate-500">{row.league}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-mono text-emerald-300">{signed(row.manual_profit_units)}</p>
                    <p className="text-xs uppercase tracking-wide text-slate-500">{row.manual_result_status}</p>
                  </div>
                </div>

                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                  <p className="text-xs uppercase tracking-wide text-emerald-300">My Pick</p>
                  <p className="mt-1 text-sm text-slate-100">
                    {row.manual_market_type} · {row.manual_selection}
                    {row.manual_line != null ? ` ${row.manual_line > 0 ? '+' : ''}${row.manual_line}` : ''}
                  </p>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  {row.compared_models.map(model => (
                    <div key={`${row.manual_pick_id}-${model.model_name}-${model.version}`} className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-sm font-semibold text-slate-100">{model.model_name}</p>
                          <p className="text-xs text-slate-500">v{model.version}</p>
                        </div>
                        <span className="text-xs uppercase tracking-wide text-slate-500">{model.confidence_tier ?? '—'}</span>
                      </div>
                      <p className="mt-3 text-sm text-slate-200">
                        {model.market_type} · {model.selection}
                        {model.line != null ? ` ${model.line > 0 ? '+' : ''}${model.line}` : ''}
                      </p>
                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-400">
                        <span>Result</span><span className="text-right uppercase">{model.result_status}</span>
                        <span>Profit</span><span className="text-right font-mono">{signed(model.profit_units)}</span>
                        <span>Final prob</span><span className="text-right font-mono">{pct(model.final_probability)}</span>
                        <span>Edge</span><span className="text-right font-mono">{pct(model.edge_pct)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
