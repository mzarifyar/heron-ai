import { type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import Skeleton from './Skeleton'

interface Props {
  label: string
  value: string | number | null | undefined
  icon: LucideIcon
  iconColor?: string
  trend?: { value: string; positive?: boolean }
  loading?: boolean
  className?: string
}

export default function StatCard({
  label,
  value,
  icon: Icon,
  iconColor = 'text-violet-400',
  trend,
  loading,
  className,
}: Props) {
  return (
    <div className={clsx('bg-zinc-900 border border-zinc-800 rounded-xl p-5', className)}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-zinc-500 uppercase tracking-wide">{label}</span>
        <div className="w-7 h-7 rounded-lg bg-zinc-800 flex items-center justify-center">
          <Icon className={clsx('w-3.5 h-3.5', iconColor)} />
        </div>
      </div>
      {loading ? (
        <Skeleton className="h-8 w-24" />
      ) : (
        <div className="text-2xl font-semibold text-zinc-100 tabular-nums">
          {value ?? '—'}
        </div>
      )}
      {trend && !loading && (
        <div
          className={clsx(
            'mt-1.5 text-xs font-medium',
            trend.positive ? 'text-emerald-400' : 'text-rose-400',
          )}
        >
          {trend.value}
        </div>
      )}
    </div>
  )
}
