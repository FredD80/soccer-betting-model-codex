import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { api } from '../api/client'
import type { BullyScheduleFixture, FixturePick, MoneylinePick, SeasonTrackerResponse } from '../api/types'
import ManualPickForm from '../components/ManualPickForm'
import { decimalToAmerican, formatAmericanFromDecimal } from '../lib/odds'
import { formatEasternDateTime } from '../lib/time'

type LeagueTab = 'all' | string
type BullySortKey = 'composite' | 'combo' | 'elo_gap' | 'favorite_win' | 'two_plus' | 'clean_sheet' | 'kickoff'

const SORT_OPTIONS: { key: BullySortKey; label: string }[] = [
  { key: 'composite', label: 'Composite' },
  { key: 'combo', label: 'SGP Lens' },
  { key: 'elo_gap', label: 'Elo Gap' },
  { key: 'favorite_win', label: 'Win' },
  { key: 'two_plus', label: '2+ Goals' },
  { key: 'clean_sheet', label: 'Clean Sheet' },
  { key: 'kickoff', label: 'Kickoff' },
]

const DESKTOP_GRID = 'lg:grid-cols-[36px_minmax(0,1.9fr)_108px_72px_72px_72px_72px_88px_84px]'

interface Props {
  label?: string
  days?: number
  refreshKey?: number
  onManualSaved?: () => void
}

function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value == null) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function fmtGoals(value: number | null | undefined): string {
  if (value == null) return '—'
  return value.toFixed(2)
}

function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}`
}

function fmtSignedPct(value: number | null | undefined, digits = 1): string {
  if (value == null) return '—'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(digits)}%`
}

function fmtLine(value: number | null | undefined): string {
  if (value == null) return '—'
  return value > 0 ? `+${value}` : `${value}`
}

function favoriteOdds(fixture: BullyScheduleFixture): number | null {
  if (fixture.favorite_side === 'home') return fixture.lines?.home_odds ?? null
  return fixture.lines?.away_odds ?? null
}

function favoriteTrend(fixture: BullyScheduleFixture): number | null {
  return fixture.favorite_side === 'home' ? fixture.home_xg_trend : fixture.away_xg_trend
}

function impliedProbability(decimalOdds: number | null): number | null {
  if (decimalOdds == null || decimalOdds <= 1) return null
  return 1 / decimalOdds
}

function bullyComboScore(fixture: BullyScheduleFixture): number {
  return fixture.favorite_probability * fixture.favorite_two_plus_probability
}

function bullyCompositeScore(fixture: BullyScheduleFixture): number {
  return (
    bullyComboScore(fixture) * 0.5 +
    fixture.favorite_probability * 0.25 +
    Math.min(1, fixture.elo_gap / 400) * 0.25
  )
}

function sortFixtures(fixtures: BullyScheduleFixture[], sortKey: BullySortKey): BullyScheduleFixture[] {
  const sorted = [...fixtures]
  sorted.sort((a, b) => {
    const delta =
      sortKey === 'combo'
        ? bullyComboScore(b) - bullyComboScore(a)
        : sortKey === 'elo_gap'
          ? b.elo_gap - a.elo_gap
          : sortKey === 'favorite_win'
            ? b.favorite_probability - a.favorite_probability
            : sortKey === 'two_plus'
              ? b.favorite_two_plus_probability - a.favorite_two_plus_probability
              : sortKey === 'clean_sheet'
                ? b.favorite_clean_sheet_probability - a.favorite_clean_sheet_probability
                : sortKey === 'kickoff'
                  ? new Date(a.kickoff_at).getTime() - new Date(b.kickoff_at).getTime()
                  : bullyCompositeScore(b) - bullyCompositeScore(a)

    if (Math.abs(delta) > 1e-9) return delta
    if (a.is_bully_spot !== b.is_bully_spot) return a.is_bully_spot ? -1 : 1
    return b.favorite_probability - a.favorite_probability
  })
  return sorted
}

