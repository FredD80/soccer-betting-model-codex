import { useEffect, useState } from 'react'
import type { FixturePick, ModelView } from '../api/types'
import PickCard from '../components/PickCard'
import { modelViewLabel } from '../lib/modelLabels'

interface Props {
  label: string
  fetcher: (modelView: ModelView) => Promise<FixturePick[]>
  modelView: ModelView
  emptyText?: string
  onManualSaved?: () => void
}

export default function PicksList({ label, fetcher, modelView, emptyText, onManualSaved }: Props) {
  const [picks, setPicks] = useState<FixturePick[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetcher(modelView)
      .then(setPicks)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [fetcher, modelView])

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
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
        {label} · {modelViewLabel(modelView)} — {picks.length} fixture{picks.length !== 1 ? 's' : ''}
      </h2>
      <p className="text-xs uppercase tracking-[0.2em] text-gray-500">
        Elite and high-confidence fixtures appear first. All scheduled fixtures are shown.
      </p>
      {picks.map(p => (
        <PickCard key={p.fixture_id} pick={p} onManualSaved={onManualSaved} />
      ))}
    </div>
  )
}
