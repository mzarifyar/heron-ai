import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { CheckCircle2, XCircle, ExternalLink, RefreshCw, Play, TicketIcon, ChevronDown } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { getJiraAuthStatus } from '../api/ops'
import { getPullerStatus, getPullerRuns, runPullerNow } from '../api/pullers'
import { listDbIncidents } from '../api/dashboard'
import PageHeader from '../components/layout/PageHeader'
import Tabs from '../components/ui/Tabs'
import Card, { CardHeader } from '../components/ui/Card'
import Badge, { severityVariant, statusVariant } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import { SkeletonTable } from '../components/ui/Skeleton'
import { Table, Thead, Th, Tbody, Tr, Td, Pagination } from '../components/ui/Table'

function StatusDot({ ok }: { ok: boolean }) {
  return ok
    ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
    : <XCircle className="w-4 h-4 text-zinc-600" />
}

function RunStatusBadge({ status }: { status: string }) {
  const v = status === 'ok' || status === 'success' ? 'success'
    : status === 'error' ? 'critical'
    : 'default'
  return <Badge variant={v}>{status}</Badge>
}

function JiraTab() {
  const { data: jira, isLoading } = useQuery({ queryKey: ['jira-auth-status'], queryFn: getJiraAuthStatus })
  return (
    <div className="space-y-4 mt-4">
      <Card>
        <CardHeader title="Jira Connection" />
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {isLoading ? (
              <span className="w-4 h-4 bg-zinc-700 rounded-full animate-pulse" />
            ) : (
              <StatusDot ok={jira?.configured ?? false} />
            )}
            <span className="text-sm text-zinc-300">
              {jira?.configured ? 'Connected' : 'Not configured'}
            </span>
          </div>
          {jira?.base_url && (
            <div className="flex items-center gap-2 text-xs text-zinc-500">
              <ExternalLink className="w-3 h-3" />
              <span className="font-mono">{jira.base_url}</span>
            </div>
          )}
          {jira?.token_source && (
            <div className="text-xs text-zinc-500">
              Token source: <span className="text-zinc-400">{jira.token_source}</span>
            </div>
          )}
          {!jira?.configured && (
            <p className="text-xs text-zinc-500 mt-2">
              Set <code className="bg-zinc-800 px-1 py-0.5 rounded text-zinc-400">JIRA_BASE_URL</code> and{' '}
              <code className="bg-zinc-800 px-1 py-0.5 rounded text-zinc-400">JIRA_BEARER_TOKEN</code> in your{' '}
              <code className="bg-zinc-800 px-1 py-0.5 rounded text-zinc-400">.env</code> to connect.
            </p>
          )}
        </div>
      </Card>
    </div>
  )
}

