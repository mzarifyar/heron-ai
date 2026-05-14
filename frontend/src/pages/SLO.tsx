import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Target, AlertTriangle, CheckCircle, Plus, Trash2, RefreshCw, BookOpen } from 'lucide-react'
import api from '../api/client'
import PageHeader from '../components/layout/PageHeader'
import Card, { CardHeader } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'

// ── Types ─────────────────────────────────────────────────────────────────────

interface SLOBurn {
  slo_id: string; service: string; name: string; metric_name: string
  target: number; window_days: number
  observed_error_rate: number; allowed_error_rate: number
  budget_remaining_pct: number; burn_rate: number
  status: string; alert: boolean; n_samples: number
  budget_seconds_total: number; budget_seconds_remaining: number
}

interface Runbook {
  id: string; title: string; service: string | null
  source: string; url: string | null; tags: string[]
  relevance_score?: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_COLOR = {
  healthy:   { bar: '#10b981', text: 'text-emerald-400', label: 'Healthy' },
  warning:   { bar: '#f59e0b', text: 'text-amber-400',   label: 'Warning' },
  critical:  { bar: '#f97316', text: 'text-orange-400',  label: 'Critical' },
  exhausted: { bar: '#f43f5e', text: 'text-rose-400',    label: 'Exhausted' },
}

function BudgetBar({ pct, status }: { pct: number; status: string }) {
  const cfg = STATUS_COLOR[status as keyof typeof STATUS_COLOR] ?? STATUS_COLOR.healthy
  return (
    <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.max(0, pct)}%`, background: cfg.bar }}
      />
    </div>
  )
}

function fmtSeconds(s: number): string {
  if (s >= 3600) return `${(s / 3600).toFixed(1)}h`
  if (s >= 60)   return `${Math.round(s / 60)}m`
  return `${Math.round(s)}s`
}

// ── SLO card ──────────────────────────────────────────────────────────────────

function SLOCard({ burn, onDelete }: { burn: SLOBurn; onDelete: () => void }) {
  const cfg = STATUS_COLOR[burn.status as keyof typeof STATUS_COLOR] ?? STATUS_COLOR.healthy

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-zinc-200">{burn.name}</div>
          <div className="text-xs text-zinc-500 mt-0.5">{burn.service} · {burn.metric_name} · {burn.window_days}d window</div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-xs font-semibold ${cfg.text}`}>{cfg.label}</span>
          {burn.alert && <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />}
          <button onClick={onDelete} className="text-zinc-700 hover:text-rose-400 transition-colors ml-1">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <BudgetBar pct={burn.budget_remaining_pct} status={burn.status} />

      <div className="grid grid-cols-4 gap-2 text-center">
        <div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Target</div>
          <div className="text-sm font-semibold text-zinc-200 tabular-nums">{(burn.target * 100).toFixed(3)}%</div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Budget left</div>
          <div className={`text-sm font-semibold tabular-nums ${cfg.text}`}>{burn.budget_remaining_pct.toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Burn rate</div>
          <div className={`text-sm font-semibold tabular-nums ${burn.burn_rate > 2 ? 'text-rose-400' : 'text-zinc-200'}`}>
            {burn.burn_rate.toFixed(1)}×
          </div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Time left</div>
          <div className="text-sm font-semibold text-zinc-200 tabular-nums">
            {fmtSeconds(burn.budget_seconds_remaining)}
          </div>
        </div>
      </div>

      {burn.n_samples === 0 && (
        <p className="text-[10px] text-zinc-600">No signal data in window — budget shows 100% consumed as worst-case.</p>
      )}
    </div>
  )
}

// ── Create SLO form ───────────────────────────────────────────────────────────

function CreateSLOForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false)
  const [service, setService]   = useState('')
  const [name, setName]         = useState('')
  const [metric, setMetric]     = useState('error_rate')
  const [target, setTarget]     = useState('99.9')
  const [window, setWindow]     = useState('30')

  const mut = useMutation({
    mutationFn: () => api.post('/api/v1/slo', {
      service, name, metric_name: metric,
      target: parseFloat(target) / 100,
      window_days: parseInt(window),
    }),
    onSuccess: () => { onCreated(); setOpen(false); setService(''); setName('') },
  })

  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        <Plus className="w-3.5 h-3.5" /> Define SLO
      </Button>
    )
  }

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 space-y-3">
      <p className="text-sm font-medium text-zinc-300">New SLO</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Service</label>
          <input value={service} onChange={e => setService(e.target.value)}
            placeholder="payment-processor"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-violet-500" />
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">SLO name</label>
          <input value={name} onChange={e => setName(e.target.value)}
            placeholder="Payment Success Rate"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-violet-500" />
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Metric</label>
          <select value={metric} onChange={e => setMetric(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-300 focus:outline-none">
            <option value="error_rate">error_rate</option>
            <option value="latency_p99_ms">latency_p99_ms</option>
            <option value="cpu_utilization">cpu_utilization</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Target (%)</label>
          <input value={target} onChange={e => setTarget(e.target.value)}
            placeholder="99.9" type="number" step="0.001" min="0" max="100"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-violet-500" />
        </div>
      </div>
      {mut.error && <p className="text-xs text-rose-400">{String(mut.error)}</p>}
      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={() => mut.mutate()} disabled={mut.isPending || !service || !name}>
          {mut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
          Create
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  )
}

// ── Runbook panel ─────────────────────────────────────────────────────────────

function RunbookPanel() {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState<string | null>(null)
  const { data } = useQuery({
    queryKey: ['runbooks'],
    queryFn: () => api.get('/api/v1/runbooks').then(r => r.data as { items: (Runbook & { content?: string })[]; count: number }),
  })
  const indexMut = useMutation({
    mutationFn: () => api.post('/api/v1/runbooks/index'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runbooks'] }),
  })

  const isExternalUrl = (url: string | null) =>
    url?.startsWith('http://') || url?.startsWith('https://')

  return (
    <Card>
      <div className="flex items-start justify-between mb-4">
        <CardHeader title="Runbook Index" subtitle="Markdown files and Confluence pages matched to incidents" />
        <Button variant="ghost" size="sm" onClick={() => indexMut.mutate()} disabled={indexMut.isPending}>
          {indexMut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          Re-index
        </Button>
      </div>

      {!data?.items.length ? (
        <EmptyState
          icon={BookOpen}
          title="No runbooks indexed"
          description="Add .md files to docs/runbooks/ or configure CONFLUENCE_BASE_URL and click Re-index."
        />
      ) : (
        <div className="space-y-2">
          {data.items.map(rb => (
            <div key={rb.id} className="bg-zinc-800/50 rounded-lg overflow-hidden">
              <button
                onClick={() => setExpanded(expanded === rb.id ? null : rb.id)}
                className="w-full flex items-center gap-3 p-3 hover:bg-zinc-800 transition-colors text-left"
              >
                <BookOpen className="w-3.5 h-3.5 text-violet-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-200 truncate">{rb.title}</div>
                  <div className="text-xs text-zinc-500">{rb.source}{rb.service ? ` · ${rb.service}` : ''}</div>
                </div>
                {isExternalUrl(rb.url) ? (
                  <a href={rb.url!} target="_blank" rel="noopener noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="text-xs text-violet-400 hover:text-violet-300 shrink-0">
                    Open →
                  </a>
                ) : (
                  <span className="text-xs text-zinc-600 shrink-0">{expanded === rb.id ? '▲' : '▼'}</span>
                )}
              </button>
              {expanded === rb.id && rb.content && (
                <div className="px-4 pb-4 pt-1 border-t border-zinc-700/50">
                  <pre className="text-xs text-zinc-400 whitespace-pre-wrap font-mono leading-relaxed overflow-auto max-h-80">
                    {rb.content}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {indexMut.data && (
        <p className="text-xs text-emerald-400 mt-3">
          Indexed: {(indexMut.data as { data: { local: number; confluence: number } }).data.local} local + {(indexMut.data as { data: { local: number; confluence: number } }).data.confluence} Confluence
        </p>
      )}
    </Card>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SLOPage() {
  const qc = useQueryClient()

  const { data: burn, isLoading, refetch } = useQuery({
    queryKey: ['slo-burn'],
    queryFn: () => api.get('/api/v1/slo/burn').then(r => r.data as { items: SLOBurn[]; count: number; alerts: number }),
    refetchInterval: 60_000,
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/slo/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['slo-burn'] }),
  })

  const alertCount = burn?.alerts ?? 0
  const items = burn?.items ?? []

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="SLO & Runbooks"
        subtitle="Error budget tracking and incident runbook index"
        actions={
          <div className="flex items-center gap-3">
            {alertCount > 0 && (
              <span className="flex items-center gap-1.5 text-xs text-rose-400">
                <AlertTriangle className="w-3 h-3" />{alertCount} SLO{alertCount !== 1 ? 's' : ''} in alert
              </span>
            )}
            <Button variant="ghost" size="sm" onClick={() => refetch()}>
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </Button>
          </div>
        }
      />

      <div className="p-6 space-y-6">
        {/* Summary row */}
        {!isLoading && items.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {(['healthy', 'warning', 'critical', 'exhausted'] as const).map(status => {
              const cfg = STATUS_COLOR[status]
              const count = items.filter(i => i.status === status).length
              return (
                <div key={status} className="bg-zinc-900 border border-zinc-800 rounded-xl p-3 text-center">
                  <div className="text-2xl font-bold tabular-nums" style={{ color: cfg.bar }}>{count}</div>
                  <div className="text-xs text-zinc-500 mt-0.5">{cfg.label}</div>
                </div>
              )
            })}
          </div>
        )}

        {/* SLO cards */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-zinc-300">Error Budgets</h3>
            <CreateSLOForm onCreated={() => qc.invalidateQueries({ queryKey: ['slo-burn'] })} />
          </div>

          {isLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[1,2,3,4].map(i => <div key={i} className="h-36 bg-zinc-800 rounded-xl animate-pulse" />)}
            </div>
          ) : !items.length ? (
            <EmptyState icon={Target} title="No SLOs defined"
              description='Click "Define SLO" to add your first service level objective.' />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {items.map(b => (
                <SLOCard key={b.slo_id} burn={b} onDelete={() => deleteMut.mutate(b.slo_id)} />
              ))}
            </div>
          )}
        </div>

        {/* Runbook index */}
        <RunbookPanel />
      </div>
    </div>
  )
}
