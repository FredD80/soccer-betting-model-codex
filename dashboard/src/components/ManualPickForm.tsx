import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { FixturePick } from '../api/types'

type MarketType = 'moneyline' | 'spread' | 'ou'

interface Props {
  pick: FixturePick
  onSaved?: () => void
}

function formatAmerican(n: number | null | undefined): string {
  if (n == null) return ''
  return n > 0 ? `+${n}` : `${n}`
}

function selectionLabel(pick: FixturePick, marketType: MarketType, selection: string): string {
  if (marketType === 'moneyline') {
    if (selection === 'home') return pick.home_team
    if (selection === 'away') return pick.away_team
    return 'Draw'
  }
  if (marketType === 'spread') {
    return selection === 'home' ? pick.home_team : pick.away_team
  }
  return selection === 'over' ? 'Over' : 'Under'
}

function deriveSuggestion(pick: FixturePick, marketType: MarketType) {
  if (marketType === 'moneyline' && pick.best_moneyline) {
    return {
      selection: pick.best_moneyline.outcome,
      line: null,
      americanOdds: pick.best_moneyline.american_odds ?? null,
    }
  }
  if (marketType === 'spread' && pick.best_spread) {
    return {
      selection: pick.best_spread.team_side,
      line: pick.best_spread.goal_line,
      americanOdds: pick.best_spread.american_odds ?? null,
    }
  }
  if (marketType === 'ou' && pick.best_ou) {
    return {
      selection: pick.best_ou.direction,
      line: pick.best_ou.line,
      americanOdds: pick.best_ou.american_odds ?? null,
    }
  }

  if (marketType === 'moneyline') return { selection: 'home', line: null, americanOdds: null }
  if (marketType === 'spread') return { selection: 'home', line: -0.5, americanOdds: null }
  return { selection: 'over', line: 2.5, americanOdds: null }
}

