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
  { key: 'combo', label: 'SGP' },
  { key: 'elo_gap', label: 'Elo Gap' },
  { key: 'favorite_win', label: 'Win' },
  { key: 'two_plus', label: '2+' },
  { key: 'clean_sheet', label: 'CS' },
  { key: 'kickoff', label: 'Kickoff' },
]

// #  Fixture        KO   Elo  Win  2+   Comp  SGP  xG F/D  Odds
const DESKTOP_GRID =
  'lg:grid-cols-[28px_minmax(180px,1.6fr)_64px_52px_52px_50px_54px_54px_72px_64px]'

interface Props {
  label?: string
  days?: number
  refreshKey?: number
  onManualSaved?: () => void
  status?: { latest_prediction_at?: string | null; latest_odds_at?: string | null; latest_result_at?: string | null } | null
}

/* ─── formatters ───────────────────────────────────────────────────────── */

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

/* ─── fixture helpers ──────────────────────────────────────────────────── */

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

function favoritePickLabel(fixture: BullyScheduleFixture): string {
  return fixture.favorite_side === 'home' ? `${fixture.home_team} ML` : `${fixture.away_team} ML`
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

/**
 * Tier tone — bully-first color language.
 *   ELITE → solid bully (gold)
 *   HIGH  → dim bully (gold-adjacent), NOT win-green
 *   WATCH → neutral slate
 */
function tierClass(tier: 'ELITE' | 'HIGH' | 'WATCH'): string {
  if (tier === 'ELITE') return 'border-bully/45 bg-bully/18 text-bully'
  if (tier === 'HIGH') return 'border-bully/25 bg-bully/08 text-bully/80'
  return 'border-line-2 bg-bg-3 text-ink-2'
}

function trackerGroup(data: SeasonTrackerResponse | null) {
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

/* ─── small primitives ─────────────────────────────────────────────────── */

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

function SummaryStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-[14px] border border-line-1 bg-bg-1/80 px-3 py-3">
      <p className="stat-label">{label}</p>
      <p className={`mt-1 font-mono text-lg ${accent ?? 'text-ink-0'}`}>{value}</p>
    </div>
  )
}

/**
 * Inline hero stat — NO card background. Used in the single-row HeroStrip.
 * Label sits above a tabular-nums value.
 */
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

/* ─── left rail ────────────────────────────────────────────────────────── */

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

function LeftRailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="eyebrow">{title}</p>
      <div className="mt-3 space-y-1.5">{children}</div>
    </div>
  )
}

