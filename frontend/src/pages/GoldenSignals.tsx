'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, RefreshCw, ChevronRight, AlertTriangle, Zap, TrendingUp, Gauge } from 'lucide-react'
import { formatDistanceToNow, parseISO } from 'date-fns'
import {
  getGoldenSignalsSummary, getServiceSignals, getEdgeMetrics, recomputeBaselines,
  type ServiceSummaryRow, type ServiceGoldenSignals,
} from '../api/goldenSignals'
import PageHeader from '../components/layout/PageHeader'
import Card, { CardHeader } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { SkeletonCard, SkeletonTable } from '../components/ui/Skeleton'
import EmptyState from '../components/ui/EmptyState'
import { Table, Thead, Th, Tbody, Tr, Td } from '../components/ui/Table'

const POLL = 15_000

// ── Helpers ────────────────────────────────────────────────────────────────

function sevColor(sev: string) {
  if (sev === 'critical') return 'text-rose-400'
  if (sev === 'warning')  return 'text-amber-400'
  if (sev === 'ok')       return 'text-emerald-400'
  return 'text-zinc-500'
}

function sevDot(sev: string) {
  if (sev === 'critical') return 'bg-rose-500 animate-pulse'
  if (sev === 'warning')  return 'bg-amber-400'
  if (sev === 'ok')       return 'bg-emerald-400'
  return 'bg-zinc-600'
}

