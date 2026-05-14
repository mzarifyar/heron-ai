import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, Clock, Zap, FileText, ChevronDown, ChevronUp,
} from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { getDbIncident } from '../api/dashboard'
import PageHeader from '../components/layout/PageHeader'
import Badge, { severityVariant, statusVariant } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card, { CardHeader } from '../components/ui/Card'
import Tabs from '../components/ui/Tabs'
import ErrorState from '../components/ui/ErrorState'
import EmptyState from '../components/ui/EmptyState'
import { SkeletonTable } from '../components/ui/Skeleton'
import type { DbTimelineEvent } from '../api/dashboard'

function eventTypeColor(type: string): string {
  if (type.startsWith('sense') || type.startsWith('ingest')) return 'bg-sky-500'
  if (type.startsWith('insight') || type.startsWith('anomaly')) return 'bg-amber-500'
  if (type.startsWith('core') || type.startsWith('decision')) return 'bg-violet-500'
  if (type.startsWith('reflex') || type.startsWith('action')) return 'bg-orange-500'
  if (type.startsWith('verify') || type.startsWith('verification')) return 'bg-teal-500'
  if (type.startsWith('escalat')) return 'bg-rose-500'
  if (type.includes('learn')) return 'bg-emerald-500'
  return 'bg-zinc-500'
}

