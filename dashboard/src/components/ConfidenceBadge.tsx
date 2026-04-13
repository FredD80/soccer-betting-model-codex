interface Props {
  tier: 'SKIP' | 'MEDIUM' | 'HIGH' | 'ELITE'
}

const COLORS: Record<Props['tier'], string> = {
  ELITE: 'bg-yellow-500 text-black',
  HIGH:  'bg-green-600 text-white',
  MEDIUM:'bg-blue-600 text-white',
  SKIP:  'bg-gray-600 text-gray-300',
}

export default function ConfidenceBadge({ tier }: Props) {
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded uppercase tracking-wider ${COLORS[tier]}`}>
      {tier}
    </span>
  )
}
