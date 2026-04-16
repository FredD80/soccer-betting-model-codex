const EASTERN_TIME_ZONE = 'America/New_York'

function parseApiDateTime(value: string): Date {
  const hasTimeZone = /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  return new Date(hasTimeZone ? value : `${value}Z`)
}

export function formatEasternDateTime(iso: string): string {
  const value = parseApiDateTime(iso)
  return new Intl.DateTimeFormat('en-US', {
    timeZone: EASTERN_TIME_ZONE,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  }).format(value)
}