function TimelineItem({ entry, isLast }: { entry: DbTimelineEvent; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const hasMeta = entry.metadata != null && Object.keys(entry.metadata).length > 0
  const isLlm = entry.event_type === 'decision.llm'
  const meta = entry.metadata as Record<string, unknown> | null

  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <div className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${eventTypeColor(entry.event_type)}`} />
        {!isLast && <div className="w-px flex-1 bg-zinc-800 mt-1" />}
      </div>
      <div className="pb-4 flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-mono text-zinc-500">
            {format(parseISO(entry.timestamp), 'HH:mm:ss')}
          </span>
          <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${
            isLlm
              ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30'
              : 'bg-zinc-800 text-zinc-400'
          }`}>
            {isLlm ? '✦ AI Decision' : entry.event_type}
          </span>
          {isLlm && meta?.confidence != null && (
            <span className="text-xs text-violet-400 font-medium">
              {(Number(meta?.confidence ?? 0) * 100).toFixed(0)}% confidence
            </span>
          )}
          {!isLlm && <span className="text-[10px] text-zinc-600">{entry.actor}</span>}
        </div>

        {/* LLM reasoning — always shown expanded */}
        {isLlm ? (
          <div className="mt-2 bg-violet-500/5 border border-violet-500/20 rounded-lg p-3">
            <p className="text-sm text-zinc-300 leading-relaxed border-l-2 border-violet-500/40 pl-3">
              {entry.description}
            </p>
            {Array.isArray(meta?.actions) && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(meta!.actions as string[]).map((a: string) => (
                  <span key={a} className="text-[10px] bg-violet-500/15 text-violet-300 px-2 py-0.5 rounded font-mono border border-violet-500/20">
                    {a}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <>
            <p className="mt-1 text-sm text-zinc-300">{entry.description}</p>
            {hasMeta && (
              <button
                onClick={() => setExpanded((e) => !e)}
                className="text-xs text-zinc-600 hover:text-zinc-400 mt-1 flex items-center gap-1 transition-colors"
              >
                {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {expanded ? 'Hide' : 'Show'} metadata
              </button>
            )}
            {expanded && hasMeta && (
              <pre className="mt-2 text-xs bg-zinc-800/80 rounded-lg p-3 text-zinc-400 overflow-x-auto max-w-xl">
                {JSON.stringify(entry.metadata, null, 2)}
              </pre>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: detail, isLoading, error, refetch } = useQuery({
    queryKey: ['db-incident', id],
    queryFn: () => getDbIncident(id!),
    enabled: !!id,
    refetchInterval: 15_000,
  })

  const tlLoading = isLoading
  const timeline = detail ? { items: detail.timeline, count: detail.timeline.length } : undefined
  const pm = detail?.postmortem

  if (isLoading) return <SkeletonTable rows={10} />
  if (error || !detail)
    return <ErrorState error={error as Error} onRetry={refetch} />

  const inc = detail.incident
  const dur = inc.duration_seconds
    ? (inc.duration_seconds < 60 ? `${inc.duration_seconds}s`
       : inc.duration_seconds < 3600 ? `${Math.round(inc.duration_seconds / 60)}m`
       : `${(inc.duration_seconds / 3600).toFixed(1)}h`)
    : null

  return (
    <div className="animate-fade-in">
      <PageHeader
        title={inc.title}
        subtitle={`${inc.service} · ${inc.environment} · ${inc.region}`}
        actions={
          <Button variant="ghost" size="sm" onClick={() => navigate('/incidents')}>
            <ArrowLeft className="w-3.5 h-3.5" />
            Back
          </Button>
        }
      />

      {/* Meta strip */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-zinc-800 flex-wrap text-xs text-zinc-500">
        <Badge variant={severityVariant(inc.severity)}>{inc.severity}</Badge>
        <Badge variant={statusVariant(inc.status)} dot>{inc.status}</Badge>
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {format(parseISO(inc.started_at), 'MMM d, HH:mm')}
        </span>
        {dur && <span className="flex items-center gap-1"><Zap className="w-3 h-3" />{inc.auto_healed ? 'Auto-healed in' : 'Resolved in'} {dur}</span>}
        {inc.auto_healed && (
          <span className="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded-full">
            auto-healed by Heron
          </span>
        )}
      </div>

      <div className="p-6">
        <Tabs
          tabs={[
            { key: 'timeline', label: 'Timeline', count: timeline?.count },
            { key: 'postmortem', label: 'Postmortem' },
            { key: 'annotations', label: 'Annotations', count: detail.annotations.length },
            { key: 'actions', label: 'Actions', count: detail.actions.length },
          ]}
        >
          {(tab) => (
            <>
              {/* Timeline */}
              {tab === 'timeline' && (
                <div className="mt-5">
                  {tlLoading ? (
                    <SkeletonTable rows={8} />
                  ) : !timeline?.items.length ? (
                    <EmptyState
                      icon={Clock}
                      title="No timeline events yet"
                      description="Events will appear as Heron processes this incident."
                    />
                  ) : (
                    <div className="pl-2">
                      {timeline.items.map((entry, i) => (
                        <TimelineItem
                          key={entry.id}
                          entry={entry}
                          isLast={i === timeline.items.length - 1}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Postmortem */}
              {tab === 'postmortem' && (
                <div className="mt-5 space-y-4">
                  {!pm ? (
                    <EmptyState icon={FileText} title="No postmortem yet" description="Postmortems are written after incident resolution." />
                  ) : (
                    <Card>
                      <CardHeader
                        title="Postmortem"
                        subtitle={`Written by ${pm.author} · ${format(parseISO(pm.created_at), 'MMM d, yyyy')}`}
                      />
                      <pre className="text-sm text-zinc-300 whitespace-pre-wrap font-sans leading-relaxed">
                        {pm.content}
                      </pre>
                    </Card>
                  )}
                </div>
              )}

              {/* Annotations */}
              {tab === 'annotations' && (
                <div className="mt-5 space-y-4">
                  {detail.annotations.length > 0 ? (
                    <div className="space-y-3">
                      {detail.annotations.map((ann) => (
                        <Card key={ann.id}>
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs font-medium text-zinc-300">{ann.author}</span>
                            <span className="text-xs text-zinc-600">·</span>
                            <span className="text-xs text-zinc-500">
                              {format(parseISO(ann.created_at), 'MMM d, HH:mm')}
                            </span>
                          </div>
                          <p className="text-sm text-zinc-300 whitespace-pre-wrap">{ann.content}</p>
                        </Card>
                      ))}
                    </div>
                  ) : (
                    <EmptyState icon={FileText} title="No annotations yet" />
                  )}
                </div>
              )}

              {/* Actions */}
              {tab === 'actions' && (
                <div className="mt-5 space-y-3">
                  {detail.actions.length === 0 ? (
                    <EmptyState icon={Zap} title="No actions recorded" description="Automated actions taken during this incident will appear here." />
                  ) : (
                    detail.actions.map((action) => (
                      <Card key={action.id}>
                        <div className="flex items-center gap-3 mb-2">
                          <Badge variant={action.status === 'success' ? 'success' : action.status === 'failed' ? 'critical' : 'muted'}>
                            {action.status}
                          </Badge>
                          <code className="text-xs text-violet-400">{action.action_type}</code>
                          <span className="text-xs text-zinc-500 ml-auto">
                            {format(parseISO(action.executed_at), 'MMM d, HH:mm:ss')}
                          </span>
                        </div>
                        <p className="text-sm text-zinc-400">{action.target}</p>
                      </Card>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </Tabs>
      </div>
    </div>
  )
}
