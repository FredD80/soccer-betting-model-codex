import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import PicksList from './pages/PicksList'
import BacktestsPage from './pages/BacktestsPage'
import SchedulePage from './pages/SchedulePage'
import BullySchedulePage from './pages/BullySchedulePage'
import SeasonTrackingPage from './pages/SeasonTrackingPage'
import { api } from './api/client'
import type { ModelView } from './api/types'
import { useDashboardAutoRefresh } from './hooks/useDashboardAutoRefresh'
import { modelPresentationForView, modelViewDescription, modelViewLabel } from './lib/modelLabels'

type Tab = 'today' | 'week' | 'schedule' | 'backtests' | 'tracking'

const TABS: { key: Tab; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'Week' },
  { key: 'schedule', label: 'Schedule' },
  { key: 'backtests', label: 'Backtests' },
  { key: 'tracking', label: 'Tracking' },
]

const TAB_PATH: Record<Tab, string> = {
  today: '/today',
  week: '/week',
  schedule: '/schedule',
  backtests: '/backtests',
  tracking: '/tracking',
}

function parseTab(pathname: string): Tab {
  const match = (Object.entries(TAB_PATH) as Array<[Tab, string]>).find(([, path]) => pathname === path)
  return match?.[0] ?? 'today'
}

function parseModelView(value: string | null): ModelView {
  if (value === 'main' || value === 'parallel' || value === 'bully') return value
  return 'best'
}

function formatStatusTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [manualRefreshKey, setManualRefreshKey] = useState(0)
  const { refreshKey: autoRefreshKey, status } = useDashboardAutoRefresh()
  const refreshKey = manualRefreshKey + autoRefreshKey
  const tab = parseTab(location.pathname)
  const modelView = parseModelView(searchParams.get('view'))

  useEffect(() => {
    if (location.pathname === '/') {
      navigate('/today', { replace: true })
      return
    }
    if (location.pathname === '/my-picks') {
      navigate('/tracking', { replace: true })
    }
  }, [location.pathname, navigate])

  const modelPresentation = modelPresentationForView(modelView)
  const handleManualSaved = () => setManualRefreshKey(v => v + 1)
  const showingPickTabs = tab === 'today' || tab === 'week'
  const showingBullyModel = showingPickTabs && modelView === 'bully'
  const tabHref = (nextTab: Tab) => {
    const params = new URLSearchParams()
    if ((nextTab === 'today' || nextTab === 'week') && modelView !== 'best') {
      params.set('view', modelView)
    }
    const search = params.toString()
    return `${TAB_PATH[nextTab]}${search ? `?${search}` : ''}`
  }
  const modelHref = (nextView: ModelView) => {
    const params = new URLSearchParams()
    if (nextView !== 'best') params.set('view', nextView)
    const search = params.toString()
    return `${TAB_PATH[tab]}${search ? `?${search}` : ''}`
  }

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
    <SeasonTrackingPage refreshKey={refreshKey} />

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(16,185,129,0.12),_transparent_36%),linear-gradient(180deg,_#020617_0%,_#0f172a_100%)] text-slate-100">
      <header className="border-b border-slate-800/80 bg-slate-950/70 px-4 py-4 backdrop-blur">
        <div className="mx-auto max-w-5xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-emerald-300/80">Soccer Betting Model</p>
          <h1 className="mt-1 text-xl font-semibold tracking-wide">Picks, Tracking, and Head-to-Head Review</h1>
          <p className="mt-2 text-xs text-slate-500">
            Updated picks {formatStatusTime(status?.latest_prediction_at)} · odds {formatStatusTime(status?.latest_odds_at)} · results {formatStatusTime(status?.latest_result_at)}
          </p>
          <nav className="mt-3 flex flex-wrap gap-2 text-sm">
            {TABS.map(t => (
              <NavLink
                key={t.key}
                to={tabHref(t.key)}
                className={({ isActive }) =>
                  'rounded-full border px-3 py-1.5 transition ' +
                  (isActive
                    ? 'border-emerald-400 bg-emerald-400 text-slate-950'
                    : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200')
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        {showingPickTabs && (
          <div className="mt-3 rounded-2xl border border-slate-800 bg-slate-950/55 p-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400">
                  <span>View</span>
                  <span className={`rounded-full border px-2.5 py-1 ${modelPresentation.accentBorder} ${modelPresentation.accentBg} ${modelPresentation.accentText}`}>
                    {modelViewLabel(modelView)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-400">
                  {modelViewDescription(modelView)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-xs uppercase tracking-[0.18em]">
                {(['best', 'main', 'parallel', 'bully'] as ModelView[]).map(view => (
                  <Link
                    key={view}
                    to={modelHref(view)}
                    className={
                      'rounded-full border px-3 py-1 transition ' +
                      (modelView === view
                        ? `${modelPresentation.accentBorder} ${modelPresentation.accentBg} ${modelPresentation.accentText}`
                        : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200')
                    }
                  >
                    {modelViewLabel(view)}
                  </Link>
                ))}
              </div>
            </div>
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
