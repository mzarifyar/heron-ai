import { type ButtonHTMLAttributes, type ReactNode } from 'react'
import clsx from 'clsx'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary:   'bg-violet-600 hover:bg-violet-500 text-white border-transparent',
  secondary: 'bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border-zinc-700',
  ghost:     'bg-transparent hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 border-transparent',
  danger:    'bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border-rose-600/30',
}

const SIZES: Record<Size, string> = {
  sm: 'px-2.5 py-1.5 text-xs',
  md: 'px-3.5 py-2 text-sm',
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  children: ReactNode
  loading?: boolean
}

export default function Button({
  variant = 'secondary',
  size = 'md',
  children,
  loading,
  disabled,
  className,
  ...rest
}: Props) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-lg font-medium border transition-colors',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
    >
      {loading && (
        <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
      )}
      {children}
    </button>
  )
}