function trendLabel(value: number | null | undefined): string {
  if (value == null) return 'Neutral'
  if (value > 0.05) return 'Rising'
  if (value < -0.05) return 'Falling'
  return 'Stable'
}

function trendTone(value: number | null | undefined): string {
  if (value == null) return 'text-ink-2'
  if (value > 0.05) return 'text-win'
  if (value < -0.05) return 'text-lose'
  return 'text-warn'
}

function signalTone(value: number | null | undefined): string {
  if (value == null) return 'text-ink-2'
  if (value >= 0.62) return 'text-bully'
  if (value >= 0.5) return 'text-win'
  if (value >= 0.36) return 'text-warn'
  return 'text-ink-1'
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

function fixtureTier(fixture: BullyScheduleFixture): 'ELITE' | 'HIGH' | 'WATCH' {
  if (fixture.is_bully_spot && fixture.favorite_probability >= 0.68) return 'ELITE'
  if (fixture.is_bully_spot || fixture.favorite_probability >= 0.6) return 'HIGH'
  return 'WATCH'
}

function tierClass(tier: 'ELITE' | 'HIGH' | 'WATCH'): string {
  if (tier === 'ELITE') return 'border-bully/35 bg-bully/16 text-bully'
  if (tier === 'HIGH') return 'border-win/30 bg-win/10 text-win'
  return 'border-line-2 bg-bg-3 text-ink-1'
}

function trackerGroup(data: SeasonTrackerResponse | null) {
  if (!data) return null
  return data.model_groups.find(group => /bully/i.test(`${group.key} ${group.label} ${group.group_type}`)) ?? data.model_groups[0] ?? null
}

function SummaryStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-[14px] border border-line-1 bg-bg-1/80 px-3 py-3">
      <p className="stat-label">{label}</p>
      <p className={`mt-1 font-mono text-lg ${accent ?? 'text-ink-0'}`}>{value}</p>
    </div>
  )
}

function railDotClass(tone: 'bully' | 'best' | 'main' | 'parallel'): string {
  if (tone === 'bully') return 'bg-bully shadow-[0_0_12px_rgba(224,181,78,0.4)]'
  if (tone === 'best') return 'bg-win shadow-[0_0_12px_rgba(94,193,117,0.25)]'
  if (tone === 'main') return 'bg-edge shadow-[0_0_12px_rgba(97,181,255,0.25)]'
  return 'bg-ink-3'
}

function railLinkClass(active: boolean): string {
  return (
    'flex items-center justify-between gap-3 rounded-[12px] border px-3 py-2.5 text-sm transition-colors ' +
    (active
      ? 'border-bully/35 bg-bully/12 text-bully'
      : 'border-transparent text-ink-1 hover:border-line-1 hover:bg-bg-3/70 hover:text-ink-0')
  )
}

function LeftRailSection({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div>
      <p className="eyebrow">{title}</p>
      <div className="mt-3 space-y-1.5">{children}</div>
    </div>
  )
}

function LeftRailLink({
  to,
  label,
  count,
  active,
  tone,
}: {
  to: string
  label: string
  count?: string
  active?: boolean
  tone?: 'bully' | 'best' | 'main' | 'parallel'
}) {
  return (
    <Link to={to} className={railLinkClass(Boolean(active))}>
      <span className="flex min-w-0 items-center gap-2.5">
        {tone && <span className={`h-2 w-2 shrink-0 rounded-full ${railDotClass(tone)}`} />}
        <span className="truncate">{label}</span>
      </span>
      {count && <span className="font-mono text-xs text-ink-3">{count}</span>}
    </Link>
  )
}

