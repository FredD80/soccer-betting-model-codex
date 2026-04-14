import { useState } from 'react'
import PicksList from './pages/PicksList'
import { api } from './api/client'

type Tab = 'today' | 'week' | 'ucl'

const TABS: { key: Tab; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'Week' },
  { key: 'ucl', label: 'UCL' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('today')

  const body =
    tab === 'today' ? <PicksList label="Today's Picks" fetcher={api.picksToday} emptyText="No HIGH or ELITE picks today." /> :
    tab === 'week'  ? <PicksList label="This Week" fetcher={api.picksWeek} emptyText="No HIGH or ELITE picks this week." /> :
                      <PicksList label="Champions League" fetcher={api.picksUcl} emptyText="No UCL picks in window." />

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-4 py-3">
        <h1 className="text-lg font-semibold tracking-wide">Soccer Picks</h1>
        <nav className="mt-2 flex gap-4 text-sm">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={
                'px-2 py-1 rounded transition ' +
                (tab === t.key
                  ? 'text-white bg-gray-800'
                  : 'text-gray-400 hover:text-gray-200')
              }
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="max-w-2xl mx-auto px-4 py-6">
        {body}
      </main>
    </div>
  )
}
