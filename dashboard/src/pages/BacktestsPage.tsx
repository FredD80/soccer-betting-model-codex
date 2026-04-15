import { FormEvent, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { BacktestRun } from '../api/types'

const MARKET_OPTIONS = [
  { key: 'spread', label: 'Spread' },
  { key: 'ou', label: 'Totals' },
  { key: 'moneyline', label: 'Moneyline' },
] as const

function todayDate() {
  return new Date().toISOString().slice(0, 10)
}

function defaultFromDate() {
  const d = new Date()
  d.setDate(d.getDate() - 30)
  return d.toISOString().slice(0, 10)
}

export default function BacktestsPage() {
  const [fromDate, setFromDate] = useState(defaultFromDate)
  const [toDate, setToDate] = useState(todayDate)
  const [selectedMarkets, setSelectedMarkets] = useState<Array<'spread' | 'ou' | 'moneyline'>>([
    'spread',
    'ou',
    'moneyline',
  ])
  const [runs, setRuns] = useState<BacktestRun[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [resultMessage, setResultMessage] = useState<string | null>(null)

  useEffect(() => {
    api.backtestRuns()
      .then(setRuns)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function toggleMarket(market: 'spread' | 'ou' | 'moneyline') {
    setSelectedMarkets(current =>
      current.includes(market) ? current.filter(item => item !== market) : [...current, market],
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (selectedMarkets.length === 0) {
      setError('Select at least one market.')
      return
    }
    setRunning(true)
    setError(null)
    setResultMessage(null)
    try {
      const response = await api.runBacktestPicks({
        from_date: fromDate,
        to_date: toDate,
        markets: selectedMarkets,
      })
      setRuns(response)
      setResultMessage(
        response.length === 0
          ? 'No qualifying completed picks found in that window.'
          : `Backtest completed for ${response.length} market/model result${response.length === 1 ? '' : 's'}.`,
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="space-y-6">
      <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-4">
        <h2 className="text-sm font-medium uppercase tracking-[0.2em] text-gray-400">Backtests</h2>
        <p className="mt-2 max-w-xl text-sm text-gray-300">
          Run a historical grade on stored HIGH and ELITE picks without leaving the app. Results are grouped by market and model.
        </p>
        <form className="mt-4 grid gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
          <label className="block text-sm">
            <span className="mb-1 block text-gray-400">From date</span>
            <input
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-gray-100"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-gray-400">To date</span>
            <input
              type="date"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              className="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-gray-100"
            />
          </label>
          <div className="md:col-span-2">
            <span className="mb-2 block text-sm text-gray-400">Markets</span>
            <div className="flex flex-wrap gap-2">
              {MARKET_OPTIONS.map(option => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => toggleMarket(option.key)}
                  className={
                    'rounded-full border px-3 py-1.5 text-sm transition ' +
                    (selectedMarkets.includes(option.key)
                      ? 'border-emerald-500 bg-emerald-500/15 text-emerald-200'
                      : 'border-gray-700 bg-gray-950 text-gray-400 hover:border-gray-500 hover:text-gray-200')
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="md:col-span-2 flex items-center gap-3">
            <button
              type="submit"
              disabled={running}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-gray-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-400"
            >
              {running ? 'Running…' : 'Run Backtest'}
            </button>
            {resultMessage ? <p className="text-sm text-emerald-300">{resultMessage}</p> : null}
          </div>
        </form>
      </div>

      {error ? <p className="text-red-400">Error: {error}</p> : null}
      {loading ? <p className="text-gray-400">Loading backtests…</p> : null}

      {!loading && !error && (
        <div className="overflow-hidden rounded-2xl border border-gray-800 bg-gray-900/70">
          <div className="border-b border-gray-800 px-4 py-3">
            <h3 className="text-sm font-medium uppercase tracking-[0.2em] text-gray-400">Results</h3>
          </div>
          {runs.length === 0 ? (
            <p className="px-4 py-6 text-sm text-gray-500">No backtest runs yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-800 text-sm">
                <thead className="bg-gray-950/60 text-left text-gray-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Market</th>
                    <th className="px-4 py-3 font-medium">Model</th>
                    <th className="px-4 py-3 font-medium">Window</th>
                    <th className="px-4 py-3 font-medium text-right">Total</th>
                    <th className="px-4 py-3 font-medium text-right">Correct</th>
                    <th className="px-4 py-3 font-medium text-right">Accuracy</th>
                    <th className="px-4 py-3 font-medium text-right">ROI</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {runs.map(run => (
                    <tr key={`${run.market}-${run.model_id}-${run.run_at ?? run.date_from}`}>
                      <td className="px-4 py-3 text-gray-200">{run.market}</td>
                      <td className="px-4 py-3 text-gray-200">
                        <div>{run.model_name}</div>
                        <div className="text-xs text-gray-500">{run.model_version}</div>
                      </td>
                      <td className="px-4 py-3 text-gray-300">
                        {run.date_from.slice(0, 10)} to {run.date_to.slice(0, 10)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-200">{run.total}</td>
                      <td className="px-4 py-3 text-right text-gray-200">{run.correct}</td>
                      <td className="px-4 py-3 text-right text-gray-200">{(run.accuracy * 100).toFixed(1)}%</td>
                      <td className="px-4 py-3 text-right text-gray-200">{run.roi.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