function LeftRail({
  days,
  fixtureCount,
  bullyCount,
  leagueCount,
}: {
  days?: number
  fixtureCount: number
  bullyCount: number
  leagueCount: number
}) {
  const location = useLocation()
  const pickPath = days === 7 ? '/week' : '/today'
  const currentPath = location.pathname

  return (
    <aside className="hidden xl:block">
      <div className="sticky top-[118px] space-y-4">
        <div className="card bg-[linear-gradient(180deg,rgba(24,34,53,0.94),rgba(10,16,28,0.98))]">
          <LeftRailSection title="Views">
            <LeftRailLink to={`${pickPath}?view=bully`} label="Bully Board" count={String(fixtureCount)} active tone="bully" />
            <LeftRailLink to={`${pickPath}?view=best`} label="Best" tone="best" />
            <LeftRailLink to={`${pickPath}?view=main`} label="Main" tone="main" />
            <LeftRailLink to={`${pickPath}?view=parallel`} label="Parallel" tone="parallel" />
          </LeftRailSection>

          <div className="my-4 border-t border-line-1/80" />

          <LeftRailSection title="Window">
            <LeftRailLink to="/today?view=bully" label="Today" count={days === 1 ? String(fixtureCount) : undefined} active={days === 1} />
            <LeftRailLink to="/week?view=bully" label="This Week" count={days === 7 ? String(fixtureCount) : undefined} active={days === 7} />
            <LeftRailLink to="/schedule" label="Season" active={currentPath === '/schedule'} />
          </LeftRailSection>

          <div className="my-4 border-t border-line-1/80" />

          <LeftRailSection title="Tools">
            <LeftRailLink to="/backtests" label="Backtests" active={currentPath === '/backtests'} />
            <LeftRailLink to="/tracking" label="Season Tracker" active={currentPath === '/tracking'} />
          </LeftRailSection>
        </div>

        <div className="card">
          <p className="eyebrow text-bully">Board Snapshot</p>
          <div className="mt-3 grid gap-3">
            <SummaryStat label="Live Fixtures" value={String(fixtureCount)} />
            <SummaryStat label="Bully Spots" value={String(bullyCount)} accent="text-bully" />
            <SummaryStat label="Leagues" value={String(leagueCount)} />
          </div>
        </div>
      </div>
    </aside>
  )
}

