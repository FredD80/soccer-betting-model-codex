import { useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import type { DashboardStatus } from '../api/types'

const STATUS_POLL_MS = 15000

function statusSignature(status: DashboardStatus): string {
  return [
    status.latest_prediction_at ?? '',
    status.latest_odds_at ?? '',
    status.latest_result_at ?? '',
    status.latest_manual_pick_at ?? '',
  ].join('|')
}

export function useDashboardAutoRefresh() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [status, setStatus] = useState<DashboardStatus | null>(null)
  const signatureRef = useRef<string | null>(null)

  useEffect(() => {
    let mounted = true

    async function pollStatus() {
      try {
        const next = await api.dashboardStatus()
        if (!mounted) return

        const nextSignature = statusSignature(next)
        if (signatureRef.current === null) {
          signatureRef.current = nextSignature
          setStatus(next)
          return
        }

        if (nextSignature !== signatureRef.current) {
          signatureRef.current = nextSignature
          setStatus(next)
          setRefreshKey(current => current + 1)
          return
        }

        setStatus(next)
      } catch {
        // Keep the current page state if the lightweight status probe fails.
      }
    }

    void pollStatus()
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void pollStatus()
      }
    }, STATUS_POLL_MS)

    return () => {
      mounted = false
      window.clearInterval(intervalId)
    }
  }, [])

  return { refreshKey, status }
}
