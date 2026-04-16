const EASTERN_TIME_ZONE = 'America/New_York'

export function formatEasternDateTime(iso: string): string {
  const value = new Date(iso)
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
