import type { ModelView } from '../api/types'

function normalizeModelName(modelName: string): string {
  return modelName.trim().toLowerCase()
}

export function modelViewLabel(modelView: ModelView): string {
  if (modelView === 'main') return 'Alpha'
  if (modelView === 'parallel') return 'Market-Edge'
  return 'Best'
}

export function displayModelName(modelName: string | null | undefined): string | null {
  if (!modelName) return null

  const normalized = normalizeModelName(modelName)
  if (normalized.includes('parallel')) return 'Market-Edge'
  if (normalized.includes('main')) return 'Alpha'
  if (normalized === 'spread_v1' || normalized === 'ou_v1' || normalized === 'moneyline_v1') {
    return 'Alpha'
  }

  return modelName
}

export function modelLabel(modelName: string | null | undefined, modelVersion: string | null | undefined): string | null {
  const displayName = displayModelName(modelName)
  if (!displayName) return null
  return modelVersion ? `${displayName} · v${modelVersion}` : displayName
}
