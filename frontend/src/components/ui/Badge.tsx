import clsx from 'clsx'

type Variant = 'default' | 'critical' | 'high' | 'medium' | 'low' | 'info' |
               'open' | 'resolved' | 'postmortem' | 'success' | 'warning' | 'muted'

const VARIANTS: Record<Variant, string> = {
  default:    'bg-zinc-700/60 text-zinc-300 border-zinc-600',
  muted:      'bg-zinc-800 text-zinc-500 border-zinc-700',
  critical:   'bg-rose-500/20 text-rose-400 border-rose-500/30',
  high:       'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium:     'bg-amber-500/20 text-amber-400 border-amber-500/30',
  low:        'bg-sky-500/20 text-sky-400 border-sky-500/30',
  info:       'bg-zinc-700/60 text-zinc-400 border-zinc-600',
  open:       'bg-amber-500/20 text-amber-400 border-amber-500/30',
  resolved:   'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  postmortem: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  success:    'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  warning:    'bg-amber-500/20 text-amber-400 border-amber-500/30',
}

interface Props {
  children: React.ReactNode
  variant?: Variant
  className?: string
  dot?: boolean
}

export default function Badge({ children, variant = 'default', className, dot }: Props) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
        VARIANTS[variant],
        className,
      )}
    >
      {dot && (
        <span
          className={clsx(
            'w-1.5 h-1.5 rounded-full',
            variant === 'critical' ? 'bg-rose-400' :
            variant === 'high'     ? 'bg-orange-400' :
            variant === 'medium'   ? 'bg-amber-400' :
            variant === 'open'     ? 'bg-amber-400' :
            variant === 'resolved' ? 'bg-emerald-400' : 'bg-zinc-400',
          )}
        />
      )}
      {children}
    </span>
  )
}

export function severityVariant(s: string): Variant {
  const map: Record<string, Variant> = {
    critical: 'critical', high: 'high', medium: 'medium', low: 'low', info: 'info',
  }
  return map[s?.toLowerCase()] ?? 'info'
}

export function statusVariant(s: string): Variant {
  const map: Record<string, Variant> = {
    open: 'open', resolved: 'resolved', postmortem: 'postmortem',
  }
  return map[s?.toLowerCase()] ?? 'default'
}
