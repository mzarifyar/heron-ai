import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  AlertTriangle,
  BrainCircuit,
  Gauge,
  Plug,
  Server,
  Settings,
  ChevronLeft,
  ChevronRight,
  Activity,
  Network,
} from 'lucide-react'
import { useState } from 'react'
import clsx from 'clsx'

const NAV = [
  { to: '/dashboard',      icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/golden-signals', icon: Gauge,           label: 'Golden Signals' },
  { to: '/incidents',      icon: AlertTriangle,   label: 'Incidents' },
  { to: '/intelligence',   icon: BrainCircuit,    label: 'Intelligence' },
  { to: '/integrations',   icon: Plug,            label: 'Integrations' },
  { to: '/infrastructure', icon: Server,          label: 'Infrastructure' },
  { to: '/service-map',    icon: Network,         label: 'Service Map' },
  { to: '/settings',       icon: Settings,        label: 'Settings' },
]

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()

  return (
    <aside
      className={clsx(
        'flex flex-col h-screen bg-zinc-900 border-r border-zinc-800 transition-all duration-200 shrink-0',
        collapsed ? 'w-14' : 'w-56',
      )}
    >
      <div className="flex items-center gap-2.5 px-3 py-4 border-b border-zinc-800 min-h-[56px]">
        <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-violet-600 shrink-0">
          <Activity className="w-4 h-4 text-white" />
        </div>
        {!collapsed && (
          <div className="flex items-baseline gap-[3px] animate-fade-in">
            <span className="font-semibold text-zinc-100 tracking-tight text-sm">Heron</span>
            <span className="font-mono text-[11px] font-bold leading-none tracking-tight">
              <span className="text-violet-500/50">{'{'}</span>
              <span className="bg-gradient-to-r from-violet-400 to-cyan-400 bg-clip-text text-transparent text-[13px]">ai</span>
              <span className="text-violet-500/50">{'}'}</span>
            </span>
          </div>
        )}
      </div>

      <nav className="flex-1 px-1.5 py-3 space-y-0.5 overflow-y-auto">
        {NAV.map(({ to, icon: Icon, label }) => {
          const active =
            to === '/dashboard'
              ? location.pathname === '/dashboard' || location.pathname === '/'
              : location.pathname.startsWith(to)
          return (
            <NavLink
              key={to}
              to={to}
              className={clsx(
                'flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm font-medium transition-colors',
                active ? 'bg-violet-600/20 text-violet-400' : 'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800',
              )}
              title={collapsed ? label : undefined}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && <span className="animate-fade-in">{label}</span>}
            </NavLink>
          )
        })}
      </nav>

      <div className="px-1.5 py-3 border-t border-zinc-800">
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center justify-center w-full h-8 rounded-md text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>
    </aside>
  )
}
