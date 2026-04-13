import type { FixturePick, FixtureDetail } from './types'

const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const api = {
  picksToday: () => get<FixturePick[]>('/picks/today'),
  picksWeek: () => get<FixturePick[]>('/picks/week'),
  fixtureDetail: (id: number) => get<FixtureDetail>(`/fixture/${id}`),
}
