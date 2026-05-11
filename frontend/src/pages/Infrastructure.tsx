import { useQuery } from '@tanstack/react-query'
import { Server, RefreshCw, CheckCircle2, XCircle, AlertCircle } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { getDashboardClusters } from '../api/dashboard'
import PageHeader from '../components/layout/PageHeader'
import Tabs from '../components/ui/Tabs'
import Card, { CardHeader } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import { SkeletonTable } from '../components/ui/Skeleton'
import { Table, Thead, Th, Tbody, Tr, Td } from '../components/ui/Table'

function ClusterStatusIcon({ status }: { status: string }) {
  if (status === 'ok' || status === 'ready') return <CheckCircle2 className="w-4 h-4 text-emerald-400" />
  if (status === 'error' || status === 'failed') return <XCircle className="w-4 h-4 text-rose-400" />
  return <AlertCircle className="w-4 h-4 text-amber-400" />
}

function ClusterAccessTab() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['db-clusters'],
    queryFn: getDashboardClusters,
    refetchInterval: 60_000,
  })

  const clusters = data?.items ?? []

  return (
    <div className="space-y-4 mt-4">
      <Card padding={false}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
          <div>
            <div className="text-sm font-medium text-zinc-200">Cluster Inventory</div>
            <div className="text-xs text-zinc-500 mt-0.5">{clusters.length} cluster{clusters.length !== 1 ? 's' : ''} discovered</div>
          </div>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </Button>
        </div>

        {isLoading ? (
          <SkeletonTable rows={5} />
        ) : error ? (
          <ErrorState error={error as Error} onRetry={refetch} />
        ) : !clusters.length ? (
          <EmptyState icon={Server} title="No clusters found" description="Run make seed to populate cluster data." />
        ) : (
          <Table>
            <Thead>
              <Th>Cluster</Th>
              <Th>Region</Th>
              <Th>Env</Th>
              <Th>Status</Th>
              <Th>Nodes</Th>
              <Th>Pods</Th>
              <Th>Unhealthy</Th>
            </Thead>
            <Tbody>
              {clusters.map((c) => (
                <Tr key={c.id}>
                  <Td><code className="text-xs text-violet-400">{c.cluster_name}</code></Td>
                  <Td className="text-zinc-400 text-xs">{c.region}</Td>
                  <Td className="text-zinc-500 text-xs">{c.environment}</Td>
                  <Td>
                    <div className="flex items-center gap-1.5">
                      <ClusterStatusIcon status={c.status} />
                      <span className="text-sm">{c.status}</span>
                    </div>
                  </Td>
                  <Td className="tabular-nums">{c.node_count}</Td>
                  <Td className="tabular-nums">{c.pod_count}</Td>
                  <Td>
                    {(c.unhealthy_pods?.length ?? 0) > 0 ? (
                      <span className="text-rose-400 font-medium tabular-nums">{c.unhealthy_pods!.length}</span>
                    ) : (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      {/* Unhealthy pod detail */}
      {clusters.some(c => (c.unhealthy_pods?.length ?? 0) > 0) && (
        <Card>
          <div className="text-sm font-medium text-zinc-200 mb-3">Unhealthy Pods</div>
          <div className="space-y-2">
            {clusters.flatMap(c =>
              (c.unhealthy_pods as Array<{ pod: string; namespace: string; status: string; restarts: number }> ?? []).map((p) => (
                <div key={p.pod} className="flex items-center gap-3 bg-zinc-800/50 rounded-lg px-3 py-2">
                  <Badge variant="critical">{p.status}</Badge>
                  <code className="text-xs text-zinc-300 flex-1">{p.pod}</code>
                  <span className="text-xs text-zinc-500">{p.namespace}</span>
                  {p.restarts > 0 && <span className="text-xs text-rose-400">{p.restarts} restarts</span>}
                </div>
              ))
            )}
          </div>
        </Card>
      )}
    </div>
  )
}

function HygieneTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['db-clusters'],
    queryFn: getDashboardClusters,
    refetchInterval: 60_000,
  })

  const clusters = data?.items ?? []
  const checkedAt = clusters[0]?.last_checked_at

  return (
    <div className="space-y-4 mt-4">
      <Card>
        <CardHeader
          title="Pod Hygiene Report"
          subtitle={checkedAt ? `Last checked ${format(parseISO(checkedAt), 'MMM d, HH:mm')}` : 'No report yet'}
        />
        {isLoading ? (
          <SkeletonTable rows={3} />
        ) : !clusters.length ? (
          <EmptyState icon={Server} title="No clusters" description="Run make seed to populate cluster data." />
        ) : (
          <Table>
            <Thead>
              <Th>Cluster</Th>
              <Th>Unhealthy Pods</Th>
              <Th>Total Pods</Th>
              <Th>Status</Th>
            </Thead>
            <Tbody>
              {clusters.map((c) => (
                <Tr key={c.id}>
                  <Td><code className="text-xs text-violet-400">{c.cluster_name}</code></Td>
                  <Td>
                    <span className={(c.unhealthy_pods?.length ?? 0) > 0 ? 'text-rose-400 font-medium' : 'text-zinc-500'}>
                      {c.unhealthy_pods?.length ?? 0}
                    </span>
                  </Td>
                  <Td className="text-zinc-400">{c.pod_count}</Td>
                  <Td>
                    <Badge variant={c.status === 'healthy' ? 'success' : 'warning'}>
                      {c.status}
                    </Badge>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      {/* Unhealthy pod detail table */}
      {clusters.some(c => (c.unhealthy_pods?.length ?? 0) > 0) && (
        <Card padding={false}>
          <div className="px-5 py-4 border-b border-zinc-800">
            <div className="text-sm font-medium text-zinc-200">Unhealthy Pods</div>
            <div className="text-xs text-zinc-500 mt-0.5">
              {clusters.reduce((n, c) => n + (c.unhealthy_pods?.length ?? 0), 0)} pods requiring attention
            </div>
          </div>
          <Table>
            <Thead>
              <Th>Pod</Th>
              <Th>Namespace</Th>
              <Th>Cluster</Th>
              <Th>Status</Th>
              <Th>Restarts</Th>
              <Th>Age</Th>
              <Th>CPU</Th>
              <Th>Memory</Th>
            </Thead>
            <Tbody>
              {clusters.flatMap(c =>
                (c.unhealthy_pods as Array<{
                  pod: string; namespace: string; status: string
                  restarts: number; node?: string; age?: string; cpu?: string; memory?: string
                }> ?? []).map(p => (
                  <Tr key={`${c.cluster_name}/${p.pod}`}>
                    <Td>
                      <code className="text-xs text-violet-400">{p.pod}</code>
                      {p.node && <div className="text-[10px] text-zinc-600 mt-0.5 font-mono">{p.node.split('.')[0]}</div>}
                    </Td>
                    <Td className="text-zinc-400 text-xs">{p.namespace}</Td>
                    <Td className="text-zinc-500 text-xs whitespace-nowrap">{c.cluster_name}</Td>
                    <Td>
                      <Badge variant={
                        p.status === 'CrashLoopBackOff' ? 'critical' :
                        p.status === 'OOMKilled'        ? 'critical' :
                        p.status === 'ImagePullBackOff' ? 'high' :
                        p.status === 'Evicted'          ? 'high' :
                        'warning'
                      }>{p.status}</Badge>
                    </Td>
                    <Td className={`tabular-nums font-medium ${p.restarts > 5 ? 'text-rose-400' : p.restarts > 0 ? 'text-amber-400' : 'text-zinc-500'}`}>
                      {p.restarts}
                    </Td>
                    <Td className="text-zinc-500 text-xs">{p.age ?? '—'}</Td>
                    <Td className="text-zinc-400 text-xs font-mono">{p.cpu ?? '—'}</Td>
                    <Td className="text-zinc-400 text-xs font-mono">{p.memory ?? '—'}</Td>
                  </Tr>
                ))
              )}
            </Tbody>
          </Table>
        </Card>
      )}
    </div>
  )
}

export default function Infrastructure() {
  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Infrastructure"
        subtitle="Kubernetes cluster inventory, connectivity validation, and pod hygiene"
      />
      <div className="p-6">
        <Tabs
          tabs={[
            { key: 'clusters', label: 'Clusters' },
            { key: 'hygiene', label: 'Pod Hygiene' },
          ]}
        >
          {(tab) => (
            <>
              {tab === 'clusters' && <ClusterAccessTab />}
              {tab === 'hygiene' && <HygieneTab />}
            </>
          )}
        </Tabs>
      </div>
    </div>
  )
}
