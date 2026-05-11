import { type LucideIcon, Inbox } from 'lucide-react'
import { type ReactNode } from 'react'

interface Props {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
}

export default function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-zinc-800 mb-4">
        <Icon className="w-6 h-6 text-zinc-500" />
      </div>
      <p className="text-sm font-medium text-zinc-300 mb-1">{title}</p>
      {description && (
        <p className="text-xs text-zinc-500 max-w-xs mb-4">{description}</p>
      )}
      {action}
    </div>
  )
}
