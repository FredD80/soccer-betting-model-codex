export function decimalToAmerican(decimal: number | null | undefined): number | null {
  if (decimal == null || decimal <= 1) return null
  if (decimal >= 2) return Math.round((decimal - 1) * 100)
  return Math.round(-100 / (decimal - 1))
}

export function formatAmerican(odds: number | null | undefined): string {
  if (odds == null) return '—'
  return odds > 0 ? `+${odds}` : `${odds}`
}

export function formatAmericanFromDecimal(decimal: number | null | undefined): string {
  return formatAmerican(decimalToAmerican(decimal))
}