function FixtureDetailPanel({
  fixture,
  onManualSaved,
}: {
  fixture: BullyScheduleFixture
  onManualSaved?: () => void
}) {
  const trend = favoriteTrend(fixture)
  const implied = impliedProbability(favoriteOdds(fixture))
  const edge = implied == null ? null : fixture.favorite_probability - implied

  return (
    <div className="border-t border-line-1 bg-bg-1/92 px-4 py-4 lg:px-5">
      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr_1fr]">
        <div>
          <p className="eyebrow text-bully">Why It’s On The Board</p>
          <p className="mt-2 text-sm leading-6 text-ink-1">
            {fixture.favorite_team} holds a <span className="text-bully">+{fixture.elo_gap.toFixed(0)} Elo gap</span>, a
            {` ${fmtPct(fixture.favorite_probability)} `}win read, and a {fmtPct(fixture.favorite_two_plus_probability)} chance to score 2+.
            The current xG trend is <span className={trendTone(trend)}>{trendLabel(trend).toLowerCase()}</span>, with a
            {` ${fmtGoals(fixture.expected_goals_delta)} `}expected-goal edge over {fixture.underdog_team}.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <SummaryStat label="Moneyline" value={formatAmericanFromDecimal(favoriteOdds(fixture))} accent="text-bully" />
            <SummaryStat label="Model Edge" value={fmtSignedPct(edge)} accent={edge != null && edge >= 0 ? 'text-win' : 'text-lose'} />
            <SummaryStat label="Trend" value={fmtSigned(trend)} accent={trendTone(trend)} />
          </div>
        </div>

        <div>
          <p className="eyebrow">Model Inputs</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <SummaryStat label={`${fixture.favorite_team} xG`} value={fmtGoals(fixture.favorite_expected_goals)} accent="text-edge" />
            <SummaryStat label={`${fixture.underdog_team} xG`} value={fmtGoals(fixture.underdog_expected_goals)} />
            <SummaryStat label="Fav 2+" value={fmtPct(fixture.favorite_two_plus_probability)} accent={signalTone(fixture.favorite_two_plus_probability)} />
            <SummaryStat label="Clean Sheet" value={fmtPct(fixture.favorite_clean_sheet_probability)} accent={signalTone(fixture.favorite_clean_sheet_probability)} />
            <SummaryStat
              label="Spread"
              value={
                fixture.favorite_side === 'home'
                  ? `${fmtLine(fixture.lines?.spread_home_line)} @ ${formatAmericanFromDecimal(fixture.lines?.spread_home_odds ?? null)}`
                  : `${fmtLine(fixture.lines?.spread_away_line)} @ ${formatAmericanFromDecimal(fixture.lines?.spread_away_odds ?? null)}`
              }
            />
            <SummaryStat
              label="Total"
              value={
                fixture.lines?.total_goals_line == null
                  ? '—'
                  : `${fixture.lines.total_goals_line} / ${formatAmericanFromDecimal(fixture.lines?.over_odds ?? null)}`
              }
            />
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-[16px] border border-line-1 bg-bg-2/90 p-4">
            <p className="eyebrow">Board Angles</p>
            <div className="mt-3 space-y-2 text-sm text-ink-1">
              <div className="flex items-center justify-between gap-3">
                <span>Composite</span>
                <span className="font-mono text-bully">{fmtPct(bullyCompositeScore(fixture))}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>SGP Lens</span>
                <span className="font-mono text-edge">{fmtPct(bullyComboScore(fixture))}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Win Probability</span>
                <span className="font-mono text-win">{fmtPct(fixture.favorite_probability)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Clean Sheet</span>
                <span className={`font-mono ${signalTone(fixture.favorite_clean_sheet_probability)}`}>{fmtPct(fixture.favorite_clean_sheet_probability)}</span>
              </div>
            </div>
          </div>
          <ManualPickForm pick={manualPickFixture(fixture)} onSaved={onManualSaved} />
        </div>
      </div>
    </div>
  )
}

function HeroStrip({
  fixture,
  isOpen,
  onToggle,
}: {
  fixture: BullyScheduleFixture
  isOpen: boolean
  onToggle: () => void
}) {
  return (
    <div className="card overflow-hidden p-0">
      <div className="grid gap-5 border-l-[3px] border-l-bully bg-[linear-gradient(90deg,rgba(224,181,78,0.14),transparent_60%),rgba(14,21,36,0.96)] px-5 py-5 xl:grid-cols-[1.15fr_auto_auto] xl:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex rounded-full border px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.22em] ${tierClass(fixtureTier(fixture))}`}>
              {fixtureTier(fixture)}
            </span>
            <span className="eyebrow">{fixture.league}</span>
            <span className="eyebrow">{formatEasternDateTime(fixture.kickoff_at)}</span>
          </div>
          <h2 className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-ink-0">
            {fixture.favorite_team} <span className="text-ink-3">vs</span> {fixture.underdog_team}
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-ink-2">
            Top composite Bully spot for this window. Elo gap, price, and scoring upside all align.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5 xl:min-w-[470px]">
          <SummaryStat label="Elo" value={`+${fixture.elo_gap.toFixed(0)}`} accent="text-bully" />
          <SummaryStat label="Win" value={fmtPct(fixture.favorite_probability)} accent="text-win" />
          <SummaryStat label="Fav 2+" value={fmtPct(fixture.favorite_two_plus_probability)} accent={signalTone(fixture.favorite_two_plus_probability)} />
          <SummaryStat label="SGP" value={fmtPct(bullyComboScore(fixture))} accent="text-edge" />
          <SummaryStat label="Odds" value={formatAmericanFromDecimal(favoriteOdds(fixture))} />
        </div>

        <button type="button" onClick={onToggle} className="pill pill-bully h-fit justify-center px-4 py-2.5">
          {isOpen ? 'Hide Read' : 'Track Pick'}
        </button>
      </div>
    </div>
  )
}

