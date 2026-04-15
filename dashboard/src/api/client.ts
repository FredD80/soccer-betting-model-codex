import type { BacktestRun, BacktestRunRequest, FixturePick, FixtureDetail } from './types'

const BASE = '/api'

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
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const api = {
  picksToday: () => get<FixturePick[]>('/picks/today'),
  picksWeek: () => get<FixturePick[]>('/picks/week'),
  picksUcl: () => get<FixturePick[]>('/picks/ucl'),
  fixtureDetail: (id: number) => get<FixtureDetail>(`/fixture/${id}`),
  backtestRuns: () => get<BacktestRun[]>('/backtests/runs'),
  runBacktestPicks: (payload: BacktestRunRequest) => post<BacktestRun[]>('/backtests/picks/run', payload),
}
