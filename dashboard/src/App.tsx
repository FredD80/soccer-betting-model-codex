import { useState } from 'react'
import PicksList from './pages/PicksList'
import BacktestsPage from './pages/BacktestsPage'
import SchedulePage from './pages/SchedulePage'
import BullySchedulePage from './pages/BullySchedulePage'
import MyPicks from './pages/MyPicks'
import SeasonTrackingPage from './pages/SeasonTrackingPage'
import { api } from './api/client'
import type { ModelView } from './api/types'
import { useDashboardAutoRefresh } from './hooks/useDashboardAutoRefresh'
import { modelViewLabel } from './lib/modelLabels'

type Tab = 'today' | 'week' | 'schedule' | 'backtests' | 'tracking' | 'my-picks'

const TABS: { key: Tab; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'Week' },
  { key: 'schedule', label: 'Schedule' },
  { key: 'backtests', label: 'Backtests' },
  { key: 'tracking', label: 'Tracking' },
  { key: 'my-picks', label: 'My Picks' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('today')
  const [modelView, setModelView] = useState<ModelView>('best')
  const [manualRefreshKey, setManualRefreshKey] = useState(0)
  const { refreshKey: autoRefreshKey, status } = useDashboardAutoRefresh()
  const refreshKey = manualRefreshKey + autoRefreshKey

  const handleManualSaved = () => setManualRefreshKey(v => v + 1)
  const showingPickTabs = tab === 'today' || tab === 'week'
  const showingBullyModel = showingPickTabs && modelView === 'bully'

  const body =
    tab === 'today' ? (
      showingBullyModel
        ? <BullySchedulePage label="Today's Bully-Model" days={1} refreshKey={refreshKey} onManualSaved={handleManualSaved} />
        : <PicksList label="Today's Picks" fetcher={api.picksToday} modelView={modelView} refreshKey={refreshKey} emptyText="No HIGH or ELITE picks today." onManualSaved={handleManualSaved} />
    ) :
    tab === 'week'  ? (
      showingBullyModel
        ? <BullySchedulePage label="This Week's Bully-Model" days={7} refreshKey={refreshKey} onManualSaved={handleManualSaved} />
        : <PicksList label="This Week" fetcher={api.picksWeek} modelView={modelView} refreshKey={refreshKey} emptyText="No HIGH or ELITE picks this week." onManualSaved={handleManualSaved} />
    ) :
    tab === 'schedule' ? <SchedulePage refreshKey={refreshKey} /> :
    tab === 'backtests' ? <BacktestsPage /> :
    tab === 'tracking' ? <SeasonTrackingPage refreshKey={refreshKey} /> :
                      <MyPicks refreshKey={refreshKey} />

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(16,185,129,0.12),_transparent_36%),linear-gradient(180deg,_#020617_0%,_#0f172a_100%)] text-slate-100">
      <header className="border-b border-slate-800/80 bg-slate-950/70 px-4 py-4 backdrop-blur">
        <div className="mx-auto max-w-5xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-emerald-300/80">Soccer Betting Model</p>
          <h1 className="mt-1 text-xl font-semibold tracking-wide">Picks, Tracking, and Head-to-Head Review</h1>
          <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-500">
            Auto-refresh every 15s
            {status?.latest_prediction_at ? ` · Picks ${new Date(status.latest_prediction_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
            {status?.latest_odds_at ? ` · Odds ${new Date(status.latest_odds_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
          </p>
          <nav className="mt-3 flex flex-wrap gap-2 text-sm">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={
                'rounded-full border px-3 py-1.5 transition ' +
                (tab === t.key
                  ? 'border-emerald-400 bg-emerald-400 text-slate-950'
                  : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200')
              }
            >
              {t.label}
            </button>
          ))}
        </nav>
        {showingPickTabs && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400">
            <span className="mr-1">View</span>
            {(['best', 'main', 'parallel', 'bully'] as ModelView[]).map(view => (
              <button
                key={view}
                onClick={() => setModelView(view)}
                className={
                  'rounded-full border px-3 py-1 transition ' +
                  (modelView === view
                    ? 'border-emerald-400 bg-emerald-400/15 text-emerald-300'
                    : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200')
                }
              >
                {modelViewLabel(view)}
              </button>
            ))}
          </div>
        )}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        {body}
      </main>
    </div>
  )
}
