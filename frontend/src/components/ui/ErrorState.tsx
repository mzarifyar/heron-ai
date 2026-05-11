import { AlertTriangle } from 'lucide-react'
import Button from './Button'

interface Props {
  error?: Error | null
  message?: string
  onRetry?: () => void
}

export default function ErrorState({ error, message, onRetry }: Props) {
  const text = message ?? error?.message ?? 'Something went wrong'
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-rose-500/10 border border-rose-500/20 mb-4">
        <AlertTriangle className="w-6 h-6 text-rose-400" />
      </div>
      <p className="text-sm font-medium text-zinc-300 mb-1">Failed to load</p>
      <p className="text-xs text-zinc-500 max-w-xs mb-4">{text}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  )
}
