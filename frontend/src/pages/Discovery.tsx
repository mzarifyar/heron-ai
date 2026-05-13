import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, RefreshCw, CheckCircle, AlertTriangle, XCircle, HelpCircle, Zap } from 'lucide-react'
import api from '../api/client'
import PageHeader from '../components/layout/PageHeader'
import Card, { CardHeader } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ScanStatus {
  scan_id: string | null
  cloud: string
  status: string   // no_scan | pending | scanning | done | error | activated
  started_at?: string
  finished_at?: string
  resource_count: number
  monitored_count: number
  unmonitored_count: number
  error?: string
}

interface Resource {
  id: string
  name: string
  resource_type: string
  region: string
  compartment: string
  status: string
  monitoring_sources: string[]
  alarm_count: number
  metric_namespaces: string[]
}

interface Report {
  scan_id: string | null
  cloud: string
  scanned_at: string
  resources: Resource[]
  summary: { total: number; by_status: Record<string, number>; by_type: Record<string, number> }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  monitored:   { label: 'Monitored',   color: '#10b981', icon: CheckCircle,    badge: 'success' as const },
  partial:     { label: 'Partial',     color: '#f59e0b', icon: AlertTriangle,  badge: 'warning' as const },
  unmonitored: { label: 'Unmonitored', color: '#f43f5e', icon: XCircle,       badge: 'error'   as const },
  unknown:     { label: 'Unknown',     color: '#52525b', icon: HelpCircle,     badge: 'muted'   as const },
}

const TYPE_LABELS: Record<string, string> = {
  compute: 'Compute', database: 'Database', kubernetes: 'Kubernetes',
  lb: 'Load Balancer', network: 'Network', storage: 'Storage',
}

