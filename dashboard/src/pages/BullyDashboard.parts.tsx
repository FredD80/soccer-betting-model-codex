import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

import type { BullyScheduleFixture, FixturePick, MoneylinePick, SeasonTrackerResponse } from '../api/types'
import ManualPickForm from '../components/ManualPickForm'
import { decimalToAmerican, formatAmericanFromDecimal } from '../lib/odds'
import { formatEasternDateTime } from '../lib/time'

export type SortKey = 'composite' | 'combo' | 'elo_gap' | 'favorite_win' | 'two_plus' | 'clean_sheet' | 'kickoff'

export const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'composite', label: 'Composite' },
  { key: 'combo', label: 'SGP' },
  { key: 'elo_gap', label: 'Elo Gap' },
  { key: 'favorite_win', label: 'Win' },
  { key: 'two_plus', label: '2+' },
  { key: 'clean_sheet', label: 'CS' },
  { key: 'kickoff', label: 'Kickoff' },
]

const DESKTOP_GRID =
  'lg:grid-cols-[28px_minmax(0,1.8fr)_60px_58px_58px_56px_58px_64px_72px_58px_70px]'

function fmtPct(value: number | null | undefined, digits = 0): string {
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

export function sortFixtures(fixtures: BullyScheduleFixture[], sortKey: SortKey): BullyScheduleFixture[] {
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
  if (tier === 'ELITE') return 'border-bully/45 bg-bully/18 text-bully'
  if (tier === 'HIGH') return 'border-bully/25 bg-bully/08 text-bully/80'
  return 'border-line-2 bg-bg-3 text-ink-2'
}

export function trackerGroup(data: SeasonTrackerResponse | null) {
  if (!data) return null
  return data.model_groups.find(group => /bully/i.test(`${group.key} ${group.label} ${group.group_type}`)) ?? data.model_groups[0] ?? null
}

function formatFreshAge(value: string | null | undefined): string {
  if (!value) return '—'
  const ageMs = Date.now() - new Date(value).getTime()
  if (!Number.isFinite(ageMs) || ageMs < 0) return '—'
  const m = Math.floor(ageMs / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}

function freshnessToneClass(value: string | null | undefined): string {
  if (!value) return 'text-lose'
  const ageMin = (Date.now() - new Date(value).getTime()) / 60000
  if (!Number.isFinite(ageMin) || ageMin < 0) return 'text-ink-2'
  if (ageMin > 120) return 'text-lose'
  if (ageMin > 30) return 'text-warn'
  return 'text-win'
}

function TrackerRow({ label, roi }: { label: string; roi: number }) {
  return (
    <div className="flex justify-between py-2 border-t border-line-1 first:border-t-0 text-[12px]">
      <span className="text-ink-1 truncate">{label}</span>
      <span className={`font-mono ml-3 shrink-0 ${roi >= 0 ? 'text-win' : 'text-lose'}`}>
        {roi >= 0 ? '+' : ''}{(roi * 100).toFixed(1)}%
      </span>
    </div>
  )
}

function HeroInlineStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="flex flex-col items-start leading-none min-w-0">
      <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-ink-3">{label}</span>
      <span className={`mt-1.5 font-mono text-[18px] font-medium tabular-nums whitespace-nowrap ${accent ?? 'text-ink-0'}`}>
        {value}
      </span>
    </div>
  )
}

function WinCell({ probability }: { probability: number }) {
  return (
    <div className="flex flex-col gap-[3px]">
      <div>{fmtPct(probability, 1)}</div>
      <div className="h-[3px] overflow-hidden rounded-sm bg-bg-3">
        <div className="h-full bg-bully" style={{ width: `${Math.min(100, probability * 100)}%` }} />
      </div>
    </div>
  )
}

