import type { FixturePick, SpreadPick, OUPick, MoneylinePick } from '../api/types'
import ConfidenceBadge from './ConfidenceBadge'
import ManualPickForm from './ManualPickForm'
import { formatAmerican } from '../lib/odds'
import { formatEasternDateTime } from '../lib/time'

interface Props {
  pick: FixturePick
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

function modelLabel(modelName: string | null | undefined, modelVersion: string | null | undefined): string | null {
  if (!modelName) return null
  return modelVersion ? `${modelName} · v${modelVersion}` : modelName
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

export default function PickCard({ pick, onManualSaved }: Props) {
  const { home_team, away_team, league, kickoff_at, best_spread, best_ou, best_moneyline, top_ev } = pick
  const hasAnyPick = Boolean(best_moneyline || best_spread || best_ou)

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-900 p-4 space-y-3">
      <div className="flex justify-between items-start">
        <div>
          <p className="font-semibold">
            {home_team} <span className="text-gray-400">vs</span> {away_team}
          </p>
          <p className="text-xs text-gray-500">{league} · {formatEasternDateTime(kickoff_at)}</p>
        </div>
        {top_ev !== null && (
          <span className="text-sm font-mono text-green-400">{signedPct(top_ev)} top edge</span>
        )}
      </div>

      {best_moneyline && <MoneylineRow ml={best_moneyline} home={home_team} away={away_team} />}
      {best_spread && <SpreadRow sp={best_spread} home={home_team} away={away_team} />}
      {best_ou && <OURow ou={best_ou} />}
      {!hasAnyPick && (
        <p className="text-sm text-gray-500">No model pick is available for this fixture yet.</p>
      )}
      <ManualPickForm pick={pick} onSaved={onManualSaved} />
    </div>
  )
}
