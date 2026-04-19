import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { api } from './api/client'
import type { ModelView } from './api/types'
import { useDashboardAutoRefresh } from './hooks/useDashboardAutoRefresh'
import { modelPresentationForView, modelViewDescription, modelViewLabel } from './lib/modelLabels'
import BacktestsPage from './pages/BacktestsPage'
import BullyBoardPage from './pages/BullyBoardPage'
import PicksList from './pages/PicksList'
import SchedulePage from './pages/SchedulePage'
import SeasonTrackingPage from './pages/SeasonTrackingPage'

type Tab = 'today' | 'week' | 'schedule' | 'backtests' | 'tracking'

const TAB_PATH: Record<Tab, string> = {
  today: '/today',
  week: '/week',
  schedule: '/schedule',
  backtests: '/backtests',
  tracking: '/tracking',
}

const PRIMARY_TABS: { key: Tab; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'Week' },
  { key: 'schedule', label: 'Season' },
  { key: 'backtests', label: 'Backtests' },
  { key: 'tracking', label: 'Tracking' },
]

function parseTab(pathname: string): Tab {
  const match = (Object.entries(TAB_PATH) as Array<[Tab, string]>).find(([, path]) => pathname === path)
  return match?.[0] ?? 'today'
}

function parseModelView(value: string | null): ModelView {
  if (value === 'main' || value === 'parallel' || value === 'bully') return value
  return 'best'
}

function shellLinkClass(active: boolean): string {
  return `pill ${active ? 'pill-bully pill-active' : ''}`
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
      navigate('/today?view=bully', { replace: true })
      return
    }
    if (location.pathname === '/my-picks') {
      navigate('/tracking', { replace: true })
    }
  }, [location.pathname, navigate])

  const showingPickTabs = tab === 'today' || tab === 'week'
  const showingScheduleSection = showingPickTabs || tab === 'schedule'
  const showingBullyModel = showingPickTabs && modelView === 'bully'
  const modelPresentation = modelPresentationForView(modelView)
  const handleManualSaved = () => setManualRefreshKey(v => v + 1)

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
        ? <BullyBoardPage label="Today’s Bully Board" days={1} refreshKey={refreshKey} onManualSaved={handleManualSaved} status={status} />
        : <PicksList label="Today's Picks" fetcher={api.picksToday} modelView={modelView} refreshKey={refreshKey} emptyText="No HIGH or ELITE picks today." onManualSaved={handleManualSaved} />
    ) :
    tab === 'week' ? (
      showingBullyModel
        ? <BullyBoardPage label="This Week’s Bully Board" days={7} refreshKey={refreshKey} onManualSaved={handleManualSaved} status={status} />
        : <PicksList label="This Week" fetcher={api.picksWeek} modelView={modelView} refreshKey={refreshKey} emptyText="No HIGH or ELITE picks this week." onManualSaved={handleManualSaved} />
    ) :
    tab === 'schedule' ? <SchedulePage refreshKey={refreshKey} /> :
    tab === 'backtests' ? <BacktestsPage /> :
    <SeasonTrackingPage refreshKey={refreshKey} />

  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <header className="sticky top-0 z-30 border-b border-line-1/80 bg-bg-0/88 backdrop-blur-xl">
        <div className="mx-auto max-w-[1440px] px-4 py-4 sm:px-6">
          {/* Brand + title only — freshness moves into the right rail on BullyBoardPage */}
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] border border-bully/35 bg-[linear-gradient(180deg,rgba(224,181,78,0.18),rgba(14,21,36,0.92))] shadow-panel">
              <span className="font-mono text-xs font-semibold uppercase tracking-[0.28em] text-bully">SBM</span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="eyebrow text-bully">Soccer Betting Model</p>
              <h1 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-ink-0 sm:text-2xl">
                Bully-first market board
              </h1>
            </div>
          </div>

          <div className={`mt-4 flex flex-col gap-3 ${showingBullyModel ? 'xl:hidden' : 'xl:flex-row xl:items-center xl:justify-between'}`}>
            <nav className="flex flex-wrap gap-2">
              {PRIMARY_TABS.map(item => (
                <Link
                  key={item.key}
                  to={tabHref(item.key)}
                  className={shellLinkClass(tab === item.key)}
                >
                  {item.label}
                </Link>
              ))}
            </nav>

            {showingPickTabs && (
              <div className="flex flex-col gap-2 xl:items-end">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="filter-label">Model View</span>
                  {(['bully', 'best', 'main', 'parallel'] as ModelView[]).map(view => {
                    const presentation = modelPresentationForView(view)
                    return (
                      <Link
                        key={view}
                        to={modelHref(view)}
                        className={
                          'pill ' +
                          (modelView === view
                            ? `${presentation.accentBorder} ${presentation.accentBg} ${presentation.accentText} pill-active`
                            : '')
                        }
                      >
                        {modelViewLabel(view)}
                      </Link>
                    )
                  })}
                </div>
                <p className="max-w-2xl text-sm text-ink-2">
                  <span className={`font-medium ${modelPresentation.accentText}`}>{modelViewLabel(modelView)}</span>
                  {' · '}
                  {modelViewDescription(modelView)}
                </p>
              </div>
            )}

            {!showingPickTabs && showingScheduleSection && (
              <div className="rounded-full border border-line-1 bg-bg-2/88 px-4 py-2 text-sm text-ink-2">
                Full season schedule view
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8">
        {body}
      </main>
    </div>
  )
}
