import { type ReactNode, useState } from 'react'
import clsx from 'clsx'

interface Tab {
  key: string
  label: string
  count?: number
}

interface Props {
  tabs: Tab[]
  activeKey?: string
  onChange?: (key: string) => void
  children?: (activeKey: string) => ReactNode
}

export default function Tabs({ tabs, activeKey: controlledKey, onChange, children }: Props) {
  const [internalKey, setInternalKey] = useState(tabs[0]?.key ?? '')
  const active = controlledKey ?? internalKey

  function handleClick(key: string) {
    setInternalKey(key)
    onChange?.(key)
  }

  return (
    <div>
      <div className="flex border-b border-zinc-800 gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleClick(tab.key)}
            className={clsx(
              'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
              active === tab.key
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-zinc-500 hover:text-zinc-300',
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span
                className={clsx(
                  'ml-1.5 px-1.5 py-0.5 rounded-full text-xs',
                  active === tab.key ? 'bg-violet-500/20 text-violet-400' : 'bg-zinc-800 text-zinc-500',
                )}
              >
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>
      {children && <div className="mt-0">{children(active)}</div>}
    </div>
  )
}
