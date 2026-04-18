import type { ReactNode } from 'react'

import type { FixturePick, SpreadPick, OUPick, MoneylinePick, ModelView } from '../api/types'
import ConfidenceBadge from './ConfidenceBadge'
import ManualPickForm from './ManualPickForm'
import { formatAmerican } from '../lib/odds'
import { modelLabel, modelPresentationForView, modelViewLabel } from '../lib/modelLabels'
import { formatEasternDateTime } from '../lib/time'

interface Props {
  pick: FixturePick
  modelView: ModelView
  onManualSaved?: () => void
}

function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function signedPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(1)}%`
}

function numberOrNegativeInfinity(value: number | null | undefined): number {
  return value == null ? Number.NEGATIVE_INFINITY : value
}

type AngleSummary = {
  key: string
  label: string
  odds: string
  probability: string
  edge: string
}

type AngleRow = {
  key: string
  score: number
  summary: AngleSummary
  node: ReactNode
}

function PickDetails({ tier, edge, kelly, steam }: {
  tier: string
  edge: number | null | undefined
  kelly: number | null | undefined
  steam: boolean
}) {
  return (
    <div className="flex items-center gap-2 text-xs text-gray-400">
      <ConfidenceBadge tier={tier as 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'} />
      <span className="font-mono text-green-400">{signedPct(edge)} edge</span>
      {kelly != null && kelly > 0 && (
        <span className="font-mono text-blue-300">{pct(kelly, 2)} Kelly</span>
      )}
      {steam && (
        <span title="Sharp money already moved the line" className="text-orange-300">
          🔥 steam
        </span>
      )}
    </div>
  )
}

function SpreadRow({ sp, home, away }: { sp: SpreadPick; home: string; away: string }) {
  const name = sp.team_side === 'home' ? home : away
  const sign = sp.goal_line > 0 ? '+' : ''
  const prob = sp.final_probability ?? sp.cover_probability
  const price = formatAmerican(sp.american_odds)
  return (
    <div className="space-y-1">
      {modelLabel(sp.model_name, sp.model_version) && (
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
          {modelLabel(sp.model_name, sp.model_version)}
        </p>
      )}
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-medium">{name} {sign}{sp.goal_line}</span>
        {price && <span className="font-mono text-gray-200">{price}</span>}
        <span className="text-gray-400">{pct(prob, 0)} cover</span>
      </div>
      <PickDetails
        tier={sp.confidence_tier}
        edge={sp.edge_pct ?? sp.ev_score}
        kelly={sp.kelly_fraction}
        steam={sp.steam_downgraded}
      />
    </div>
  )
}

function OURow({ ou }: { ou: OUPick }) {
  const prob = ou.final_probability ?? ou.probability
  const price = formatAmerican(ou.american_odds)
  return (
    <div className="space-y-1">
      {modelLabel(ou.model_name, ou.model_version) && (
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
          {modelLabel(ou.model_name, ou.model_version)}
        </p>
      )}
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-medium capitalize">{ou.direction} {ou.line}</span>
        {price && <span className="font-mono text-gray-200">{price}</span>}
        <span className="text-gray-400">{pct(prob, 0)}</span>
      </div>
      <PickDetails
        tier={ou.confidence_tier}
        edge={ou.edge_pct ?? ou.ev_score}
        kelly={ou.kelly_fraction}
        steam={ou.steam_downgraded}
      />
    </div>
  )
}

function MoneylineRow({ ml, home, away }: { ml: MoneylinePick; home: string; away: string }) {
  const label = ml.outcome === 'home' ? home : ml.outcome === 'away' ? away : 'Draw'
  const prob = ml.final_probability ?? ml.probability
  const price = formatAmerican(ml.american_odds)
  return (
    <div className="space-y-1">
      {modelLabel(ml.model_name, ml.model_version) && (
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
          {modelLabel(ml.model_name, ml.model_version)}
        </p>
      )}
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-xs text-gray-500 uppercase">ML</span>
        {price && <span className="font-mono text-gray-200">{price}</span>}
        <span className="text-gray-400">{pct(prob, 0)}</span>
      </div>
      <PickDetails
        tier={ml.confidence_tier}
        edge={ml.edge_pct ?? ml.ev_score}
        kelly={ml.kelly_fraction}
        steam={ml.steam_downgraded}
      />
    </div>
  )
}

export default function PickCard({ pick, modelView, onManualSaved }: Props) {
  const { home_team, away_team, league, kickoff_at, best_spread, best_ou, best_moneyline, top_ev } = pick
  const hasAnyPick = Boolean(best_moneyline || best_spread || best_ou)
  const presentation = modelPresentationForView(modelView)

  const rows: AngleRow[] = []
  if (best_moneyline) {
    rows.push({
      key: 'moneyline',
      score: numberOrNegativeInfinity(best_moneyline.edge_pct ?? best_moneyline.ev_score),
      summary: {
        key: 'moneyline',
        label: `${best_moneyline.outcome === 'home' ? home_team : best_moneyline.outcome === 'away' ? away_team : 'Draw'} moneyline`,
        odds: formatAmerican(best_moneyline.american_odds) || '—',
        probability: pct(best_moneyline.final_probability ?? best_moneyline.probability, 0),
        edge: signedPct(best_moneyline.edge_pct ?? best_moneyline.ev_score),
      },
      node: <MoneylineRow ml={best_moneyline} home={home_team} away={away_team} />,
    })
  }
  if (best_spread) {
    rows.push({
      key: 'spread',
      score: numberOrNegativeInfinity(best_spread.edge_pct ?? best_spread.ev_score),
      summary: {
        key: 'spread',
        label: `${best_spread.team_side === 'home' ? home_team : away_team} ${best_spread.goal_line > 0 ? '+' : ''}${best_spread.goal_line}`,
        odds: formatAmerican(best_spread.american_odds) || '—',
        probability: pct(best_spread.final_probability ?? best_spread.cover_probability, 0),
        edge: signedPct(best_spread.edge_pct ?? best_spread.ev_score),
      },
      node: <SpreadRow sp={best_spread} home={home_team} away={away_team} />,
    })
  }
  if (best_ou) {
    rows.push({
      key: 'ou',
      score: numberOrNegativeInfinity(best_ou.edge_pct ?? best_ou.ev_score),
      summary: {
        key: 'ou',
        label: `${best_ou.direction} ${best_ou.line}`,
        odds: formatAmerican(best_ou.american_odds) || '—',
        probability: pct(best_ou.final_probability ?? best_ou.probability, 0),
        edge: signedPct(best_ou.edge_pct ?? best_ou.ev_score),
      },
      node: <OURow ou={best_ou} />,
    })
  }

  rows.sort((a, b) => b.score - a.score)
  const primaryAngle = rows[0]?.summary ?? null
  const supportingRows = primaryAngle ? rows.slice(1) : rows
  const additionalAngles = supportingRows.map(row => row.summary)

  return (
    <div className={`rounded-2xl border bg-slate-900/90 p-4 space-y-4 shadow-[0_18px_60px_rgba(2,6,23,0.35)] ${presentation.accentBorder}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] ${presentation.accentBorder} ${presentation.accentBg} ${presentation.accentText}`}>
              {presentation.badge}
            </span>
            <span className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
              {modelViewLabel(modelView)}
            </span>
          </div>
          <p className="font-semibold text-slate-100">
            {home_team} <span className="text-gray-400">vs</span> {away_team}
          </p>
          <p className="text-xs text-slate-500">{league} · {formatEasternDateTime(kickoff_at)}</p>
        </div>
        <div className="space-y-1 text-left sm:text-right">
          {top_ev !== null && (
            <p className="text-sm font-mono text-emerald-300">{signedPct(top_ev)} top edge</p>
          )}
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
            Built for pick review, manual tracking, and later grading
          </p>
        </div>
      </div>

      {primaryAngle && (
        <div className={`rounded-2xl border p-4 ${presentation.accentBorder} ${presentation.accentBg}`}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Primary Angle</p>
              <p className="mt-1 text-lg font-semibold text-slate-100">{primaryAngle.label}</p>
            </div>
            <div className="grid grid-cols-3 gap-3 text-xs text-slate-400 sm:min-w-[260px]">
              <div>
                <p className="uppercase tracking-wide text-slate-500">Odds</p>
                <p className="mt-1 font-mono text-slate-100">{primaryAngle.odds}</p>
              </div>
              <div>
                <p className="uppercase tracking-wide text-slate-500">Prob</p>
                <p className="mt-1 font-mono text-slate-100">{primaryAngle.probability}</p>
              </div>
              <div>
                <p className="uppercase tracking-wide text-slate-500">Edge</p>
                <p className="mt-1 font-mono text-emerald-300">{primaryAngle.edge}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {supportingRows.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
              Additional Angles
            </p>
            {additionalAngles.length > 0 && (
              <div className="hidden items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500 sm:flex">
                {additionalAngles.map(angle => (
                  <span key={angle.key} className="rounded-full border border-slate-700 px-2 py-1">
                    {angle.label}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="space-y-3">
            {supportingRows.map(row => (
              <div key={row.key} className="rounded-xl border border-slate-800 bg-slate-950/65 p-3">
                {row.node}
              </div>
            ))}
          </div>
        </div>
      )}

      {!hasAnyPick && (
        <p className="text-sm text-slate-500">No model pick is available for this fixture yet.</p>
      )}
      <ManualPickForm pick={pick} onSaved={onManualSaved} />
    </div>
  )
}