function LeftRailLink({
  to, label, count, active, tone,
}: {
  to: string; label: string; count?: string; active?: boolean; tone?: 'bully' | 'best' | 'main' | 'parallel'
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

function LeftRail({ days, fixtureCount }: { days?: number; fixtureCount: number }) {
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
      </div>
    </aside>
  )
}

/* ─── hero strip — single row, no card clutter ─────────────────────────── */

function HeroStrip({
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
    <div className="overflow-hidden rounded-[16px] border border-bully/35 bg-[linear-gradient(135deg,rgba(224,181,78,0.10),rgba(14,21,36,0.96)_40%,rgba(10,14,24,0.98))] shadow-panel">
      <div className="border-l-[3px] border-l-bully px-4 py-3.5 sm:px-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-5">
          {/* LEFT: tier + teams + meta */}
          <div className="flex min-w-0 items-center gap-3 lg:flex-1">
            <span className={`shrink-0 inline-flex rounded-full border px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-[0.22em] ${tierClass(tier)}`}>
              {tier}
            </span>
            <div className="min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="truncate text-[16px] font-semibold tracking-[-0.01em] text-ink-0 sm:text-[17px]">
                  {fixture.favorite_team} <span className="font-normal text-ink-3">vs {fixture.underdog_team}</span>
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[9.5px] tracking-[0.16em] uppercase text-ink-3">
                <span className="text-bully">Top Bully</span>
                <span className="text-line-2">·</span>
                <span>{fixture.league}</span>
                <span className="text-line-2">·</span>
                <span>{formatEasternDateTime(fixture.kickoff_at)}</span>
              </div>
            </div>
          </div>

          {/* CENTER: inline stats, no card chrome */}
          <div className="flex items-center gap-5 sm:gap-7">
            <HeroInlineStat label="Elo" value={`+${fixture.elo_gap.toFixed(0)}`} accent="text-bully" />
            <HeroInlineStat label="Win" value={fmtPct(fixture.favorite_probability)} accent="text-win" />
            <HeroInlineStat label="2+" value={fmtPct(fixture.favorite_two_plus_probability)} accent={signalTone(fixture.favorite_two_plus_probability)} />
            <HeroInlineStat label="SGP" value={fmtPct(bullyComboScore(fixture))} accent="text-edge" />
            <HeroInlineStat label="Odds" value={formatAmericanFromDecimal(favoriteOdds(fixture))} />
            <HeroInlineStat
              label="Edge"
              value={fmtSignedPct(edge)}
              accent={edge != null && edge >= 0 ? 'text-win' : 'text-lose'}
            />
          </div>

          {/* RIGHT: single CTA */}
          <button
            type="button"
            onClick={onToggle}
            className="shrink-0 inline-flex min-h-[36px] items-center justify-center rounded-full border border-bully/45 bg-bully/14 px-4 py-2 font-mono text-[10.5px] font-semibold uppercase tracking-[0.16em] text-bully transition-colors hover:border-bully/65 hover:bg-bully/22 lg:ml-auto"
          >
            {isOpen ? 'Hide' : 'Details'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─── fixture detail drawer ────────────────────────────────────────────── */

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
            {` ${fmtPct(fixture.favorite_probability, 1)} `}win read, and a {fmtPct(fixture.favorite_two_plus_probability, 1)} chance to score 2+.
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
            <SummaryStat label="Fav 2+" value={fmtPct(fixture.favorite_two_plus_probability, 1)} accent={signalTone(fixture.favorite_two_plus_probability)} />
            <SummaryStat label="Clean Sheet" value={fmtPct(fixture.favorite_clean_sheet_probability, 1)} accent={signalTone(fixture.favorite_clean_sheet_probability)} />
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
                <span>Play</span>
                <span className="font-mono text-ink-0">{favoritePickLabel(fixture)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Composite</span>
                <span className="font-mono text-bully">{fmtPct(bullyCompositeScore(fixture), 1)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>SGP Lens</span>
                <span className="font-mono text-edge">{fmtPct(bullyComboScore(fixture), 1)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Win Probability</span>
                <span className="font-mono text-win">{fmtPct(fixture.favorite_probability, 1)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Clean Sheet</span>
                <span className={`font-mono ${signalTone(fixture.favorite_clean_sheet_probability)}`}>{fmtPct(fixture.favorite_clean_sheet_probability, 1)}</span>
              </div>
            </div>
          </div>
          <ManualPickForm pick={manualPickFixture(fixture)} onSaved={onManualSaved} />
        </div>
      </div>
    </div>
  )
}

/* ─── board row (desktop) ──────────────────────────────────────────────── */

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
        className={`hidden w-full lg:grid ${DESKTOP_GRID} items-center gap-2 border-b border-line-1 px-4 py-2 text-left transition-colors hover:bg-bg-3/60 ${
          isOpen ? 'bg-bg-3/75' : ''
        } ${fixture.is_bully_spot ? 'border-l-[3px] border-l-bully pl-[13px]' : ''}`}
      >
        <div className="font-mono text-[11.5px] text-ink-3 tabular-nums">{String(index).padStart(2, '0')}</div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="truncate text-[13px] font-semibold text-ink-0">
              {fixture.favorite_team} <span className="font-normal text-ink-3">vs {fixture.underdog_team}</span>
            </span>
            <span className={`shrink-0 inline-flex rounded border px-1.5 py-0.5 font-mono text-[8.5px] font-bold uppercase tracking-[0.18em] ${tierClass(tier)}`}>
              {tier}
            </span>
          </div>
          <div className="mt-0.5 font-mono text-[9px] tracking-[0.18em] uppercase text-ink-3 truncate">{fixture.league}</div>
        </div>
        <div className="font-mono text-[11px] text-ink-2 tabular-nums truncate">{formatEasternDateTime(fixture.kickoff_at)}</div>
        <div className="font-mono text-[13px] text-bully tabular-nums">+{fixture.elo_gap.toFixed(0)}</div>
        <div className="font-mono text-[13px] text-win tabular-nums">{fmtPct(fixture.favorite_probability)}</div>
        <div className={`font-mono text-[13px] tabular-nums ${signalTone(fixture.favorite_two_plus_probability)}`}>
          {fmtPct(fixture.favorite_two_plus_probability)}
        </div>
        <div className="font-mono text-[13px] text-bully tabular-nums">{fmtPct(bullyCompositeScore(fixture))}</div>
        <div className="font-mono text-[13px] text-edge tabular-nums">{fmtPct(bullyComboScore(fixture))}</div>
        <div className="font-mono text-[11px] text-ink-2 tabular-nums">
          {fmtGoals(fixture.favorite_expected_goals)}/{fmtGoals(fixture.underdog_expected_goals)}
        </div>
        <div className="font-mono text-[13px] text-ink-0 tabular-nums text-right">{formatAmericanFromDecimal(favoriteOdds(fixture))}</div>
      </button>
      {isOpen && (
        <div className="hidden lg:block">
          <FixtureDetailPanel fixture={fixture} onManualSaved={onManualSaved} />
        </div>
      )}
    </>
  )
}

/* ─── right rail: freshness pill + tracker + league mix ────────────────── */

function FreshnessPill({
  status,
}: {
  status?: { latest_prediction_at?: string | null; latest_odds_at?: string | null; latest_result_at?: string | null } | null
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-line-1 bg-bg-1 px-2.5 py-1.5 font-mono text-[10.5px] text-ink-3">
      <span className="h-1.5 w-1.5 rounded-full bg-win shadow-[0_0_8px_currentColor]" />
      <span className="uppercase tracking-[0.14em] text-[9.5px] text-ink-2">Fresh</span>
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

/* ─── page ─────────────────────────────────────────────────────────────── */

export default function BullyBoardPage({ days, refreshKey = 0, onManualSaved, status }: Props) {
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

  if (loading) return <div className="card text-ink-2">Loading bully model schedule…</div>
  if (error) return <div className="card text-lose">Error: {error}</div>
  if (!hero) return <div className="card text-ink-2">No Elo bully model games are available yet.</div>

  return (
    <section className="grid gap-6 xl:grid-cols-[220px_minmax(0,1fr)_280px]">
      <LeftRail days={days} fixtureCount={visibleFixtures.length} />

      <div className="min-w-0 space-y-4">
        {/* HERO — single row strip */}
        <HeroStrip
          fixture={hero}
          isOpen={openId === hero.fixture_id}
          onToggle={() => setOpenId(openId === hero.fixture_id ? null : hero.fixture_id)}
        />
        {openId === hero.fixture_id && <FixtureDetailPanel fixture={hero} onManualSaved={onManualSaved} />}

        {/* FILTERS — flat single-row strip, no nested cards */}
        <div className="rounded-[14px] border border-line-1 bg-bg-2/72 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="filter-label">Sort</span>
            {SORT_OPTIONS.filter(o => ['composite', 'combo', 'elo_gap', 'two_plus'].includes(o.key)).map(option => (
              <button
                key={option.key}
                type="button"
                onClick={() => setSortKey(option.key)}
                className={`pill ${sortKey === option.key ? 'pill-bully pill-active' : ''}`}
              >
                {option.label}
              </button>
            ))}

            <span className="mx-1 h-4 w-px bg-line-2" />

            <span className="filter-label">Window</span>
            <Link to="/today?view=bully" className={`pill ${days === 1 ? 'pill-bully pill-active' : ''}`}>Today</Link>
            <Link to="/week?view=bully" className={`pill ${days === 7 ? 'pill-bully pill-active' : ''}`}>Week</Link>
            <Link to="/schedule" className="pill">Season</Link>

            {leagueNames.length > 1 && (
              <>
                <span className="mx-1 h-4 w-px bg-line-2" />
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
              </>
            )}
          </div>
        </div>

        {/* TABLE (desktop) */}
        <div className="card hidden overflow-hidden p-0 lg:block">
          <div className={`grid ${DESKTOP_GRID} gap-2 border-b border-line-1 px-4 py-2.5 font-mono text-[9.5px] uppercase tracking-[0.18em] text-ink-3`}>
            <span>#</span>
            <span>Fixture</span>
            <span>KO</span>
            <span>Elo</span>
            <span>Win</span>
            <span>2+</span>
            <span>Comp</span>
            <span>SGP</span>
            <span>xG F/D</span>
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

        {/* CARDS (mobile) — 4 stats, not 2 */}
        <div className="grid gap-4 lg:hidden">
          {boardFixtures.map((fixture, index) => (
            <article key={fixture.fixture_id} className="card overflow-hidden p-0">
              <button
                type="button"
                onClick={() => setOpenId(openId === fixture.fixture_id ? null : fixture.fixture_id)}
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
      </div>

      {/* RIGHT RAIL */}
      <aside className="card space-y-5">
        {/* Freshness — single minimal pill */}
        <div>
          <p className="eyebrow mb-2">Data Freshness</p>
          <FreshnessPill status={status} />
        </div>

        {/* Season Tracker */}
        <div>
          <p className="eyebrow mb-2.5">Season Tracker · 2025–26</p>
          {trackerSummary ? (
            <div className="space-y-0">
              <TrackerRow label={trackerSummary.label || 'Bully Model'} roi={trackerSummary.roi} />
              {tracker?.manual_group && (
                <TrackerRow label="My Manual" roi={tracker.manual_group.roi} />
              )}
              {tracker?.model_groups.filter(g => g.key !== trackerSummary.key).slice(0, 2).map(g => (
                <TrackerRow key={g.key} label={g.label} roi={g.roi} />
              ))}
            </div>
          ) : (
            <p className="text-[12px] text-ink-2">Loading…</p>
          )}
        </div>

        {/* League Mix */}
        {leagueCounts.length > 0 && (
          <div>
            <p className="eyebrow mb-2.5">League Mix</p>
            <div className="space-y-1.5">
              {leagueCounts.map(([league, count]) => (
                <div key={league} className="flex items-center justify-between gap-3 text-[12px]">
                  <span className="truncate text-ink-1">{league}</span>
                  <span className="font-mono text-ink-0">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </section>
  )
}
