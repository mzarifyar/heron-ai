import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle, Activity, Clock, Zap,
  CircleDot, RefreshCw, ArrowUpRight, CheckCircle2, XCircle,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { formatDistanceToNow, parseISO } from 'date-fns'
import {
  getDashboardSummary, getAlertVolume, getDashboardRecentIncidents,
  getDashboardIntegrations, getDashboardClusters,
} from '../api/dashboard'
import PageHeader from '../components/layout/PageHeader'
import StatCard from '../components/ui/StatCard'
import Card, { CardHeader } from '../components/ui/Card'
import Badge, { severityVariant, statusVariant } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { SkeletonCard, SkeletonTable } from '../components/ui/Skeleton'
import EmptyState from '../components/ui/EmptyState'

const POLL = 30_000

function fmtMttr(s: number | null | undefined): string {
  if (!s) return '—'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function mttrTrend(curr: number | null, prev: number | null): { value: string; positive: boolean } | undefined {
  if (!curr || !prev) return undefined
  const delta = ((curr - prev) / prev) * 100
  const sign = delta <= 0 ? '↓' : '↑'
  return { value: `${sign} ${Math.abs(delta).toFixed(0)}% vs prev week`, positive: delta <= 0 }
}

export default function Dashboard() {
  const navigate = useNavigate()

  const { data: summary, isLoading: sumLoading, refetch } = useQuery({
    queryKey: ['db-summary'], queryFn: getDashboardSummary, refetchInterval: POLL, retry: 1,
  })

  const { data: volume, isLoading: volLoading } = useQuery({
    queryKey: ['db-volume'], queryFn: () => getAlertVolume(14), refetchInterval: POLL,
  })

  const { data: recent, isLoading: recLoading } = useQuery({
    queryKey: ['db-recent'], queryFn: () => getDashboardRecentIncidents(5), refetchInterval: POLL,
  })

  const { data: integrations, isLoading: intLoading } = useQuery({
    queryKey: ['db-integrations'], queryFn: getDashboardIntegrations, refetchInterval: 60_000,
  })

  const { data: clusters, isLoading: clLoading } = useQuery({
    queryKey: ['db-clusters'], queryFn: getDashboardClusters, refetchInterval: 60_000,
  })

  const criticalCount = summary?.active_by_severity?.sev1 ?? 0
  const mttrTrendVal = mttrTrend(summary?.mttr_last_7_days ?? null, summary?.mttr_previous_7_days ?? null)

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Dashboard"
        subtitle="Live system health overview"
        actions={
          <Button variant="ghost" size="sm" onClick={() => refetch()}>
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </Button>
        }
      />

      <div className="p-6 space-y-6">
        {/* Stat row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {sumLoading ? (
            <><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /></>
          ) : (
            <>
              <StatCard
                label="Active Incidents"
                value={summary?.active_incidents ?? '—'}
                icon={AlertTriangle}
                iconColor={criticalCount > 0 ? 'text-rose-400' : 'text-amber-400'}
                trend={criticalCount > 0 ? { value: `${criticalCount} critical`, positive: false } : undefined}
              />
              <StatCard
                label="MTTR (7 days)"
                value={fmtMttr(summary?.mttr_last_7_days)}
                icon={Clock}
                iconColor="text-sky-400"
                trend={mttrTrendVal}
              />
              <StatCard
                label="Auto-Heal Rate"
                value={fmtPct(summary?.auto_heal_rate)}
                icon={Zap}
                iconColor="text-emerald-400"
                trend={summary?.auto_heal_rate ? {
                  value: `${((summary.auto_heal_rate) * 100).toFixed(0)}% last 30 days`,
                  positive: (summary.auto_heal_rate) > 0.7,
                } : undefined}
              />
              <StatCard
                label="Incidents This Week"
                value={summary?.total_incidents_this_week ?? '—'}
                icon={Activity}
                iconColor="text-violet-400"
              />
            </>
          )}
        </div>

        {/* Signal volume + integration health */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-2">
            <CardHeader title="Alert Volume" subtitle="Signals ingested per day, last 14 days" />
            {volLoading ? (
              <div className="h-40 bg-zinc-800 rounded-lg animate-pulse" />
            ) : !volume?.items.length ? (
              <EmptyState icon={Activity} title="No signal data yet" description="Run the seeder to populate demo data." />
            ) : (
              <ResponsiveContainer width="100%" height={160}>
                <AreaChart data={volume.items} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                  <defs>
                    <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#8b5cf6" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="day" tick={{ fill: '#71717a', fontSize: 10 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: '#71717a', fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: '#a1a1aa' }} itemStyle={{ color: '#a78bfa' }}
                  />
                  <Area type="monotone" dataKey="count" stroke="#8b5cf6" strokeWidth={2} fill="url(#volGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </Card>

          {/* Integrations */}
          <Card>
            <CardHeader title="Integrations" subtitle="Connection status" />
            {intLoading ? (
              <div className="space-y-2">
                {[1, 2, 3, 4].map(i => <div key={i} className="h-8 bg-zinc-800 rounded-lg animate-pulse" />)}
              </div>
            ) : (
              <div className="space-y-2">
                {(integrations?.items ?? []).map((intg) => (
                  <div key={intg.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-zinc-800/60 border border-zinc-700/50">
                    {intg.status === 'connected'
                      ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      : <XCircle className="w-3.5 h-3.5 text-zinc-600 shrink-0" />}
                    <span className="text-xs text-zinc-400 flex-1">{intg.name}</span>
                    {intg.last_synced_at && intg.status === 'connected' && (
                      <span className="text-[10px] text-zinc-600">
                        {formatDistanceToNow(parseISO(intg.last_synced_at), { addSuffix: true })}
                      </span>
                    )}
                    {intg.status !== 'connected' && (
                      <span className="text-[10px] text-zinc-600">{intg.status}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Recent incidents */}
        <Card padding={false}>
          <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
            <div>
              <div className="text-sm font-medium text-zinc-200">Recent Incidents</div>
              <div className="text-xs text-zinc-500 mt-0.5">Last 5 incidents across all services</div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => navigate('/incidents')}>
              View all <ArrowUpRight className="w-3 h-3" />
            </Button>
          </div>
          {recLoading ? (
            <SkeletonTable rows={5} />
          ) : !recent?.items.length ? (
            <EmptyState icon={CircleDot} title="No incidents yet" description="Run make seed to populate demo data." />
          ) : (
            <div className="divide-y divide-zinc-800/60">
              {recent.items.map((inc) => (
                <div
                  key={inc.id}
                  onClick={() => navigate(`/incidents/${inc.id}`)}
                  className="flex items-center gap-3 px-5 py-3.5 hover:bg-zinc-800/30 cursor-pointer transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-zinc-200 truncate">{inc.title}</div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      {inc.service} · {inc.region} · {formatDistanceToNow(parseISO(inc.started_at), { addSuffix: true })}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {inc.auto_healed && (
                      <span className="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded-full">
                        auto-healed
                      </span>
                    )}
                    {inc.mttr_seconds && inc.status === 'resolved' && (
                      <span className="text-xs text-zinc-500">{fmtMttr(inc.mttr_seconds)}</span>
                    )}
                    <Badge variant={severityVariant(inc.severity)}>{inc.severity}</Badge>
                    <Badge variant={statusVariant(inc.status)} dot>{inc.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Cluster health */}
        {!clLoading && clusters?.items && clusters.items.length > 0 && (
          <Card>
            <CardHeader title="Cluster Health" subtitle="Kubernetes infrastructure status" />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {clusters.items.map((cl) => (
                <div key={cl.id} className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${
                      cl.status === 'healthy'    ? 'bg-emerald-400' :
                      cl.status === 'degraded'   ? 'bg-amber-400' : 'bg-rose-400'
                    }`} />
                    <span className="text-xs font-medium text-zinc-200 truncate">{cl.cluster_name}</span>
                  </div>
                  <div className="grid grid-cols-3 gap-1 text-center">
                    {[
                      ['Nodes', cl.node_count],
                      ['Pods', cl.pod_count],
                      ['Unhealthy', cl.unhealthy_pods?.length ?? 0],
                    ].map(([label, val]) => (
                      <div key={label as string}>
                        <div className={`text-sm font-semibold tabular-nums ${(label === 'Unhealthy' && Number(val) > 0) ? 'text-rose-400' : 'text-zinc-200'}`}>
                          {val}
                        </div>
                        <div className="text-[10px] text-zinc-600">{label}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
