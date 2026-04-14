import { useEffect, useState } from 'react'
import type { FixturePick } from '../api/types'
import PickCard from '../components/PickCard'

interface Props {
  label: string
  fetcher: () => Promise<FixturePick[]>
  emptyText?: string
}

export default function PicksList({ label, fetcher, emptyText }: Props) {
  const [picks, setPicks] = useState<FixturePick[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetcher()
      .then(setPicks)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [fetcher])

  if (loading) return <p className="text-gray-400">Loading picks…</p>
  if (error) return <p className="text-red-400">Error: {error}</p>
  if (picks.length === 0) {
    return <p className="text-gray-500">{emptyText ?? 'No HIGH or ELITE picks.'}</p>
  }

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
        {label} — {picks.length} fixture{picks.length !== 1 ? 's' : ''}
      </h2>
      {picks.map(p => (
        <PickCard key={p.fixture_id} pick={p} />
      ))}
    </div>
  )
}