export default function ManualPickForm({ pick, onSaved }: Props) {
  const initialMarket: MarketType =
    pick.best_moneyline ? 'moneyline' :
    pick.best_spread ? 'spread' :
    'ou'

  const [expanded, setExpanded] = useState(false)
  const [marketType, setMarketType] = useState<MarketType>(initialMarket)
  const [selection, setSelection] = useState('')
  const [line, setLine] = useState<string>('')
  const [americanOdds, setAmericanOdds] = useState<string>('')
  const [stakeUnits, setStakeUnits] = useState('1')
  const [bookmaker, setBookmaker] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  useEffect(() => {
    const suggestion = deriveSuggestion(pick, marketType)
    setSelection(suggestion.selection)
    setLine(suggestion.line == null ? '' : String(suggestion.line))
    setAmericanOdds(suggestion.americanOdds == null ? '' : String(suggestion.americanOdds))
  }, [marketType, pick])

  const choices =
    marketType === 'moneyline'
      ? [
          { value: 'home', label: pick.home_team },
          { value: 'draw', label: 'Draw' },
          { value: 'away', label: pick.away_team },
        ]
      : marketType === 'spread'
        ? [
            { value: 'home', label: pick.home_team },
            { value: 'away', label: pick.away_team },
          ]
        : [
            { value: 'over', label: 'Over' },
            { value: 'under', label: 'Under' },
          ]

  async function submit() {
    try {
      setSaving(true)
      setError(null)
      setSuccess(null)

      await api.createManualPick({
        fixture_id: pick.fixture_id,
        market_type: marketType,
        selection,
        line: marketType === 'moneyline' ? null : Number(line),
        american_odds: americanOdds === '' ? null : Number(americanOdds),
        stake_units: Number(stakeUnits),
        bookmaker: bookmaker || null,
        notes: notes || null,
      })

      setSuccess(`${selectionLabel(pick, marketType, selection)} tracked`)
      setBookmaker('')
      setNotes('')
      setStakeUnits('1')
      onSaved?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save pick')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-[16px] border border-line-1 bg-bg-2/90 p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-ink-0">Track My Pick</p>
          <p className="text-xs text-ink-2">Save your bet on this fixture and settle it automatically.</p>
        </div>
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="pill"
        >
          {expanded ? 'Hide Form' : 'Add Pick'}
        </button>
      </div>

      {expanded && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {(['moneyline', 'spread', 'ou'] as MarketType[]).map(option => (
              <button
                key={option}
                type="button"
                onClick={() => setMarketType(option)}
                className={
                  'pill ' +
                  (marketType === option
                    ? 'pill-bully pill-active'
                    : '')
                }
              >
                {option === 'moneyline' ? 'Moneyline' : option === 'spread' ? 'Spread' : 'Total'}
              </button>
            ))}
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-ink-2">Selection</span>
              <select
                value={selection}
                onChange={e => setSelection(e.target.value)}
                className="w-full rounded-xl border border-line-2 bg-bg-1 px-3 py-2 text-sm text-ink-0 outline-none transition focus:border-bully"
              >
                {choices.map(choice => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            </label>

            {marketType !== 'moneyline' && (
              <label className="space-y-1">
                <span className="text-xs uppercase tracking-wide text-ink-2">Line</span>
                <input
                  value={line}
                  onChange={e => setLine(e.target.value)}
                  className="w-full rounded-xl border border-line-2 bg-bg-1 px-3 py-2 text-sm text-ink-0 outline-none transition focus:border-bully"
                  placeholder="2.5"
                />
              </label>
            )}

            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-ink-2">American Odds</span>
              <input
                value={americanOdds}
                onChange={e => setAmericanOdds(e.target.value)}
                className="w-full rounded-xl border border-line-2 bg-bg-1 px-3 py-2 text-sm text-ink-0 outline-none transition focus:border-bully"
                placeholder={formatAmerican(
                  marketType === 'moneyline'
                    ? pick.best_moneyline?.american_odds
                    : marketType === 'spread'
                      ? pick.best_spread?.american_odds
                      : pick.best_ou?.american_odds,
                ) || '-110'}
              />
            </label>

            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-ink-2">Stake Units</span>
              <input
                value={stakeUnits}
                onChange={e => setStakeUnits(e.target.value)}
                className="w-full rounded-xl border border-line-2 bg-bg-1 px-3 py-2 text-sm text-ink-0 outline-none transition focus:border-bully"
                placeholder="1.0"
              />
            </label>

            <label className="space-y-1">
              <span className="text-xs uppercase tracking-wide text-ink-2">Bookmaker</span>
              <input
                value={bookmaker}
                onChange={e => setBookmaker(e.target.value)}
                className="w-full rounded-xl border border-line-2 bg-bg-1 px-3 py-2 text-sm text-ink-0 outline-none transition focus:border-bully"
                placeholder="draftkings"
              />
            </label>

            <label className="space-y-1 md:col-span-2">
              <span className="text-xs uppercase tracking-wide text-ink-2">Notes</span>
              <input
                value={notes}
                onChange={e => setNotes(e.target.value)}
                className="w-full rounded-xl border border-line-2 bg-bg-1 px-3 py-2 text-sm text-ink-0 outline-none transition focus:border-bully"
                placeholder="Why you liked it"
              />
            </label>
          </div>

          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-ink-2">
              Saving: <span className="font-medium text-ink-1">{selectionLabel(pick, marketType, selection)}</span>
              {marketType !== 'moneyline' && line !== '' ? ` ${line}` : ''}
            </div>
            <button
              type="button"
              onClick={submit}
              disabled={saving || selection === '' || stakeUnits === '' || (marketType !== 'moneyline' && line === '') || americanOdds === ''}
              className="rounded-xl bg-bully px-4 py-2 text-sm font-semibold text-bg-0 transition hover:bg-bully/85 disabled:cursor-not-allowed disabled:bg-bg-3 disabled:text-ink-3"
            >
              {saving ? 'Saving…' : 'Save Pick'}
            </button>
          </div>

          {error && <p className="text-sm text-lose">{error}</p>}
          {success && <p className="text-sm text-win">{success}</p>}
        </div>
      )}
    </div>
  )
}