function BoardRow({
  fixture,
  index,
  isOpen,
  onToggle,
  onManualSaved,
}: {
  fixture: BullyScheduleFixture
  index: number
  isOpen: boolean
  onToggle: () => void
  onManualSaved?: () => void
}) {
  const tier = fixtureTier(fixture)

  return (
    <>
      <button
        type="button"
        onClick={onToggle}
        className={`hidden w-full lg:grid ${DESKTOP_GRID} items-center gap-3 border-b border-line-1 px-4 py-3 text-left transition-colors hover:bg-bg-3/60 ${
          isOpen ? 'bg-bg-3/75' : ''
        } ${fixture.is_bully_spot ? 'border-l-[3px] border-l-bully pl-[13px]' : ''}`}
      >
        <div className="font-mono text-xs text-ink-3">{String(index).padStart(2, '0')}</div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-ink-0">
            {fixture.favorite_team} <span className="font-normal text-ink-3">vs {fixture.underdog_team}</span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span className="eyebrow">{fixture.league}</span>
            <span className={`inline-flex rounded-full border px-2 py-1 font-mono text-[9px] tracking-[0.2em] ${tierClass(tier)}`}>
              {tier}
            </span>
          </div>
        </div>
        <div className="font-mono text-xs text-ink-1">{formatEasternDateTime(fixture.kickoff_at)}</div>
        <div className="font-mono text-sm text-bully">+{fixture.elo_gap.toFixed(0)}</div>
        <div className="font-mono text-sm text-win">{fmtPct(fixture.favorite_probability)}</div>
        <div className={`font-mono text-sm ${signalTone(fixture.favorite_two_plus_probability)}`}>{fmtPct(fixture.favorite_two_plus_probability)}</div>
        <div className={`font-mono text-sm ${signalTone(fixture.favorite_clean_sheet_probability)}`}>{fmtPct(fixture.favorite_clean_sheet_probability)}</div>
        <div className="font-mono text-sm text-edge">{fmtPct(bullyComboScore(fixture))}</div>
        <div className="text-right font-mono text-sm text-ink-0">{formatAmericanFromDecimal(favoriteOdds(fixture))}</div>
      </button>
      {isOpen && (
        <div className="hidden lg:block">
          <FixtureDetailPanel fixture={fixture} onManualSaved={onManualSaved} />
        </div>
      )}
    </>
  )
}

