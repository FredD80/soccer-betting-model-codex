import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import type { FixturePick, ModelView } from '../api/types'
import PickCard from '../components/PickCard'
import { modelPresentationForView, modelViewDescription, modelViewLabel } from '../lib/modelLabels'

interface Props {
  label: string
  fetcher: (modelView: ModelView) => Promise<FixturePick[]>
  modelView: ModelView
  refreshKey?: number
  emptyText?: string
  onManualSaved?: () => void
}

export default function PicksList({ label, fetcher, modelView, refreshKey = 0, emptyText, onManualSaved }: Props) {
  const [picks, setPicks] = useState<FixturePick[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const presentation = modelPresentationForView(modelView)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetcher(modelView)
      .then(setPicks)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [fetcher, modelView, refreshKey])

  if (loading) return <p className="text-gray-400">Loading picks…</p>
  if (error) return <p className="text-red-400">Error: {error}</p>
  if (picks.length === 0) {
    const modelSpecificEmpty =
      modelView === 'parallel'
        ? 'No Market-Edge picks are available in this window yet.'
        : emptyText ?? 'No fixtures available in this window.'
    return <p className="text-gray-500">{modelSpecificEmpty}</p>
  }

  return (
    <div className="space-y-3">
      <div className={`rounded-2xl border bg-slate-950/55 p-3 sm:p-4 ${presentation.accentBorder}`}>
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] ${presentation.accentBorder} ${presentation.accentBg} ${presentation.accentText}`}>
                {presentation.badge}
              </span>
              <h2 className="text-sm font-medium text-gray-300 uppercase tracking-wider">
                {label} · {modelViewLabel(modelView)} — {picks.length} fixture{picks.length !== 1 ? 's' : ''}
              </h2>
            </div>
            <p className="mt-2 text-xs text-slate-400 sm:hidden">
              {picks.length} fixtures sorted by confidence.
            </p>
            <p className="mt-2 hidden max-w-2xl text-sm text-slate-400 sm:block">
              {modelViewDescription(modelView)} Elite and high-confidence fixtures are surfaced first so the board stays actionable.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs uppercase tracking-[0.18em]">
            <Link to="/tracking" className={`rounded-full border px-3 py-1 transition ${presentation.accentBorder} ${presentation.accentText}`}>
              Season Tracker
            </Link>
            <Link to="/backtests" className="rounded-full border border-slate-700 px-3 py-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100">
              Backtests
            </Link>
          </div>
        </div>
      </div>
      {picks.map(p => (
        <PickCard key={p.fixture_id} pick={p} modelView={modelView} onManualSaved={onManualSaved} />
      ))}
    </div>
  )
}