function SeverityBar({ label, value, max, severity, unit = '' }: {
  label: string; value: number; max: number; severity: string; unit?: string
}) {
  const pct = Math.min(100, (value / max) * 100)
  const barColor =
    severity === 'critical' ? 'bg-rose-500' :
    severity === 'warning'  ? 'bg-amber-400' : 'bg-emerald-500'
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-zinc-500">{label}</span>
        <span className={sevColor(severity)}>{value.toFixed(1)}{unit}</span>
      </div>
      <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function SignalCard({ icon: Icon, title, value, unit, severity, subtitle }: {
  icon: React.ElementType; title: string; value: number | string; unit?: string
  severity: string; subtitle?: string
}) {
  return (
    <div className={`bg-zinc-800/60 rounded-xl p-4 border transition-colors ${
      severity === 'critical' ? 'border-rose-500/40' :
      severity === 'warning'  ? 'border-amber-500/40' : 'border-zinc-700/50'
    }`}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-3.5 h-3.5 ${sevColor(severity)}`} />
        <span className="text-xs font-medium text-zinc-400">{title}</span>
      </div>
      <div className={`text-2xl font-black tabular-nums ${sevColor(severity)}`}>
        {typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : value}
        {unit && <span className="text-sm font-normal text-zinc-500 ml-1">{unit}</span>}
      </div>
      {subtitle && <div className="text-xs text-zinc-600 mt-1">{subtitle}</div>}
    </div>
  )
}

// ── Service Detail Panel ───────────────────────────────────────────────────

function ServiceDetail({ service, onClose }: { service: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['golden-signals-service', service],
    queryFn: () => getServiceSignals(service),
    refetchInterval: POLL,
  })

  return (
    <div className="fixed right-0 top-0 h-full w-[420px] bg-zinc-900 border-l border-zinc-800 z-50 overflow-y-auto shadow-2xl animate-fade-in">
      <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
        <div>
          <div className="text-sm font-semibold text-zinc-100">{service}</div>
          <div className="text-xs text-zinc-500 mt-0.5">Four Golden Signals</div>
        </div>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 text-lg leading-none">✕</button>
      </div>

      {isLoading ? (
        <div className="p-5 space-y-4"><SkeletonCard /><SkeletonCard /></div>
      ) : !data ? null : (
        <div className="p-5 space-y-5">
          {/* Latency */}
          <Card>
            <CardHeader title="Latency" subtitle="Request duration" />
            <div className="grid grid-cols-3 gap-3 mb-4">
              {[
                { label: 'p50', val: data.latency.p50_ms },
                { label: 'p95', val: data.latency.p95_ms },
                { label: 'p99', val: data.latency.p99_ms },
              ].map(({ label, val }) => (
                <div key={label} className="text-center bg-zinc-800/60 rounded-lg py-2">
                  <div className="text-xs text-zinc-500 mb-1">{label}</div>
                  <div className={`text-lg font-bold tabular-nums ${sevColor(data.latency.severity)}`}>
                    {val.toFixed(0)}<span className="text-xs font-normal text-zinc-600">ms</span>
                  </div>
                </div>
              ))}
            </div>
            {data.latency.baseline_p99 && (
              <div className="text-xs text-zinc-600">
                Baseline p99: {data.latency.baseline_p99.toFixed(0)}ms
                {' · '}
                <span className={sevColor(data.latency.severity)}>
                  {data.latency.ratio_vs_baseline > 1
                    ? `+${((data.latency.ratio_vs_baseline - 1) * 100).toFixed(0)}% above normal`
                    : 'within normal range'}
                </span>
              </div>
            )}
          </Card>

          {/* Traffic */}
          <Card>
            <CardHeader title="Traffic" subtitle="Request rate" />
            <div className="flex items-end gap-2">
              <span className={`text-3xl font-black tabular-nums ${
                data.traffic.zero_traffic ? 'text-rose-400' : sevColor(data.traffic.severity)
              }`}>
                {data.traffic.rps.toFixed(1)}
              </span>
              <span className="text-zinc-500 text-sm mb-1">req/s</span>
            </div>
            {data.traffic.zero_traffic && (
              <div className="mt-2 text-xs text-rose-400 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                Zero traffic detected — possible circuit breaker or upstream failure
              </div>
            )}
          </Card>

          {/* Errors */}
          <Card>
            <CardHeader title="Errors" subtitle="Failure rate" />
            <div className="flex items-end gap-2">
              <span className={`text-3xl font-black tabular-nums ${sevColor(data.errors.severity)}`}>
                {data.errors.rate_pct.toFixed(2)}
              </span>
              <span className="text-zinc-500 text-sm mb-1">%</span>
            </div>
            {data.errors.severity !== 'ok' && (
              <div className={`mt-2 text-xs ${sevColor(data.errors.severity)}`}>
                {data.errors.severity === 'critical' ? 'Critical error rate — immediate action required' : 'Elevated error rate — monitor closely'}
              </div>
            )}
          </Card>

          {/* Saturation */}
          <Card>
            <CardHeader title="Saturation" subtitle="Resource utilization" />
            <div className="space-y-3">
              <SeverityBar label="CPU" value={data.saturation.cpu_pct} max={100} severity={data.saturation.cpu_severity} unit="%" />
              <SeverityBar label="Memory" value={data.saturation.memory_pct} max={100} severity={data.saturation.memory_severity} unit="%" />
              <SeverityBar label="Connection Pool" value={data.saturation.connection_pool_pct} max={100} severity={data.saturation.pool_severity} unit="%" />
              {data.saturation.connection_pool_pct > 80 && (
                <div className="text-xs text-amber-400 flex items-center gap-1 mt-1">
                  <AlertTriangle className="w-3 h-3" />
                  Connection pool at {data.saturation.connection_pool_pct.toFixed(0)}% — failure imminent above 95%
                </div>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function GoldenSignals() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)

  const { data: summary, isLoading } = useQuery({
    queryKey: ['golden-signals-summary'],
    queryFn: getGoldenSignalsSummary,
    refetchInterval: POLL,
  })

  const { data: edges } = useQuery({
    queryKey: ['golden-signals-edges'],
    queryFn: getEdgeMetrics,
    refetchInterval: POLL,
  })

  const recompute = useMutation({
    mutationFn: recomputeBaselines,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['golden-signals-summary'] }),
  })

  const items = summary?.items ?? []
  const critical = items.filter(s => s.overall_health === 'critical').length
  const warning  = items.filter(s => s.overall_health === 'warning').length
  const healthy  = items.filter(s => s.overall_health === 'ok').length

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Golden Signals"
        subtitle="Latency · Traffic · Errors · Saturation — the four metrics that matter"
        actions={
          <Button variant="ghost" size="sm" loading={recompute.isPending} onClick={() => recompute.mutate()}>
            <RefreshCw className="w-3.5 h-3.5" />
            Recompute baselines
          </Button>
        }
      />

      <div className="p-6 space-y-6">
        {/* Summary strip */}
        {!isLoading && items.length > 0 && (
          <div className="grid grid-cols-3 gap-4">
            <div className="glass rounded-xl p-4 text-center">
              <div className="text-3xl font-black text-rose-400 tabular-nums">{critical}</div>
              <div className="text-xs text-zinc-500 mt-1">Critical</div>
            </div>
            <div className="glass rounded-xl p-4 text-center">
              <div className="text-3xl font-black text-amber-400 tabular-nums">{warning}</div>
              <div className="text-xs text-zinc-500 mt-1">Warning</div>
            </div>
            <div className="glass rounded-xl p-4 text-center">
              <div className="text-3xl font-black text-emerald-400 tabular-nums">{healthy}</div>
              <div className="text-xs text-zinc-500 mt-1">Healthy</div>
            </div>
          </div>
        )}

        {/* Service table */}
        <Card padding={false}>
          <div className="px-5 py-4 border-b border-zinc-800">
            <div className="text-sm font-medium text-zinc-200">All Services</div>
            <div className="text-xs text-zinc-500 mt-0.5">Click any service for the full signal breakdown</div>
          </div>

          {isLoading ? <SkeletonTable rows={6} /> : !items.length ? (
            <EmptyState icon={Activity} title="No signal data yet"
              description="Signal data appears here once the app ingests signals from your services. Enable demo mode or connect a real signal source." />
          ) : (
            <Table>
              <Thead>
                <Th>Service</Th>
                <Th>Health</Th>
                <Th>Latency p99</Th>
                <Th>Errors</Th>
                <Th>RPS</Th>
                <Th>Pool</Th>
                <Th />
              </Thead>
              <Tbody>
                {items.map((row) => (
                  <Tr key={row.service} onClick={() => setSelected(row.service)}
                    className={selected === row.service ? 'bg-violet-500/5' : ''}>
                    <Td>
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full shrink-0 ${sevDot(row.overall_health)}`} />
                        <span className="text-sm font-medium text-zinc-200">{row.service}</span>
                      </div>
                    </Td>
                    <Td>
                      <span className={`text-xs font-semibold ${sevColor(row.overall_health)}`}>
                        {row.overall_health.toUpperCase()}
                      </span>
                    </Td>
                    <Td className={`tabular-nums text-sm ${sevColor(row.latency_severity)}`}>
                      {row.latency_p99_ms > 0 ? `${row.latency_p99_ms.toFixed(0)}ms` : '—'}
                    </Td>
                    <Td className={`tabular-nums text-sm ${sevColor(row.error_severity)}`}>
                      {row.error_rate_pct > 0 ? `${row.error_rate_pct.toFixed(2)}%` : '0%'}
                    </Td>
                    <Td className="tabular-nums text-sm text-zinc-400">
                      {row.rps > 0 ? `${row.rps.toFixed(0)} rps` : '—'}
                    </Td>
                    <Td>
                      {row.pool_pct > 0 ? (
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                row.pool_pct > 90 ? 'bg-rose-500' :
                                row.pool_pct > 80 ? 'bg-amber-400' : 'bg-emerald-500'
                              }`}
                              style={{ width: `${Math.min(100, row.pool_pct)}%` }}
                            />
                          </div>
                          <span className="text-xs text-zinc-500 tabular-nums">{row.pool_pct.toFixed(0)}%</span>
                        </div>
                      ) : <span className="text-zinc-600 text-xs">—</span>}
                    </Td>
                    <Td><ChevronRight className="w-3.5 h-3.5 text-zinc-600" /></Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </Card>

        {/* Edge metrics */}
        {edges && edges.items.length > 0 && (
          <Card padding={false}>
            <div className="px-5 py-4 border-b border-zinc-800">
              <div className="text-sm font-medium text-zinc-200">Service Edge Metrics (RED)</div>
              <div className="text-xs text-zinc-500 mt-0.5">Rate · Errors · Duration per inter-service call</div>
            </div>
            <Table>
              <Thead>
                <Th>Source → Destination</Th>
                <Th>p99</Th>
                <Th>RPS</Th>
                <Th>Error Rate</Th>
                <Th>Health</Th>
              </Thead>
              <Tbody>
                {edges.items.slice(0, 10).map((e, i) => (
                  <Tr key={i}>
                    <Td>
                      <span className="text-xs font-mono">
                        <span className="text-violet-400">{e.source}</span>
                        <span className="text-zinc-600 mx-1.5">→</span>
                        <span className="text-cyan-400">{e.dest}</span>
                      </span>
                    </Td>
                    <Td className="tabular-nums text-sm">{e.p99_ms.toFixed(0)}ms</Td>
                    <Td className="tabular-nums text-sm text-zinc-400">{e.rps.toFixed(0)}</Td>
                    <Td className={`tabular-nums text-sm ${e.error_rate_pct > 1 ? 'text-rose-400' : 'text-zinc-400'}`}>
                      {e.error_rate_pct.toFixed(2)}%
                    </Td>
                    <Td>
                      <Badge variant={e.health === 'ok' ? 'success' : e.health === 'warning' ? 'warning' : 'critical'}>
                        {e.health}
                      </Badge>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Card>
        )}
      </div>

      {/* Detail panel */}
      {selected && <ServiceDetail service={selected} onClose={() => setSelected(null)} />}
      {selected && (
        <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setSelected(null)} />
      )}
    </div>
  )
}