function StatusIcon({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.unknown
  const Icon = cfg.icon
  return <Icon className="w-3.5 h-3.5 shrink-0" style={{ color: cfg.color }} />
}

// ── Connect form ──────────────────────────────────────────────────────────────

function ConnectForm({ onStarted }: { onStarted: () => void }) {
  const [cloud, setCloud] = useState('oci')
  const [region, setRegion] = useState('')
  const [compartmentId, setCompartmentId] = useState('')
  const [demo, setDemo] = useState(false)

  const mutation = useMutation({
    mutationFn: () => api.post('/api/v1/discovery/connect', {
      cloud, region, compartment_id: compartmentId, demo,
    }),
    onSuccess: onStarted,
  })

  return (
    <Card>
      <CardHeader title="Connect Cloud Account" subtitle="Point Heron at your infrastructure to begin discovery" />
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-zinc-400 mb-1.5 block">Cloud provider</label>
            <select
              value={cloud}
              onChange={e => setCloud(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-violet-500"
            >
              <option value="oci">Oracle Cloud (OCI)</option>
              <option value="aws" disabled>AWS (coming soon)</option>
              <option value="gcp" disabled>GCP (coming soon)</option>
              <option value="azure" disabled>Azure (coming soon)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1.5 block">Region</label>
            <input
              value={region}
              onChange={e => setRegion(e.target.value)}
              placeholder="us-ashburn-1"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-500"
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-zinc-400 mb-1.5 block">Compartment OCID</label>
          <input
            value={compartmentId}
            onChange={e => setCompartmentId(e.target.value)}
            placeholder="ocid1.compartment.oc1..aaaa... (leave blank to use demo data)"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-500 font-mono"
          />
        </div>
        <div className="flex items-center gap-2.5">
          <input
            type="checkbox"
            id="demo-mode"
            checked={demo}
            onChange={e => setDemo(e.target.checked)}
            className="rounded border-zinc-600 bg-zinc-800 text-violet-500"
          />
          <label htmlFor="demo-mode" className="text-sm text-zinc-400 cursor-pointer">
            Use demo data (no credentials required)
          </label>
        </div>
        {mutation.error && (
          <p className="text-xs text-rose-400">{String(mutation.error)}</p>
        )}
        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          variant="primary"
        >
          {mutation.isPending ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
          {mutation.isPending ? 'Starting scan…' : 'Start discovery scan'}
        </Button>
      </div>
    </Card>
  )
}

// ── Coverage map ──────────────────────────────────────────────────────────────

function CoverageMap({ report, scanId }: { report: Report; scanId: string }) {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const activate = useMutation({
    mutationFn: (ids: string[]) => api.post('/api/v1/discovery/activate', {
      scan_id: scanId,
      resource_ids: ids,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['discovery-status'] }),
  })

  const filtered = report.resources.filter(r => {
    if (filter !== 'all' && r.status !== filter) return false
    if (typeFilter !== 'all' && r.resource_type !== typeFilter) return false
    return true
  })

  const toggleAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(filtered.map(r => r.id)))
    }
  }

  const types = Array.from(new Set(report.resources.map(r => r.resource_type))).sort()
  const summary = report.summary.by_status

  return (
    <div className="space-y-4">
      {/* Summary tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
          <button
            key={key}
            onClick={() => setFilter(filter === key ? 'all' : key)}
            className={`p-3 rounded-xl border text-left transition-all ${
              filter === key
                ? 'border-violet-500 bg-violet-500/10'
                : 'border-zinc-800 bg-zinc-900 hover:border-zinc-700'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <cfg.icon className="w-3.5 h-3.5" style={{ color: cfg.color }} />
              <span className="text-xs text-zinc-400">{cfg.label}</span>
            </div>
            <div className="text-2xl font-bold tabular-nums" style={{ color: cfg.color }}>
              {summary[key] ?? 0}
            </div>
          </button>
        ))}
      </div>

      {/* Filters + actions */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-zinc-300 focus:outline-none"
        >
          <option value="all">All types</option>
          {types.map(t => (
            <option key={t} value={t}>{TYPE_LABELS[t] ?? t}</option>
          ))}
        </select>
        <span className="text-xs text-zinc-500">{filtered.length} resources</span>
        <div className="ml-auto flex items-center gap-2">
          {selected.size > 0 && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => activate.mutate(Array.from(selected))}
              disabled={activate.isPending}
            >
              <Zap className="w-3 h-3" />
              Activate {selected.size} selected
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => activate.mutate([])}
            disabled={activate.isPending}
          >
            <CheckCircle className="w-3 h-3" />
            Activate all monitored
          </Button>
        </div>
      </div>

      {activate.data && (
        <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-sm text-emerald-400">
          <CheckCircle className="w-4 h-4 shrink-0" />
          {(activate.data as { data: { message: string } }).data.message}
        </div>
      )}

      {/* Resource table */}
      <Card padding={false}>
        <div className="divide-y divide-zinc-800/60">
          {/* Header */}
          <div className="grid grid-cols-[24px_1fr_110px_130px_160px] gap-3 px-4 py-2.5 text-xs text-zinc-500 uppercase tracking-wider">
            <input
              type="checkbox"
              checked={selected.size === filtered.length && filtered.length > 0}
              onChange={toggleAll}
              className="rounded border-zinc-600 bg-zinc-800 text-violet-500 mt-0.5"
            />
            <span>Resource</span>
            <span>Type</span>
            <span>Status</span>
            <span>Monitoring sources</span>
          </div>

          {filtered.length === 0 ? (
            <div className="px-4 py-8">
              <EmptyState icon={Search} title="No resources match" description="Adjust the filters above." />
            </div>
          ) : (
            filtered.map(r => {
              const cfg = STATUS_CONFIG[r.status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.unknown
              return (
                <div
                  key={r.id}
                  className="grid grid-cols-[24px_1fr_110px_130px_160px] gap-3 px-4 py-3 hover:bg-zinc-800/30 items-center"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(r.id)}
                    onChange={e => {
                      const next = new Set(selected)
                      e.target.checked ? next.add(r.id) : next.delete(r.id)
                      setSelected(next)
                    }}
                    className="rounded border-zinc-600 bg-zinc-800 text-violet-500"
                  />
                  <div className="min-w-0">
                    <div className="text-sm text-zinc-200 truncate font-medium">{r.name}</div>
                    <div className="text-xs text-zinc-500 truncate">{r.region} · {r.compartment.split('..').pop()}</div>
                  </div>
                  <span className="text-xs text-zinc-400">{TYPE_LABELS[r.resource_type] ?? r.resource_type}</span>
                  <div className="flex items-center gap-1.5">
                    <StatusIcon status={r.status} />
                    <span className="text-xs" style={{ color: cfg.color }}>{cfg.label}</span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {r.monitoring_sources.length === 0 ? (
                      <span className="text-xs text-zinc-600">None</span>
                    ) : (
                      r.monitoring_sources.slice(0, 2).map(src => (
                        <span key={src} className="text-[10px] bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded">
                          {src}
                        </span>
                      ))
                    )}
                    {r.monitoring_sources.length > 2 && (
                      <span className="text-[10px] text-zinc-600">+{r.monitoring_sources.length - 2}</span>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </Card>
    </div>
  )
}

// ── Scanning progress ─────────────────────────────────────────────────────────

function ScanProgress({ status }: { status: ScanStatus }) {
  return (
    <Card>
      <div className="flex flex-col items-center py-10 gap-4">
        <RefreshCw className="w-8 h-8 text-violet-400 animate-spin" />
        <div className="text-center">
          <p className="text-zinc-200 font-semibold">Scanning {status.cloud?.toUpperCase()} infrastructure…</p>
          <p className="text-zinc-500 text-sm mt-1">Inventorying resources and checking monitoring coverage</p>
        </div>
      </div>
    </Card>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Discovery() {
  const qc = useQueryClient()

  const { data: status } = useQuery<ScanStatus>({
    queryKey: ['discovery-status'],
    queryFn: () => api.get('/api/v1/discovery/status').then(r => r.data),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s === 'pending' || s === 'scanning' ? 2000 : 15_000
    },
  })

  const { data: report } = useQuery<Report>({
    queryKey: ['discovery-report'],
    queryFn: () => api.get('/api/v1/discovery/report').then(r => r.data),
    enabled: status?.status === 'done' || status?.status === 'activated',
  })

  const isScanning = status?.status === 'pending' || status?.status === 'scanning'
  const hasReport  = status?.status === 'done' || status?.status === 'activated'

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Discovery"
        subtitle="Scan your cloud account to map infrastructure and identify monitoring gaps"
        actions={
          hasReport ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => qc.invalidateQueries({ queryKey: ['discovery-status', 'discovery-report'] })}
            >
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </Button>
          ) : undefined
        }
      />
      <div className="p-6 space-y-6">
        {status?.status === 'error' && (
          <div className="flex items-center gap-3 p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl text-sm text-rose-400">
            <XCircle className="w-4 h-4 shrink-0" />
            <span>Scan failed: {status.error}</span>
          </div>
        )}

        {isScanning && <ScanProgress status={status!} />}

        {!isScanning && !hasReport && (
          <ConnectForm onStarted={() => qc.invalidateQueries({ queryKey: ['discovery-status'] })} />
        )}

        {hasReport && report && report.scan_id && (
          <>
            <div className="flex items-center gap-3 p-4 bg-violet-500/10 border border-violet-500/20 rounded-xl text-sm text-violet-300">
              <CheckCircle className="w-4 h-4 shrink-0 text-violet-400" />
              <span>
                Scanned <strong>{status?.cloud?.toUpperCase()}</strong> — {report.summary.total} resources found.
                {status?.status === 'activated' && ' Monitoring activated.'}
              </span>
              <button
                onClick={() => qc.invalidateQueries({ queryKey: ['discovery-status'] }).then(() =>
                  api.post('/api/v1/discovery/connect', { cloud: status?.cloud, demo: true })
                    .then(() => qc.invalidateQueries({ queryKey: ['discovery-status', 'discovery-report'] }))
                )}
                className="ml-auto text-xs text-violet-400 hover:text-violet-300 underline underline-offset-2"
              >
                Rescan
              </button>
            </div>
            <CoverageMap report={report} scanId={report.scan_id} />
          </>
        )}

        {!isScanning && hasReport && (
          <div className="mt-2">
            <ConnectForm onStarted={() => qc.invalidateQueries({ queryKey: ['discovery-status'] })} />
          </div>
        )}
      </div>
    </div>
  )
}