function PullerTab() {
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['puller-status'], queryFn: getPullerStatus, refetchInterval: 15_000,
  })
  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ['puller-runs'], queryFn: () => getPullerRuns(20), refetchInterval: 30_000,
  })
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 10
  const runItems = runs?.items ?? []
  const totalPages = Math.max(1, Math.ceil(runItems.length / PAGE_SIZE))
  const pageRuns = runItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const trigger = useMutation({ mutationFn: (src: 'jira' | 'devops_portal') => runPullerNow(src) })

  return (
    <div className="space-y-4 mt-4">
      {/* Scheduler status */}
      <Card>
        <CardHeader title="Scheduler" />
        {statusLoading ? (
          <div className="h-4 w-32 bg-zinc-800 rounded animate-pulse" />
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <StatusDot ok={status?.scheduler?.enabled ?? false} />
              <span className="text-sm text-zinc-300">
                Scheduler {status?.scheduler?.enabled ? 'running' : 'disabled'}
              </span>
            </div>
            {status?.sources && (Array.isArray(status.sources) ? status.sources : Object.values(status.sources)).map((src) => (
              <div key={src.source} className="flex items-center justify-between bg-zinc-800/50 rounded-lg px-3 py-2">
                <div className="flex items-center gap-2">
                  <StatusDot ok={src.enabled} />
                  <span className="text-sm text-zinc-300 font-medium">{src.source}</span>
                </div>
                <div className="flex items-center gap-3">
                  {src.last_run_at && (
                    <span className="text-xs text-zinc-500">
                      {format(parseISO(src.last_run_at), 'HH:mm:ss')}
                    </span>
                  )}
                  {src.last_status && <RunStatusBadge status={src.last_status} />}
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={trigger.isPending}
                    onClick={() => trigger.mutate(src.source as 'jira' | 'devops_portal')}
                  >
                    <Play className="w-3 h-3" />
                    Run now
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Recent runs */}
      <Card padding={false}>
        <div className="px-5 py-4 border-b border-zinc-800">
          <div className="text-sm font-medium text-zinc-200">Recent Runs</div>
        </div>
        {runsLoading ? (
          <SkeletonTable rows={5} />
        ) : !pageRuns.length ? (
          <EmptyState icon={RefreshCw} title="No runs yet" description="Puller runs will appear here." />
        ) : (
          <>
            <Table>
              <Thead>
                <Th>Source</Th>
                <Th>Status</Th>
                <Th>Started</Th>
                <Th>Fetched</Th>
                <Th>Accepted</Th>
              </Thead>
              <Tbody>
                {pageRuns.map((run) => {
                  const s = run.summary as Record<string, number>
                  return (
                    <Tr key={run.run_id}>
                      <Td><code className="text-xs text-violet-400">{run.source}</code></Td>
                      <Td><RunStatusBadge status={run.status} /></Td>
                      <Td className="text-zinc-500 text-xs whitespace-nowrap">
                        {format(parseISO(run.started_at), 'MMM d, HH:mm:ss')}
                      </Td>
                      <Td className="tabular-nums">{s.fetched ?? '—'}</Td>
                      <Td className="tabular-nums">{s.accepted ?? '—'}</Td>
                    </Tr>
                  )
                })}
              </Tbody>
            </Table>
            <Pagination page={page} totalPages={totalPages} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  )
}

function TicketsTab() {
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 25
  const { data, isLoading } = useQuery({
    queryKey: ['db-incidents-tickets', page],
    queryFn: () => listDbIncidents({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }),
  })
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="mt-4">
      <Card padding={false}>
        <div className="px-5 py-4 border-b border-zinc-800">
          <div className="text-sm font-medium text-zinc-200">Ingested Incidents</div>
          {total > 0 && (
            <div className="text-xs text-zinc-500 mt-0.5">{total} total</div>
          )}
        </div>
        {isLoading ? (
          <SkeletonTable rows={8} />
        ) : !data?.items.length ? (
          <EmptyState icon={TicketIcon} title="No incidents ingested" description="Incidents appear here once Heron starts processing signals." />
        ) : (
          <>
            <Table>
              <Thead>
                <Th className="w-[45%]">Title</Th>
                <Th>Service</Th>
                <Th>Severity</Th>
                <Th>Status</Th>
                <Th>Started</Th>
              </Thead>
              <Tbody>
                {data.items.map((inc) => (
                  <Tr key={inc.id}>
                    <Td className="max-w-0">
                      <div className="truncate text-zinc-300">{inc.title}</div>
                    </Td>
                    <Td className="text-zinc-400 text-xs whitespace-nowrap">{inc.service}</Td>
                    <Td><Badge variant={severityVariant(inc.severity)}>{inc.severity}</Badge></Td>
                    <Td><Badge variant={statusVariant(inc.status)} dot>{inc.status}</Badge></Td>
                    <Td className="text-zinc-500 text-xs whitespace-nowrap">
                      {format(parseISO(inc.started_at), 'MMM d, HH:mm')}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
            <Pagination page={page} totalPages={totalPages} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  )
}

export default function Integrations() {
  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Integrations"
        subtitle="Manage connections to Jira, alert sources, and other systems"
      />
      <div className="p-6">
        <Tabs
          tabs={[
            { key: 'jira', label: 'Jira' },
            { key: 'pullers', label: 'Alert Sources' },
            { key: 'tickets', label: 'Ingested Tickets' },
          ]}
        >
          {(tab) => (
            <>
              {tab === 'jira' && <JiraTab />}
              {tab === 'pullers' && <PullerTab />}
              {tab === 'tickets' && <TicketsTab />}
            </>
          )}
        </Tabs>
      </div>
    </div>
  )
}
