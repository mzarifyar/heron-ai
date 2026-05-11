import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Search, Filter, Sparkles } from 'lucide-react'
import { formatDistanceToNow, parseISO, differenceInSeconds } from 'date-fns'
import { listDbIncidents, type DbIncident } from '../api/dashboard'
import api from '../api/client'
import PageHeader from '../components/layout/PageHeader'
import Badge, { severityVariant, statusVariant } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import { SkeletonTable } from '../components/ui/Skeleton'
import { Table, Thead, Th, Tbody, Tr, Td, Pagination } from '../components/ui/Table'

// ── Mitigate modal ─────────────────────────────────────────────────────────
function MitigateResult({ result, onClose }: {
  result: {
    ok: boolean; reasoning?: string; confidence?: number
    escalate_immediately?: boolean; steps?: Array<{action: string; rationale: string}>
    incident_title?: string; error?: string
  }
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-zinc-900 border border-zinc-700 rounded-2xl p-6 max-w-xl w-full max-h-[80vh] overflow-y-auto shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-violet-400" />
            <span className="text-sm font-semibold text-zinc-100">Heron AI Analysis</span>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 text-lg leading-none">✕</button>
        </div>

        {!result.ok ? (
          <p className="text-sm text-rose-400">{result.error ?? 'Analysis failed'}</p>
        ) : (
          <div className="space-y-4">
            {result.incident_title && (
              <p className="text-xs text-zinc-500 truncate">{result.incident_title}</p>
            )}

            {/* Confidence */}
            <div className="flex items-center gap-3">
              <span className={`text-2xl font-black tabular-nums ${
                (result.confidence ?? 0) >= 0.8 ? 'text-emerald-400' :
                (result.confidence ?? 0) >= 0.6 ? 'text-amber-400' : 'text-rose-400'
              }`}>
                {((result.confidence ?? 0) * 100).toFixed(0)}%
              </span>
              <span className="text-xs text-zinc-500">confidence</span>
              {result.escalate_immediately && (
                <Badge variant="warning">escalation recommended</Badge>
              )}
            </div>

            {/* Reasoning */}
            {result.reasoning && (
              <div className="border-l-2 border-violet-500/50 pl-3">
                <p className="text-sm text-zinc-300 leading-relaxed">{result.reasoning}</p>
              </div>
            )}

            {/* Steps */}
            {result.steps && result.steps.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide">Recommended Actions</div>
                {result.steps.map((s, i) => (
                  <div key={i} className="bg-zinc-800/60 rounded-lg px-3 py-2">
                    <code className="text-xs text-violet-400">{s.action}</code>
                    <p className="text-xs text-zinc-400 mt-0.5">{s.rationale}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

const PAGE_SIZE = 25

function fmtDuration(start: string, end: string): string {
  const secs = differenceInSeconds(parseISO(end), parseISO(start))
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.round(secs / 60)}m`
  return `${(secs / 3600).toFixed(1)}h`
}

export default function Incidents() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [filterSev, setFilterSev] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [page, setPage] = useState(1)
  const [mitigating, setMitigating] = useState<string | null>(null)
  const [mitigateResult, setMitigateResult] = useState<Record<string, unknown> | null>(null)

  const mitigate = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/dashboard/incidents/${id}/mitigate`).then(r => r.data),
    onSuccess: (data) => setMitigateResult(data),
    onSettled: () => setMitigating(null),
  })

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['db-incidents', { limit: 200 }],
    queryFn: () => listDbIncidents({ limit: 200 }),
    refetchInterval: 30_000,
  })

  const filtered = (data?.items ?? [] as DbIncident[]).filter((inc) => {
    const q = search.toLowerCase()
    const matchSearch =
      !q ||
      inc.title.toLowerCase().includes(q) ||
      inc.service.toLowerCase().includes(q) ||
      inc.id.toLowerCase().includes(q)
    const matchSev = !filterSev || inc.severity === filterSev
    const matchStatus = !filterStatus || inc.status === filterStatus
    return matchSearch && matchSev && matchStatus
  })

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  function handleFilterChange() {
    setPage(1)
  }

  return (
    <>
    <div className="animate-fade-in">
      <PageHeader
        title="Incidents"
        subtitle="Chronicle — every incident, every decision, every outcome"
        actions={
          <Button variant="ghost" size="sm" onClick={() => refetch()}>
            Refresh
          </Button>
        }
      />

      {/* Filters */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-zinc-800">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500" />
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value); handleFilterChange() }}
            placeholder="Search incidents…"
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-zinc-800 border border-zinc-700 rounded-lg text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:border-violet-500"
          />
        </div>

        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Filter className="w-3 h-3" />
        </div>

        <select
          value={filterSev}
          onChange={(e) => { setFilterSev(e.target.value); handleFilterChange() }}
          className="text-xs bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-300 focus:outline-none focus:border-violet-500"
        >
          <option value="">All severities</option>
          {['sev1', 'sev2', 'sev3', 'sev4'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          value={filterStatus}
          onChange={(e) => { setFilterStatus(e.target.value); handleFilterChange() }}
          className="text-xs bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-300 focus:outline-none focus:border-violet-500"
        >
          <option value="">All statuses</option>
          {['open', 'resolved', 'postmortem'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <span className="text-xs text-zinc-500 ml-auto">
          {filtered.length} incident{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {isLoading ? (
        <SkeletonTable rows={8} />
      ) : error ? (
        <ErrorState error={error as Error} onRetry={refetch} />
      ) : !pageItems.length ? (
        <EmptyState
          icon={AlertTriangle}
          title={search || filterSev || filterStatus ? 'No matching incidents' : 'No incidents yet'}
          description={
            search || filterSev || filterStatus
              ? 'Try adjusting your filters.'
              : 'Incidents will appear here once Cortex detects activity. Enable demo mode to see synthetic incidents.'
          }
        />
      ) : (
        <>
          <Table>
            <Thead>
              <Th className="w-[36%]">Summary</Th>
              <Th>Service</Th>
              <Th>Severity</Th>
              <Th>Status</Th>
              <Th>Duration</Th>
              <Th>Started</Th>
              <Th />
            </Thead>
            <Tbody>
              {pageItems.map((inc) => (
                <Tr key={inc.id} onClick={() => navigate(`/incidents/${inc.id}`)}>
                  <Td className="max-w-0">
                    <div className="truncate text-zinc-200 font-medium">{inc.title}</div>
                    {inc.auto_healed && (
                      <span className="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded-full mt-1 inline-block">
                        auto-healed
                      </span>
                    )}
                  </Td>
                  <Td className="text-zinc-400 whitespace-nowrap">{inc.service}</Td>
                  <Td><Badge variant={severityVariant(inc.severity)}>{inc.severity}</Badge></Td>
                  <Td><Badge variant={statusVariant(inc.status)} dot>{inc.status}</Badge></Td>
                  <Td className="text-zinc-500 whitespace-nowrap tabular-nums">
                    {inc.status !== 'active' && inc.duration_seconds
                      ? fmtDuration(inc.started_at, inc.resolved_at ?? inc.started_at)
                      : <span className="text-amber-400 text-xs">active</span>}
                  </Td>
                  <Td className="text-zinc-500 whitespace-nowrap text-xs">
                    {formatDistanceToNow(parseISO(inc.started_at), { addSuffix: true })}
                  </Td>
                  <Td>
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={mitigating === inc.id}
                      onClick={(e) => {
                        e.stopPropagation()
                        setMitigating(inc.id)
                        mitigate.mutate(inc.id)
                      }}
                      className="gap-1"
                    >
                      <Sparkles className="w-3 h-3 text-violet-400" />
                      <span className="text-violet-400">Analyze</span>
                    </Button>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
          <Pagination page={page} totalPages={totalPages} onPage={setPage} />
        </>
      )}
    </div>

    {mitigateResult && (
      <MitigateResult
        result={mitigateResult as Parameters<typeof MitigateResult>[0]['result']}
        onClose={() => setMitigateResult(null)}
      />
    )}
    </>
  )
}
