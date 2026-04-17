import type {
  BacktestRun,
  BacktestRunRequest,
  FixturePick,
  FixtureDetail,
  ModelView,
  ScheduledFixture,
  ManualPick,
  ManualPickCreateRequest,
  ManualPickSummary,
  ManualVsModelComparison,
  ManualVsModelSummary,
  FixtureManualComparison,
} from './types'

const BASE = '/api'

function picksPath(path: string, modelView: ModelView): string {
  const suffix = modelView === 'best' ? '' : `?model_view=${modelView}`
  return `${path}${suffix}`
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const parsed = await res.json() as { detail?: string }
      if (parsed.detail) detail = parsed.detail
    } catch {
      // keep default detail
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  picksToday: (modelView: ModelView = 'best') => get<FixturePick[]>(picksPath('/picks/today', modelView)),
  picksWeek: (modelView: ModelView = 'best') => get<FixturePick[]>(picksPath('/picks/week', modelView)),
  picksLeague: (leagueId: string, modelView: ModelView = 'best') => get<FixturePick[]>(picksPath(`/picks/league/${leagueId}`, modelView)),
  fixtureDetail: (id: number) => get<FixtureDetail>(`/fixture/${id}`),
  fixtureSchedule: () => get<ScheduledFixture[]>('/fixture/schedule'),
  backtestRuns: () => get<BacktestRun[]>('/backtests/runs'),
  runBacktestPicks: (payload: BacktestRunRequest) => post<BacktestRun[]>('/backtests/picks/run', payload),
  createManualPick: (payload: ManualPickCreateRequest) => post<ManualPick>('/performance/manual-picks', payload),
  manualPicks: () => get<ManualPick[]>('/performance/manual-picks'),
  manualPickSummary: () => get<ManualPickSummary[]>('/performance/manual-picks/summary'),
  compareManualVsModels: () => get<ManualVsModelComparison[]>('/performance/compare/manual-vs-models'),
  compareManualVsModelsSummary: () => get<ManualVsModelSummary[]>('/performance/compare/manual-vs-models/summary'),
  compareFixtures: () => get<FixtureManualComparison[]>('/performance/compare/fixtures'),
}
