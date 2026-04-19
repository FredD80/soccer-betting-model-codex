import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'
import type { BullyScheduleFixture, SeasonTrackerResponse } from '../api/types'
import {
  BoardTable,
  FilterRow,
  FixtureDetailPanel,
  HeroStrip,
  RightRail,
  SideNav,
  sortFixtures,
  trackerGroup,
  type SortKey,
} from './BullyDashboard.parts'

interface Props {
  label?: string
  days?: number
  refreshKey?: number
  onManualSaved?: () => void
  status?: { latest_prediction_at?: string | null; latest_odds_at?: string | null; latest_result_at?: string | null } | null
}

export default function BullyDashboard(props: Props) {
  const { days, refreshKey = 0, onManualSaved, status } = props
  const [fixtures, setFixtures] = useState<BullyScheduleFixture[]>([])
  const [tracker, setTracker] = useState<SeasonTrackerResponse | null>(null)
  const [leagueTab, setLeagueTab] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('composite')
  const [openId, setOpenId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.bullySchedule(days, true)
      .then(data => {
        setFixtures(data)
        setOpenId(current => (current != null && data.some(fixture => fixture.fixture_id === current) ? current : null))
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [days, refreshKey])

  useEffect(() => {
    api.seasonTracker().then(setTracker).catch(() => {})
  }, [refreshKey])

  const leagueCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const fixture of fixtures) {
      counts.set(fixture.league, (counts.get(fixture.league) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  }, [fixtures])

  const leagueNames = leagueCounts.map(([league]) => league)
  const filteredFixtures = leagueTab === 'all' ? fixtures : fixtures.filter(fixture => fixture.league === leagueTab)
  const visibleFixtures = useMemo(() => sortFixtures(filteredFixtures, sortKey), [filteredFixtures, sortKey])
  const hero = visibleFixtures[0] ?? null
  const boardFixtures = hero ? visibleFixtures.slice(1) : []
  const trackerSummary = trackerGroup(tracker)

  if (loading) return <div className="card text-ink-2">Loading bully model schedule…</div>
  if (error) return <div className="card text-lose">Error: {error}</div>
  if (!hero) return <div className="card text-ink-2">No Elo bully model games are available yet.</div>

  return (
    <section className="grid gap-6 xl:grid-cols-[220px_minmax(0,1fr)_280px]">
      <SideNav days={days} fixtureCount={visibleFixtures.length} />

      <div className="min-w-0 space-y-4">
        <HeroStrip
          fixture={hero}
          isOpen={openId === hero.fixture_id}
          onToggle={() => setOpenId(openId === hero.fixture_id ? null : hero.fixture_id)}
        />
        {openId === hero.fixture_id && <FixtureDetailPanel fixture={hero} onManualSaved={onManualSaved} />}

        <FilterRow
          sortKey={sortKey}
          onSort={setSortKey}
          days={days}
          leagueNames={leagueNames}
          leagueTab={leagueTab}
          onLeagueChange={setLeagueTab}
        />

        <BoardTable
          rows={boardFixtures}
          openId={openId}
          onToggle={(id) => setOpenId(current => (current === id ? null : id))}
          onManualSaved={onManualSaved}
        />
      </div>

      <RightRail
        status={status}
        tracker={tracker}
        trackerSummary={trackerSummary}
        leagueCounts={leagueCounts}
      />
    </section>
  )
}
