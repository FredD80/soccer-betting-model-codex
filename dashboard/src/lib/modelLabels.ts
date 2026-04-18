import type { ModelView } from '../api/types'

export type ModelPresentation = {
  badge: string
  accentBorder: string
  accentBg: string
  accentText: string
}

function normalizeModelName(modelName: string): string {
  return modelName.trim().toLowerCase()
}

export function modelViewLabel(modelView: ModelView): string {
  if (modelView === 'bully') return 'Bully-Model'
  if (modelView === 'main') return 'Alpha'
  if (modelView === 'parallel') return 'Market-Edge'
  return 'Combined'
}

export function modelPresentationForView(modelView: ModelView): ModelPresentation {
  if (modelView === 'bully') {
    return {
      badge: 'Bully',
      accentBorder: 'border-amber-500/40',
      accentBg: 'bg-amber-500/10',
      accentText: 'text-amber-200',
    }
  }
  if (modelView === 'main') {
    return {
      badge: 'Alpha',
      accentBorder: 'border-emerald-500/35',
      accentBg: 'bg-emerald-500/10',
      accentText: 'text-emerald-200',
    }
  }
  if (modelView === 'parallel') {
    return {
      badge: 'Market-Edge',
      accentBorder: 'border-sky-500/35',
      accentBg: 'bg-sky-500/10',
      accentText: 'text-sky-200',
    }
  }
  return {
    badge: 'Combined',
    accentBorder: 'border-violet-500/30',
    accentBg: 'bg-violet-500/10',
    accentText: 'text-violet-200',
  }
}

export function displayModelName(modelName: string | null | undefined): string | null {
  if (!modelName) return null

  const normalized = normalizeModelName(modelName)
  if (normalized.includes('elo_bully') || normalized.includes('bully')) return 'Bully-Model'
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

export function modelViewDescription(modelView: ModelView): string {
  if (modelView === 'bully') return 'Elo-first dominance board focused on strong-vs-weak mismatches.'
  if (modelView === 'main') return 'Primary model stack balancing probability, price, and confidence.'
  if (modelView === 'parallel') return 'Market-sensitive alternative view built to disagree when pricing shifts.'
  return 'Combined board showing the strongest available angles across model views.'
}