function FormTrend({ fixture }: { fixture: BullyScheduleFixture }) {
  const base = Math.round(fixture.favorite_probability * 100)
  const bars = [-10, -4, 8, 14, -1, 6, -16, 12, -6, 10].map(offset =>
    Math.max(18, Math.min(86, base + offset)),
  )

  return (
    <div className="flex h-4 items-end gap-[1.5px]">
      {bars.map((height, index) => (
        <span
          key={index}
          className={`w-1 rounded-[1px] ${height >= 58 ? 'bg-win opacity-100' : 'bg-ink-3 opacity-50'}`}
          style={{ height: `${height}%` }}
        />
      ))}
    </div>
  )
}

function TierBadge({ tier }: { tier: 'ELITE' | 'HIGH' | 'WATCH' }) {
  const styles =
    tier === 'ELITE'
      ? 'bg-bully text-bg-1'
      : tier === 'HIGH'
        ? 'border border-bully/35 bg-bully/16 text-bully'
        : 'border border-line-2 bg-bg-3 text-ink-1'

  return (
    <span className={`inline-block rounded px-2 py-1 font-mono text-[9.5px] font-bold tracking-[0.22em] ${styles}`}>
      {tier}
    </span>
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

function LeftRailSection({ title, children }: { title: string; children: ReactNode }) {
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

export function SideNav({ days, fixtureCount }: { days?: number; fixtureCount: number }) {
  const location = useLocation()
  const pickPath = days === 7 ? '/week' : '/today'
  const currentPath = location.pathname

  return (
    <aside>
      <div className="space-y-4 xl:sticky xl:top-[118px]">
        <div className="card">
          <LeftRailSection title="Views">
            <LeftRailLink to={`${pickPath}?view=bully`} label="Bully Board" count={String(fixtureCount)} active tone="bully" />
            <LeftRailLink to={`${pickPath}?view=best`} label="Best" tone="best" />
            <LeftRailLink to={`${pickPath}?view=main`} label="Main" tone="main" />
            <LeftRailLink to={`${pickPath}?view=parallel`} label="Parallel" tone="parallel" />
          </LeftRailSection>

          <div className="my-4 border-t border-line-1/80" />

          <LeftRailSection title="Windows">
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
      </div>
    </aside>
  )
}

export function HeroStrip({
  fixture,
  isOpen,
  onToggle,
}: {
  fixture: BullyScheduleFixture
  isOpen: boolean
  onToggle: () => void
}) {
  const tier = fixtureTier(fixture)
  const implied = impliedProbability(favoriteOdds(fixture))
  const edge = implied == null ? null : fixture.favorite_probability - implied

  return (
    <div className="rounded-[14px] border border-bully/35 border-l-[3px] border-l-bully bg-[linear-gradient(90deg,rgba(224,181,78,0.16),transparent_60%),rgba(14,21,36,0.92)]">
      <div className="grid gap-4 px-5 py-4 2xl:grid-cols-[minmax(420px,1.2fr)_auto_auto] 2xl:items-center 2xl:gap-6">
        <div className="flex min-w-0 items-center gap-3.5">
          <TierBadge tier={tier} />
          <div className="min-w-0">
            <div className="text-[18px] font-semibold tracking-[-0.01em] leading-tight text-ink-0">
              {fixture.favorite_team} <span className="mx-1.5 font-normal text-ink-3">vs</span> {fixture.underdog_team}
            </div>
            <div className="mt-0.5 font-mono text-[11px] tracking-[0.08em] text-ink-3">
              {fixture.league} · {formatEasternDateTime(fixture.kickoff_at)} · <b className="text-bully">Bully Spot of the Day</b>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-x-5 gap-y-3 text-left sm:grid-cols-6 2xl:text-right">
          <HeroInlineStat label="Elo" value={`+${fixture.elo_gap.toFixed(0)}`} accent="text-bully" />
          <HeroInlineStat label="Win" value={fmtPct(fixture.favorite_probability, 1)} />
          <HeroInlineStat label="Fav 2+" value={fmtPct(fixture.favorite_two_plus_probability, 1)} accent="text-edge" />
          <HeroInlineStat label="SGP" value={fmtPct(bullyComboScore(fixture), 1)} accent="text-bully" />
          <HeroInlineStat label="Odds" value={formatAmericanFromDecimal(favoriteOdds(fixture))} />
          <HeroInlineStat label="Edge" value={fmtSignedPct(edge)} accent={edge != null && edge >= 0 ? 'text-win' : 'text-lose'} />
        </div>

        <button
          type="button"
          onClick={onToggle}
          className="shrink-0 justify-self-start whitespace-nowrap rounded-full border border-bully/45 bg-bully/14 px-4 py-2.5 font-mono text-[10.5px] font-semibold text-bully transition-colors hover:border-bully/65 hover:bg-bully/22 2xl:justify-self-end"
        >
          {isOpen ? 'Close' : 'Track Pick'}
        </button>
      </div>
    </div>
  )
}

function DetailAction({ label }: { label: string }) {
  return (
    <button className="pill justify-center py-2.5" type="button">
      {label}
    </button>
  )
}

function AngleCard({ label, value, primary = false }: { label: string; value: string; primary?: boolean }) {
  return (
    <div className={`rounded-[10px] border p-3 ${primary ? 'border-bully/35 bg-bully/16' : 'border-line-1 bg-bg-2'}`}>
      <div className="text-[9px] uppercase tracking-[0.2em] text-ink-3">{label}</div>
      <div className={`mt-1 font-mono text-[14px] ${primary ? 'text-bully' : 'text-ink-0'}`}>{value}</div>
    </div>
  )
}

function MiniStat({ label, value, tint }: { label: string; value: string; tint?: 'alpha' | 'win' | 'lose' }) {
  const color =
    tint === 'alpha' ? 'text-alpha'
      : tint === 'win' ? 'text-win'
        : tint === 'lose' ? 'text-lose'
          : 'text-ink-0'

  return (
    <div className="rounded-md border border-line-1 bg-bg-2 px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-[0.2em] text-ink-3">{label}</div>
      <div className={`mt-0.5 font-mono text-[14px] ${color}`}>{value}</div>
    </div>
  )
}

export function FixtureDetailPanel({
  fixture,
  onManualSaved,
}: {
  fixture: BullyScheduleFixture
  onManualSaved?: () => void
}) {
  const trend = favoriteTrend(fixture)

  return (
    <div className="border-b border-line-1 border-l-[3px] border-l-bully bg-bg-1 px-5 py-4">
      <div className="mb-3.5 flex items-start justify-between">
        <div>
          <div className="eyebrow mb-1 text-bully">{fixture.league} · {formatEasternDateTime(fixture.kickoff_at)}</div>
          <div className="text-[22px] font-semibold tracking-[-0.01em]">
            {fixture.favorite_team} <span className="font-normal text-ink-3">vs {fixture.underdog_team}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="eyebrow">Composite</div>
          <div className="font-mono text-[28px] font-medium text-bully">
            {(bullyCompositeScore(fixture) * 100).toFixed(1)}
          </div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_1fr_1fr]">
        <div>
          <div className="eyebrow mb-2 text-bully">Why It’s On The Board</div>
          <p className="text-[13px] leading-[1.55] text-ink-1">
            Elo gap <b className="text-bully">+{fixture.elo_gap.toFixed(0)}</b>. {fixture.favorite_team.split(' ')[0]} xG trending{' '}
            <b className={trendTone(trend)}>{fmtSigned(trend)}</b>. Model reads <b className="text-bully">{fmtPct(fixture.favorite_probability, 1)} win</b> with{' '}
            <b className="text-bully">{fmtPct(fixture.favorite_two_plus_probability, 1)} to score 2+</b>. SGP Lens: {fmtPct(bullyComboScore(fixture), 1)}.
          </p>
          <div className="mt-3.5 grid grid-cols-3 gap-2">
            <AngleCard label="Primary · ML" value={formatAmericanFromDecimal(favoriteOdds(fixture))} primary />
            <AngleCard label="Fav 2+" value={fmtPct(fixture.favorite_two_plus_probability, 1)} />
            <AngleCard label="Clean Sheet" value={fmtPct(fixture.favorite_clean_sheet_probability, 1)} />
          </div>
        </div>

        <div>
          <div className="eyebrow mb-2">Model Inputs</div>
          <div className="grid grid-cols-2 gap-2">
            <MiniStat label="Fav xG" value={fmtGoals(fixture.favorite_expected_goals)} tint="alpha" />
            <MiniStat label="Dog xG" value={fmtGoals(fixture.underdog_expected_goals)} />
            <MiniStat label="Win %" value={fmtPct(fixture.favorite_probability, 1)} />
            <MiniStat label="Trend" value={fmtSigned(trend)} tint={trend != null && trend >= 0 ? 'win' : 'lose'} />
          </div>
        </div>

        <div>
          <div className="eyebrow mb-2">Actions</div>
          <div className="flex flex-col gap-2">
            <DetailAction label={`Track pick @ ${formatAmericanFromDecimal(favoriteOdds(fixture))}`} />
            <DetailAction label={`Spread ${fixture.favorite_side === 'home' ? fmtLine(fixture.lines?.spread_home_line) : fmtLine(fixture.lines?.spread_away_line)}`} />
            <DetailAction label={`Total ${fixture.lines?.total_goals_line ?? '—'}`} />
          </div>
          <div className="mt-3">
            <ManualPickForm pick={manualPickFixture(fixture)} onSaved={onManualSaved} />
          </div>
        </div>
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
        className={`hidden w-full lg:grid ${DESKTOP_GRID} cursor-pointer items-center gap-2.5 border-b border-line-1 px-3.5 py-[7px] font-mono text-[12.5px] transition-colors hover:bg-bg-3 ${
          isOpen ? 'bg-bg-3' : ''
        } ${fixture.is_bully_spot ? 'border-l-[3px] border-l-bully bg-gradient-to-r from-bully/16 to-transparent pl-[11px]' : ''}`}
      >
        <div className="text-ink-3">{String(index).padStart(2, '0')}</div>
        <div className="min-w-0 overflow-hidden font-sans">
          <div className="truncate text-[13px] font-semibold">
              {fixture.favorite_team} <span className="font-normal text-ink-3">vs {fixture.underdog_team}</span>
          </div>
          <div className="mt-0.5 text-[9px] uppercase tracking-[0.2em] text-ink-3">
            {fixture.league}
          </div>
        </div>
        <div className="text-[11.5px] text-ink-2">{formatEasternDateTime(fixture.kickoff_at)}</div>
        <div className="text-bully">+{fixture.elo_gap.toFixed(0)}</div>
        <WinCell probability={fixture.favorite_probability} />
        <div className="text-edge">{fmtPct(fixture.favorite_two_plus_probability, 1)}</div>
        <div className="text-bully">{fmtPct(bullyComboScore(fixture), 1)}</div>
        <div className="text-alpha text-[11.5px]">
          {fmtGoals(fixture.favorite_expected_goals)}/{fmtGoals(fixture.underdog_expected_goals)}
        </div>
        <FormTrend fixture={fixture} />
        <div>{formatAmericanFromDecimal(favoriteOdds(fixture))}</div>
        <div className="text-right">
          <TierBadge tier={tier} />
        </div>
      </button>
      {isOpen && (
        <div className="hidden lg:block">
          <FixtureDetailPanel fixture={fixture} onManualSaved={onManualSaved} />
        </div>
      )}
    </>
  )
}

export function FilterRow({
  sortKey,
  onSort,
  days,
  leagueNames,
  leagueTab,
  onLeagueChange,
}: {
  sortKey: SortKey
  onSort: (key: SortKey) => void
  days?: number
  leagueNames: string[]
  leagueTab: string
  onLeagueChange: (league: string) => void
}) {
  return (
    <div className="my-4 flex flex-wrap items-center gap-2">
      <span className="filter-label">Sort</span>
      {SORT_OPTIONS.filter(option => ['composite', 'combo', 'elo_gap', 'two_plus'].includes(option.key)).map(option => (
        <button
          key={option.key}
          type="button"
          onClick={() => onSort(option.key)}
          className={`pill ${sortKey === option.key ? 'pill-bully pill-active' : ''}`}
        >
          {option.key === 'combo' ? 'SGP Lens' : option.key === 'two_plus' ? '2+ Goals' : option.label}
        </button>
      ))}

      <span className="w-3" />
      <span className="filter-label">Window</span>
      <Link to="/today?view=bully" className={`pill ${days === 1 ? 'pill-bully pill-active' : ''}`}>Today</Link>
      <Link to="/week?view=bully" className={`pill ${days === 7 ? 'pill-bully pill-active' : ''}`}>Week</Link>
      <Link to="/schedule" className="pill">Season</Link>

      {leagueNames.length > 1 && (
        <>
          <span className="w-3" />
          <span className="filter-label">League</span>
          <button type="button" onClick={() => onLeagueChange('all')} className={`pill ${leagueTab === 'all' ? 'pill-bully pill-active' : ''}`}>All</button>
          {leagueNames.map(league => (
            <button
              key={league}
              type="button"
              onClick={() => onLeagueChange(league)}
              className={`pill ${leagueTab === league ? 'pill-bully pill-active' : ''}`}
            >
              {league}
            </button>
          ))}
        </>
      )}
    </div>
  )
}

export function BoardTable({
  rows,
  openId,
  onToggle,
  onManualSaved,
}: {
  rows: BullyScheduleFixture[]
  openId: number | null
  onToggle: (id: number) => void
  onManualSaved?: () => void
}) {
  return (
    <>
      <div className="card hidden overflow-hidden p-0 lg:block">
        <div className={`grid ${DESKTOP_GRID} gap-2 border-b border-line-1 px-4 py-2.5 font-mono text-[9.5px] uppercase tracking-[0.18em] text-ink-3`}>
          <span>#</span>
          <span>Fixture</span>
          <span>KO</span>
          <span>Elo</span>
          <span>Win</span>
          <span>2+</span>
          <span>SGP</span>
          <span>xG F/D</span>
          <span>L10</span>
          <span>Odds</span>
          <span className="text-right">Tier</span>
        </div>
        {rows.map((fixture, index) => (
          <BoardRow
            key={fixture.fixture_id}
            fixture={fixture}
            index={index + 2}
            isOpen={openId === fixture.fixture_id}
            onToggle={() => onToggle(fixture.fixture_id)}
            onManualSaved={onManualSaved}
          />
        ))}
      </div>

      <div className="grid gap-4 lg:hidden">
        {rows.map((fixture, index) => (
          <article key={fixture.fixture_id} className="card overflow-hidden p-0">
            <button
              type="button"
              onClick={() => onToggle(fixture.fixture_id)}
              className={`w-full border-l-[3px] px-4 py-4 text-left ${fixture.is_bully_spot ? 'border-l-bully' : 'border-l-line-2'}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="eyebrow">#{String(index + 2).padStart(2, '0')}</span>
                    <span className={`inline-flex rounded-full border px-2 py-0.5 font-mono text-[9px] tracking-[0.2em] ${tierClass(fixtureTier(fixture))}`}>
                      {fixtureTier(fixture)}
                    </span>
                  </div>
                  <h3 className="mt-2 text-base font-semibold text-ink-0">
                    {fixture.favorite_team} <span className="text-ink-3">vs {fixture.underdog_team}</span>
                  </h3>
                  <p className="mt-1 text-xs text-ink-2">{fixture.league} · {formatEasternDateTime(fixture.kickoff_at)}</p>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-4 gap-2">
                <HeroInlineStat label="Elo" value={`+${fixture.elo_gap.toFixed(0)}`} accent="text-bully" />
                <HeroInlineStat label="Win" value={fmtPct(fixture.favorite_probability)} accent="text-win" />
                <HeroInlineStat label="2+" value={fmtPct(fixture.favorite_two_plus_probability)} accent={signalTone(fixture.favorite_two_plus_probability)} />
                <HeroInlineStat label="Odds" value={formatAmericanFromDecimal(favoriteOdds(fixture))} />
              </div>
            </button>
            {openId === fixture.fixture_id && <FixtureDetailPanel fixture={fixture} onManualSaved={onManualSaved} />}
          </article>
        ))}
      </div>
    </>
  )
}

function FreshnessPill({
  status,
}: {
  status?: { latest_prediction_at?: string | null; latest_odds_at?: string | null; latest_result_at?: string | null } | null
}) {
  return (
    <div className="mb-4.5 inline-flex items-center gap-2 rounded-full border border-line-1 bg-bg-1 px-2.5 py-1.5 font-mono text-[10.5px] text-ink-3">
      <span className="h-1.5 w-1.5 rounded-full bg-win shadow-[0_0_8px_theme(colors.win)]" />
      <span className="text-[9.5px] uppercase tracking-[0.14em] text-ink-2">Fresh</span>
      <span className="tabular-nums text-ink-1">
        P <span className={freshnessToneClass(status?.latest_prediction_at)}>{formatFreshAge(status?.latest_prediction_at)}</span>
        {' · '}
        O <span className={freshnessToneClass(status?.latest_odds_at)}>{formatFreshAge(status?.latest_odds_at)}</span>
        {' · '}
        R <span className={freshnessToneClass(status?.latest_result_at)}>{formatFreshAge(status?.latest_result_at)}</span>
      </span>
    </div>
  )
}

export function RightRail({
  status,
  tracker,
  trackerSummary,
  hero,
}: {
  status?: { latest_prediction_at?: string | null; latest_odds_at?: string | null; latest_result_at?: string | null } | null
  tracker: SeasonTrackerResponse | null
  trackerSummary: SeasonTrackerResponse['model_groups'][number] | null
  hero?: BullyScheduleFixture | null
}) {
  const heroBars = hero
    ? [-6, 8, 14, -2, 5, -10, 11, -4, 6, 2].map(offset =>
        Math.max(18, Math.min(90, Math.round(hero.favorite_probability * 100) + offset)),
      )
    : [68, 54, 30, 78, 62, 70, 22, 74, 52, 66]

  return (
    <aside className="card">
      <FreshnessPill status={status} />

      <div>
        <p className="eyebrow mb-2.5">Season Tracker · 2025–26</p>
        {trackerSummary ? (
          <div className="space-y-0">
            <TrackerRow label={trackerSummary.label || 'Bully Model'} roi={trackerSummary.roi} />
            {tracker?.manual_group && (
              <TrackerRow label="My Manual" roi={tracker.manual_group.roi} />
            )}
            {tracker?.model_groups.filter(group => group.key !== trackerSummary.key).slice(0, 2).map(group => (
              <TrackerRow key={group.key} label={group.label} roi={group.roi} />
            ))}
          </div>
        ) : (
          <p className="text-[12px] text-ink-2">Loading…</p>
        )}
      </div>

      <div className="mt-5">
        <p className="eyebrow mb-2.5">Bully Last 10</p>
        <div className="flex h-10 items-end gap-1.5">
          {heroBars.map((height, index) => (
            <span
              key={index}
              className={`flex-1 rounded ${height > 56 ? 'bg-bully' : 'bg-ink-3/50'}`}
              style={{ height: `${height}%` }}
            />
          ))}
        </div>
        <div className="mt-1.5 flex justify-between font-mono text-[11px] text-ink-3">
          <span>{hero ? `Win ${fmtPct(hero.favorite_probability, 1)}` : 'Awaiting feed'}</span>
          <span>{hero ? `2+ ${fmtPct(hero.favorite_two_plus_probability, 1)}` : '—'}</span>
        </div>
      </div>
    </aside>
  )
}
