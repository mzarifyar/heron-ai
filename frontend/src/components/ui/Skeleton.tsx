import clsx from 'clsx'

interface Props {
  className?: string
  lines?: number
}

export default function Skeleton({ className, lines }: Props) {
  if (lines && lines > 1) {
    return (
      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={clsx(
              'h-4 bg-zinc-800 rounded animate-pulse',
              i === lines - 1 && 'w-3/4',
              className,
            )}
          />
        ))}
      </div>
    )
  }
  return (
    <div className={clsx('bg-zinc-800 rounded animate-pulse', className)} />
  )
}

export function SkeletonCard() {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-8 w-1/2" />
      <Skeleton className="h-3 w-2/3" />
    </div>
  )
}

export function SkeletonRow() {
  return (
    <div className="flex items-center gap-4 px-4 py-3 border-b border-zinc-800/50">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-3 w-40 flex-1" />
      <Skeleton className="h-5 w-16 rounded-full" />
      <Skeleton className="h-3 w-20" />
    </div>
  )
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonRow key={i} />
      ))}
    </div>
  )
}
