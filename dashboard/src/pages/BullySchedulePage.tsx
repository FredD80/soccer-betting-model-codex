import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { BullyScheduleFixture, FixturePick, MoneylinePick } from '../api/types'
import ManualPickForm from '../components/ManualPickForm'
import { decimalToAmerican, formatAmericanFromDecimal } from '../lib/odds'
import { formatEasternDateTime } from '../lib/time'

type LeagueTab = 'all' | string
type BullySortKey = 'combo' | 'composite' | 'elo_gap' | 'two_plus' | 'clean_sheet'

const SORT_OPTIONS: { key: BullySortKey; label: string }[] = [
  { key: 'combo', label: 'SGP Lens' },
  { key: 'composite', label: 'Composite' },
  { key: 'elo_gap', label: 'Elo Gap' },
  { key: 'two_plus', label: '2+ Goals %' },
  { key: 'clean_sheet', label: 'Clean Sheet %' },
]

function fmtPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

function fmtGoals(value: number): string {
  return value.toFixed(2)
}

function fmtSigned(value: number | null): string {
  if (value == null) return '—'
  return value > 0 ? `+${value.toFixed(2)}` : value.toFixed(2)
}

function fmtLine(value: number | null) {
  return value == null ? '—' : (value > 0 ? `+${value}` : `${value}`)
}

function trendTone(value: number | null): string {
  if (value == null) return 'No xG trend'
  if (value > 0.05) return 'xG rising'
  if (value < -0.05) return 'xG falling'
  return 'xG steady'
}

function signalTone(value: number, high: number, medium: number): string {
  if (value >= high) return 'text-emerald-300'
  if (value >= medium) return 'text-amber-200'
  return 'text-slate-300'
}

function bullyCompositeScore(fixture: BullyScheduleFixture): number {
  const normalizedElo = Math.min(fixture.elo_gap, 300) / 300
  return (
    (normalizedElo * 0.4) +
    (fixture.favorite_two_plus_probability * 0.35) +
    (fixture.favorite_clean_sheet_probability * 0.25)
  )
}

function bullyComboScore(fixture: BullyScheduleFixture): number {
  return fixture.favorite_probability * fixture.favorite_two_plus_probability
}

function sortFixtures(fixtures: BullyScheduleFixture[], sortKey: BullySortKey): BullyScheduleFixture[] {
  const sorted = [...fixtures]
  sorted.sort((a, b) => {
    const delta =
      sortKey === 'combo'
        ? bullyComboScore(b) - bullyComboScore(a)
        : sortKey === 'elo_gap'
        ? b.elo_gap - a.elo_gap
        : sortKey === 'two_plus'
          ? b.favorite_two_plus_probability - a.favorite_two_plus_probability
          : sortKey === 'clean_sheet'
            ? b.favorite_clean_sheet_probability - a.favorite_clean_sheet_probability
            : bullyCompositeScore(b) - bullyCompositeScore(a)

    if (Math.abs(delta) > 1e-9) return delta
    if (a.is_bully_spot !== b.is_bully_spot) return a.is_bully_spot ? -1 : 1
    if (Math.abs(b.favorite_probability - a.favorite_probability) > 1e-9) {
      return b.favorite_probability - a.favorite_probability
    }
    return new Date(a.kickoff_at).getTime() - new Date(b.kickoff_at).getTime()
  })
  return sorted
}

interface Props {
  label?: string
  days?: number
  refreshKey?: number
  onManualSaved?: () => void
}

function favoriteOdds(fixture: BullyScheduleFixture): number | null {
  if (fixture.favorite_side === 'home') return fixture.lines?.home_odds ?? null
  return fixture.lines?.away_odds ?? null
}

function impliedProbability(decimalOdds: number | null): number | null {
  if (decimalOdds == null || decimalOdds <= 1) return null
  return 1 / decimalOdds
}

function confidenceTier(fixture: BullyScheduleFixture): MoneylinePick['confidence_tier'] {
  if (fixture.is_bully_spot && fixture.favorite_probability >= 0.68) return 'ELITE'
  if (fixture.is_bully_spot || fixture.favorite_probability >= 0.6) return 'HIGH'
  return 'MEDIUM'
}

