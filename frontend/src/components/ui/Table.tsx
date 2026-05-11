import { type ReactNode } from 'react'
import clsx from 'clsx'

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx('w-full overflow-x-auto', className)}>
      <table className="w-full text-sm">{children}</table>
    </div>
  )
}

export function Thead({ children }: { children: ReactNode }) {
  return (
    <thead className="border-b border-zinc-800">
      <tr>{children}</tr>
    </thead>
  )
}

export function Th({
  children,
  className,
}: {
  children?: ReactNode
  className?: string
}) {
  return (
    <th
      className={clsx(
        'px-4 py-2.5 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide',
        className,
      )}
    >
      {children}
    </th>
  )
}

export function Tbody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-zinc-800/60">{children}</tbody>
}

export function Tr({
  children,
  onClick,
  className,
}: {
  children: ReactNode
  onClick?: () => void
  className?: string
}) {
  return (
    <tr
      onClick={onClick}
      className={clsx(
        'transition-colors',
        onClick && 'cursor-pointer hover:bg-zinc-800/40',
        className,
      )}
    >
      {children}
    </tr>
  )
}

export function Td({
  children,
  className,
}: {
  children?: ReactNode
  className?: string
}) {
  return (
    <td className={clsx('px-4 py-3 text-zinc-300', className)}>{children}</td>
  )
}

interface PaginationProps {
  page: number
  totalPages: number
  onPage: (p: number) => void
}

export function Pagination({ page, totalPages, onPage }: PaginationProps) {
  if (totalPages <= 1) return null
  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-zinc-800 text-xs text-zinc-500">
      <span>
        Page {page} of {totalPages}
      </span>
      <div className="flex gap-1">
        <button
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          className="px-2 py-1 rounded hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          ←
        </button>
        <button
          onClick={() => onPage(page + 1)}
          disabled={page >= totalPages}
          className="px-2 py-1 rounded hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          →
        </button>
      </div>
    </div>
  )
}
