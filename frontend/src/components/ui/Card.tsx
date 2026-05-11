import { type ReactNode } from 'react'
import clsx from 'clsx'

interface Props {
  children: ReactNode
  className?: string
  padding?: boolean
}

export default function Card({ children, className, padding = true }: Props) {
  return (
    <div
      className={clsx(
        'bg-zinc-900 border border-zinc-800 rounded-xl',
        padding && 'p-5',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between mb-4">
      <div>
        <div className="text-sm font-medium text-zinc-200">{title}</div>
        {subtitle && <div className="text-xs text-zinc-500 mt-0.5">{subtitle}</div>}
      </div>
      {actions}
    </div>
  )
}
