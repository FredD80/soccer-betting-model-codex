import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { ScheduledFixture } from '../api/types'
import { formatAmericanFromDecimal } from '../lib/odds'
import { formatEasternDateTime } from '../lib/time'

type LeagueTab = 'all' | string

function fmtLine(value: number | null) {
  return value == null ? '—' : (value > 0 ? `+${value}` : `${value}`)
}

interface Props {
  refreshKey?: number
}

export default function SchedulePage({ refreshKey = 0 }: Props) {
  const [fixtures, setFixtures] = useState<ScheduledFixture[]>([])
  const [leagueTab, setLeagueTab] = useState<LeagueTab>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.fixtureSchedule()
      .then(setFixtures)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [refreshKey])

  if (loading) return <p className="text-gray-400">Loading season schedule…</p>
  if (error) return <p className="text-red-400">Error: {error}</p>
  if (fixtures.length === 0) return <p className="text-gray-500">No upcoming fixtures in the season slate yet.</p>

  const leagueNames = Array.from(new Set(fixtures.map(fixture => fixture.league))).sort((a, b) => a.localeCompare(b))
  const visibleFixtures = leagueTab === 'all'
    ? fixtures
    : fixtures.filter(fixture => fixture.league === leagueTab)

  return (
    <section className="space-y-3">
      <div className="rounded-2xl border border-slate-800 bg-slate-950/55 p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="text-sm font-medium uppercase tracking-[0.2em] text-gray-400">
              Season Schedule
            </h2>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              Use the full season slate to spot upcoming matchups, then jump into the daily or weekly boards or track your own angles from the strongest cards.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs uppercase tracking-[0.18em]">
            <Link to="/today" className="rounded-full border border-slate-700 px-3 py-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100">
              Today Board
            </Link>
            <Link to="/week" className="rounded-full border border-slate-700 px-3 py-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100">
              Week Board
            </Link>
            <Link to="/tracking" className="rounded-full border border-slate-700 px-3 py-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100">
              Tracking
            </Link>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setLeagueTab('all')}
          className={
            'rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] transition ' +
            (leagueTab === 'all'
              ? 'border-gray-500 bg-gray-800 text-gray-100'
              : 'border-gray-800 bg-gray-950/60 text-gray-400 hover:text-gray-200')
          }
        >
          All
        </button>
        {leagueNames.map(league => (
          <button
            key={league}
            onClick={() => setLeagueTab(league)}
            className={
              'rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] transition ' +
              (leagueTab === league
                ? 'border-gray-500 bg-gray-800 text-gray-100'
                : 'border-gray-800 bg-gray-950/60 text-gray-400 hover:text-gray-200')
            }
          >
            {league}
          </button>
        ))}
      </div>
      {visibleFixtures.map(fixture => (
        <article key={fixture.fixture_id} className="rounded-2xl border border-gray-800 bg-gray-900/70 p-4">
          <div className="flex flex-col gap-1 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">{fixture.league}</p>
              <h3 className="mt-1 text-base font-semibold text-gray-100">
                {fixture.home_team} vs {fixture.away_team}
              </h3>
              <p className="text-sm text-gray-400">
                {formatEasternDateTime(fixture.kickoff_at)}
              </p>
            </div>
            {fixture.lines?.bookmaker ? (
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">
                {fixture.lines.bookmaker}
              </p>
            ) : null}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Moneyline</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div>Home: {formatAmericanFromDecimal(fixture.lines?.home_odds ?? null)}</div>
                <div>Draw: {formatAmericanFromDecimal(fixture.lines?.draw_odds ?? null)}</div>
                <div>Away: {formatAmericanFromDecimal(fixture.lines?.away_odds ?? null)}</div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Spread</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div>
                  Home {fmtLine(fixture.lines?.spread_home_line ?? null)} @ {formatAmericanFromDecimal(fixture.lines?.spread_home_odds ?? null)}
                </div>
                <div>
                  Away {fmtLine(fixture.lines?.spread_away_line ?? null)} @ {formatAmericanFromDecimal(fixture.lines?.spread_away_odds ?? null)}
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Total</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div>Line: {fixture.lines?.total_goals_line ?? '—'}</div>
                <div>Over: {formatAmericanFromDecimal(fixture.lines?.over_odds ?? null)}</div>
                <div>Under: {formatAmericanFromDecimal(fixture.lines?.under_odds ?? null)}</div>
              </div>
            </div>
          </div>
        </article>
      ))}
    </section>
  )
}