export default function BullyBoardPage({ label = 'Bully Board', days, refreshKey = 0, onManualSaved }: Props) {
  const [fixtures, setFixtures] = useState<BullyScheduleFixture[]>([])
  const [tracker, setTracker] = useState<SeasonTrackerResponse | null>(null)
  const [leagueTab, setLeagueTab] = useState<LeagueTab>('all')
  const [sortKey, setSortKey] = useState<BullySortKey>('composite')
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
  const averageElo = visibleFixtures.length === 0 ? null : visibleFixtures.reduce((sum, fixture) => sum + fixture.elo_gap, 0) / visibleFixtures.length
  const averageWin = visibleFixtures.length === 0 ? null : visibleFixtures.reduce((sum, fixture) => sum + fixture.favorite_probability, 0) / visibleFixtures.length
  const bullyCount = visibleFixtures.filter(fixture => fixture.is_bully_spot).length

  useEffect(() => {
    if (hero && openId == null) {
      setOpenId(hero.fixture_id)
    }
  }, [hero, openId])

  if (loading) return <div className="card text-ink-2">Loading bully model schedule…</div>
  if (error) return <div className="card text-lose">Error: {error}</div>
  if (!hero) return <div className="card text-ink-2">No Elo bully model games are available yet.</div>

  return (
    <section className="grid gap-6 xl:grid-cols-[240px_minmax(0,1fr)_320px]">
      <LeftRail
        days={days}
        fixtureCount={visibleFixtures.length}
        bullyCount={bullyCount}
        leagueCount={leagueCounts.length}
      />

      <div className="min-w-0 space-y-4">
        <div className="card bg-[linear-gradient(180deg,rgba(224,181,78,0.12),rgba(14,21,36,0.96))]">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="pill pill-bully pill-active">{label}</span>
                <span className="eyebrow">Bully-first dashboard</span>
              </div>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-ink-1">
                The uploaded handoff is now mapped onto the live bully schedule feed. Composite rank leads, SGP Lens stays visible,
                and each board row expands into the current manual tracking workflow.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <SummaryStat label="Slate" value={String(visibleFixtures.length)} />
              <SummaryStat label="Bully Spots" value={String(bullyCount)} accent="text-bully" />
              <SummaryStat label="Avg Elo" value={averageElo == null ? '—' : `+${averageElo.toFixed(0)}`} accent="text-bully" />
              <SummaryStat label="Avg Win" value={fmtPct(averageWin)} accent="text-win" />
            </div>
          </div>
        </div>

        <HeroStrip fixture={hero} isOpen={openId === hero.fixture_id} onToggle={() => setOpenId(openId === hero.fixture_id ? null : hero.fixture_id)} />
        {openId === hero.fixture_id && <FixtureDetailPanel fixture={hero} onManualSaved={onManualSaved} />}

        <div className="card">
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="filter-label">League</span>
              <button type="button" onClick={() => setLeagueTab('all')} className={`pill ${leagueTab === 'all' ? 'pill-bully pill-active' : ''}`}>All</button>
              {leagueNames.map(league => (
                <button
                  key={league}
                  type="button"
                  onClick={() => setLeagueTab(league)}
                  className={`pill ${leagueTab === league ? 'pill-bully pill-active' : ''}`}
                >
                  {league}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="filter-label">Sort</span>
              {SORT_OPTIONS.map(option => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setSortKey(option.key)}
                  className={`pill ${sortKey === option.key ? 'pill-bully pill-active' : ''}`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="card hidden overflow-hidden p-0 lg:block">
          <div className={`grid ${DESKTOP_GRID} gap-3 border-b border-line-1 px-4 py-3 font-mono text-[10px] uppercase tracking-[0.2em] text-ink-3`}>
            <span>#</span>
            <span>Fixture</span>
            <span>KO</span>
            <span>Elo</span>
            <span>Win</span>
            <span>2+</span>
            <span>Clean</span>
            <span>SGP</span>
            <span className="text-right">Odds</span>
          </div>
          {boardFixtures.map((fixture, index) => (
            <BoardRow
              key={fixture.fixture_id}
              fixture={fixture}
              index={index + 2}
              isOpen={openId === fixture.fixture_id}
              onToggle={() => setOpenId(openId === fixture.fixture_id ? null : fixture.fixture_id)}
              onManualSaved={onManualSaved}
            />
          ))}
        </div>

        <div className="grid gap-4 lg:hidden">
          {boardFixtures.map((fixture, index) => (
            <article key={fixture.fixture_id} className="card overflow-hidden p-0">
              <button
                type="button"
                onClick={() => setOpenId(openId === fixture.fixture_id ? null : fixture.fixture_id)}
                className={`w-full border-l-[3px] px-4 py-4 text-left ${fixture.is_bully_spot ? 'border-l-bully' : 'border-l-line-2'}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="eyebrow">#{String(index + 2).padStart(2, '0')}</span>
                      <span className={`inline-flex rounded-full border px-2 py-1 font-mono text-[9px] tracking-[0.2em] ${tierClass(fixtureTier(fixture))}`}>
                        {fixtureTier(fixture)}
                      </span>
                    </div>
                    <h3 className="mt-2 text-lg font-semibold text-ink-0">
                      {fixture.favorite_team} <span className="text-ink-3">vs</span> {fixture.underdog_team}
                    </h3>
                    <p className="mt-1 text-sm text-ink-2">{fixture.league} · {formatEasternDateTime(fixture.kickoff_at)}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-bully">+{fixture.elo_gap.toFixed(0)}</p>
                    <p className="mt-1 font-mono text-ink-1">{formatAmericanFromDecimal(favoriteOdds(fixture))}</p>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <SummaryStat label="Win" value={fmtPct(fixture.favorite_probability)} accent="text-win" />
                  <SummaryStat label="SGP" value={fmtPct(bullyComboScore(fixture))} accent="text-edge" />
                </div>
              </button>
              {openId === fixture.fixture_id && <FixtureDetailPanel fixture={fixture} onManualSaved={onManualSaved} />}
            </article>
          ))}
        </div>
      </div>

      <aside className="space-y-4">
        <div className="card">
          <p className="eyebrow text-bully">Board Read</p>
          <div className="mt-3 space-y-3 text-sm text-ink-1">
            <div className="flex items-center justify-between gap-3">
              <span>Top Favorite</span>
              <span className="font-mono text-bully">{hero.favorite_team}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Best SGP Lens</span>
              <span className="font-mono text-edge">{fmtPct(bullyComboScore(hero))}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Favorite Trend</span>
              <span className={`font-mono ${trendTone(favoriteTrend(hero))}`}>{fmtSigned(favoriteTrend(hero))}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Moneyline</span>
              <span className="font-mono text-ink-0">{formatAmericanFromDecimal(favoriteOdds(hero))}</span>
            </div>
          </div>
        </div>

        <div className="card">
          <p className="eyebrow">Season Tracker</p>
          {trackerSummary ? (
            <div className="mt-3 space-y-3">
              <div className="rounded-[14px] border border-line-1 bg-bg-1/80 p-3">
                <p className="text-sm font-semibold text-ink-0">{trackerSummary.label}</p>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <SummaryStat label="Settled" value={String(trackerSummary.settled_count)} />
                  <SummaryStat label="Win Rate" value={fmtPct(trackerSummary.win_rate)} accent="text-win" />
                  <SummaryStat label="ROI" value={fmtSignedPct(trackerSummary.roi)} accent={trackerSummary.roi >= 0 ? 'text-win' : 'text-lose'} />
                  <SummaryStat label="W-L-P" value={`${trackerSummary.wins}-${trackerSummary.losses}-${trackerSummary.pushes}`} />
                </div>
              </div>
              <div className="rounded-[14px] border border-line-1 bg-bg-1/80 p-3">
                <p className="text-sm font-semibold text-ink-0">Manual Tracking</p>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <SummaryStat label="Settled" value={String(tracker?.manual_group.settled_count ?? 0)} />
                  <SummaryStat label="Win Rate" value={fmtPct(tracker?.manual_group.win_rate)} accent="text-win" />
                  <SummaryStat label="ROI" value={fmtSignedPct(tracker?.manual_group.roi)} accent={(tracker?.manual_group.roi ?? 0) >= 0 ? 'text-win' : 'text-lose'} />
                  <SummaryStat label="Weeks" value={String(tracker?.available_weeks.length ?? 0)} />
                </div>
              </div>
            </div>
          ) : (
            <p className="mt-2 text-sm text-ink-2">Season tracking data is loading in the background.</p>
          )}
        </div>

        <div className="card">
          <p className="eyebrow">League Mix</p>
          <div className="mt-3 space-y-2">
            {leagueCounts.length === 0 && <p className="text-sm text-ink-2">No league split for this window.</p>}
            {leagueCounts.map(([league, count]) => (
              <div key={league} className="flex items-center justify-between gap-3 rounded-[12px] border border-line-1 bg-bg-1/80 px-3 py-2.5 text-sm">
                <span className="truncate text-ink-1">{league}</span>
                <span className="font-mono text-ink-0">{count}</span>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </section>
  )
}