function manualPickFixture(fixture: BullyScheduleFixture): FixturePick {
  const decimalOdds = favoriteOdds(fixture)
  const implied = impliedProbability(decimalOdds)
  const edge = implied == null ? null : fixture.favorite_probability - implied

  return {
    fixture_id: fixture.fixture_id,
    home_team: fixture.home_team,
    away_team: fixture.away_team,
    league: fixture.league,
    kickoff_at: fixture.kickoff_at,
    model_view: 'bully',
    best_spread: null,
    best_ou: null,
    best_moneyline: {
      model_name: fixture.model_name,
      model_version: fixture.model_version,
      outcome: fixture.favorite_side,
      probability: fixture.favorite_probability,
      ev_score: edge,
      confidence_tier: confidenceTier(fixture),
      final_probability: fixture.favorite_probability,
      edge_pct: edge,
      kelly_fraction: null,
      steam_downgraded: false,
      decimal_odds: decimalOdds,
      american_odds: decimalToAmerican(decimalOdds),
    },
    top_ev: edge,
  }
}

export default function BullySchedulePage({ label = 'Bully-Model', days, refreshKey = 0, onManualSaved }: Props) {
  const [fixtures, setFixtures] = useState<BullyScheduleFixture[]>([])
  const [leagueTab, setLeagueTab] = useState<LeagueTab>('all')
  const [sortKey, setSortKey] = useState<BullySortKey>('composite')
  const [useXgOverlay, setUseXgOverlay] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.bullySchedule(days, useXgOverlay)
      .then(setFixtures)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [days, useXgOverlay, refreshKey])

  if (loading) return <p className="text-gray-400">Loading bully model schedule…</p>
  if (error) return <p className="text-red-400">Error: {error}</p>
  if (fixtures.length === 0) return <p className="text-gray-500">No Elo bully model games are available yet.</p>

  const leagueNames = Array.from(new Set(fixtures.map(fixture => fixture.league))).sort((a, b) => a.localeCompare(b))
  const filteredFixtures = leagueTab === 'all'
    ? fixtures
    : fixtures.filter(fixture => fixture.league === leagueTab)
  const visibleFixtures = sortFixtures(filteredFixtures, sortKey)
  const highlighted = visibleFixtures.filter(fixture => fixture.is_bully_spot).slice(0, 3)

  return (
    <section className="space-y-4">
      <div className="space-y-2">
        <div className="rounded-2xl border border-amber-500/30 bg-slate-950/55 p-3 sm:p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-amber-200">
                  Bully
                </span>
                <h2 className="text-sm font-medium uppercase tracking-[0.2em] text-gray-300">
                  {label}
                </h2>
              </div>
              <p className="mt-2 text-xs text-slate-400 sm:hidden">
                Elo mismatch board ranked by SGP Lens.
              </p>
              <p className="mt-2 hidden text-sm text-slate-400 sm:block">
                Strength-gap spots first. Elo sets the baseline, then recent xG form adjusts the split. Use the SGP Lens to rank for your favorite-plus-2-goals style without hard-filtering games out.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs uppercase tracking-[0.18em]">
              <Link to="/tracking" className="rounded-full border border-amber-500/40 px-3 py-1 text-amber-200 transition hover:bg-amber-500/10">
                Season Tracker
              </Link>
              <Link to="/backtests" className="rounded-full border border-slate-700 px-3 py-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100">
                Backtests
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setLeagueTab('all')}
          className={
            'rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] transition ' +
            (leagueTab === 'all'
              ? 'border-amber-400 bg-amber-400/15 text-amber-200'
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
                ? 'border-amber-400 bg-amber-400/15 text-amber-200'
                : 'border-gray-800 bg-gray-950/60 text-gray-400 hover:text-gray-200')
            }
          >
            {league}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Sort By</span>
        {SORT_OPTIONS.map(option => (
          <button
            key={option.key}
            onClick={() => setSortKey(option.key)}
            className={
              'rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em] transition ' +
              (sortKey === option.key
                ? 'border-emerald-400 bg-emerald-400/15 text-emerald-300'
                : 'border-slate-800 bg-slate-950/60 text-slate-400 hover:text-slate-200')
            }
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-950/50 px-3 py-3 sm:px-4">
        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">xG Overlay</div>
          <p className="text-xs text-slate-300 sm:hidden">
            League-scaled view-only filter.
          </p>
          <p className="hidden text-sm text-slate-300 sm:block">
            View-only filter using league-scaled projected xG-delta thresholds. Turn it off to see pure Elo-gap bully spots.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={useXgOverlay}
          onClick={() => setUseXgOverlay(current => !current)}
          className={
            'inline-flex items-center gap-3 rounded-full border px-3 py-2 text-xs uppercase tracking-[0.2em] transition ' +
            (useXgOverlay
              ? 'border-emerald-400/60 bg-emerald-400/15 text-emerald-300'
              : 'border-slate-700 bg-slate-900 text-slate-300')
          }
        >
          <span
            className={
              'relative h-6 w-11 rounded-full transition ' +
              (useXgOverlay ? 'bg-emerald-500/70' : 'bg-slate-700')
            }
          >
            <span
              className={
                'absolute top-0.5 h-5 w-5 rounded-full bg-white transition ' +
                (useXgOverlay ? 'left-[22px]' : 'left-0.5')
              }
            />
          </span>
          <span>{useXgOverlay ? 'Overlay On' : 'Overlay Off'}</span>
        </button>
      </div>

      {highlighted.length > 0 && (
        <div className="grid gap-3 md:grid-cols-3">
          {highlighted.map(fixture => (
            <article key={`highlight-${fixture.fixture_id}`} className="rounded-2xl border border-amber-500/30 bg-[linear-gradient(180deg,rgba(245,158,11,0.16),rgba(15,23,42,0.9))] p-4">
              <p className="text-[11px] uppercase tracking-[0.24em] text-amber-200/80">Top Bully Spot</p>
              <h3 className="mt-2 text-base font-semibold text-slate-100">{fixture.favorite_team}</h3>
              <p className="text-sm text-slate-300">vs {fixture.underdog_team}</p>
              <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-400">
                {fixture.league} · {formatEasternDateTime(fixture.kickoff_at)}
              </p>
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-200">
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Elo Gap</p>
                  <p className="mt-1 text-lg font-semibold text-amber-200">{fixture.elo_gap.toFixed(0)}</p>
                </div>
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Favorite Win</p>
                  <p className="mt-1 text-lg font-semibold text-emerald-300">{fmtPct(fixture.favorite_probability)}</p>
                </div>
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Favorite 2+ Goals</p>
                  <p className={`mt-1 text-lg font-semibold ${signalTone(fixture.favorite_two_plus_probability, 0.56, 0.45)}`}>
                    {fmtPct(fixture.favorite_two_plus_probability)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Favorite xG</p>
                  <p className="mt-1 text-lg font-semibold text-sky-300">
                    {fmtGoals(fixture.favorite_expected_goals)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Favorite Shutout</p>
                  <p className={`mt-1 text-lg font-semibold ${signalTone(fixture.favorite_clean_sheet_probability, 0.42, 0.30)}`}>
                    {fmtPct(fixture.favorite_clean_sheet_probability)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">xG Delta</p>
                  <p className="mt-1 text-lg font-semibold text-emerald-300">
                    +{fmtGoals(fixture.expected_goals_delta)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">SGP Lens</p>
                  <p className="mt-1 text-lg font-semibold text-emerald-300">
                    {fmtPct(bullyComboScore(fixture))}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {visibleFixtures.map(fixture => (
        <article key={fixture.fixture_id} className="rounded-2xl border border-gray-800 bg-gray-900/70 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">{fixture.league}</p>
                <span className={
                  'rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] ' +
                  (fixture.is_bully_spot
                    ? 'border-amber-400/50 bg-amber-400/10 text-amber-200'
                    : 'border-slate-700 bg-slate-900/70 text-slate-400')
                }>
                  {fixture.is_bully_spot ? 'Bully Spot' : 'Watchlist'}
                </span>
              </div>
              <h3 className="mt-1 text-base font-semibold text-gray-100">
                {fixture.home_team} vs {fixture.away_team}
              </h3>
              <p className="text-sm text-gray-400">{formatEasternDateTime(fixture.kickoff_at)}</p>
              <p className="mt-2 text-sm text-amber-200">
                {fixture.favorite_team} favored by {fixture.elo_gap.toFixed(0)} Elo points
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2 text-right">
              <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{fixture.model_name}</p>
              <p className="mt-1 text-sm font-semibold text-slate-100">{fmtPct(fixture.favorite_probability)}</p>
              <p className="text-xs text-slate-400">favorite win probability</p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Ratings</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div>{fixture.home_team}: {fixture.home_elo.toFixed(0)}</div>
                <div>{fixture.away_team}: {fixture.away_elo.toFixed(0)}</div>
                <div className="text-amber-200">Gap: {fixture.elo_gap.toFixed(0)}</div>
                <div className="text-emerald-300">Composite: {fmtPct(bullyCompositeScore(fixture))}</div>
                <div className="text-sky-300">SGP Lens: {fmtPct(bullyComboScore(fixture))}</div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Outcome Probabilities</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div>Home: {fmtPct(fixture.home_probability)}</div>
                <div>Draw: {fmtPct(fixture.draw_probability)}</div>
                <div>Away: {fmtPct(fixture.away_probability)}</div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Scoring Signals</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div className="text-sky-300">
                  {fixture.home_team} xG: {fmtGoals(fixture.home_expected_goals)}
                </div>
                <div className="text-sky-300">
                  {fixture.away_team} xG: {fmtGoals(fixture.away_expected_goals)}
                </div>
                <div className="text-emerald-300">
                  xG delta: +{fmtGoals(fixture.expected_goals_delta)} to {fixture.favorite_team}
                </div>
                <div className={signalTone(fixture.home_two_plus_probability, 0.56, 0.45)}>
                  {fixture.home_team} 2+: {fmtPct(fixture.home_two_plus_probability)}
                </div>
                <div className={signalTone(fixture.away_two_plus_probability, 0.56, 0.45)}>
                  {fixture.away_team} 2+: {fmtPct(fixture.away_two_plus_probability)}
                </div>
                <div className={signalTone(fixture.home_clean_sheet_probability, 0.42, 0.30)}>
                  {fixture.home_team} clean sheet: {fmtPct(fixture.home_clean_sheet_probability)}
                </div>
                <div className={signalTone(fixture.away_clean_sheet_probability, 0.42, 0.30)}>
                  {fixture.away_team} clean sheet: {fmtPct(fixture.away_clean_sheet_probability)}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3 md:col-span-2">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">xG Context</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div>{fixture.home_team}: {trendTone(fixture.home_xg_trend)} ({fmtSigned(fixture.home_xg_trend)})</div>
                <div>{fixture.away_team}: {trendTone(fixture.away_xg_trend)} ({fmtSigned(fixture.away_xg_trend)})</div>
                <div className="text-slate-400">Shift applied: {fmtSigned(fixture.trend_adjustment)}</div>
              </div>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-950/60 p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Bully Read</p>
              <div className="mt-2 space-y-1 text-sm text-gray-200">
                <div>{fixture.favorite_team} win: {fmtPct(fixture.favorite_probability)}</div>
                <div>{fixture.favorite_team} xG: {fmtGoals(fixture.favorite_expected_goals)}</div>
                <div>{fixture.underdog_team} xG: {fmtGoals(fixture.underdog_expected_goals)}</div>
                <div>{fixture.favorite_team} 2+: {fmtPct(fixture.favorite_two_plus_probability)}</div>
                <div>SGP Lens: {fmtPct(bullyComboScore(fixture))}</div>
                <div>{fixture.favorite_team} clean sheet: {fmtPct(fixture.favorite_clean_sheet_probability)}</div>
              </div>
            </div>
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

          <div className="mt-4">
            <ManualPickForm pick={manualPickFixture(fixture)} onSaved={onManualSaved} />
          </div>
        </article>
      ))}
    </section>
  )
}
