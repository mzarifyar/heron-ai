import { useQuery } from '@tanstack/react-query'
import { BrainCircuit, TrendingUp, AlertCircle, Sparkles } from 'lucide-react'
import { formatDistanceToNow, parseISO } from 'date-fns'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { getDbLearnSummary, getDbRecommendations, getDbNearMisses } from '../api/dashboard'
import api from '../api/client'

async function getAiDecisions() {
  const { data } = await api.get('/api/v1/explain/ai-decisions?limit=10')
  return data as {
    count: number
    items: Array<{
      event_id: string
      event_type: string
      component: string
      message: string
      happened_at: string
      metadata: {
        reasoning?: string
        action?: string
        confidence?: number
        escalate_immediately?: boolean
        model?: string
        provider?: string
      }
    }>
  }
}
import PageHeader from '../components/layout/PageHeader'
import Card, { CardHeader } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import { SkeletonCard } from '../components/ui/Skeleton'

const BAR_COLORS = ['#8b5cf6', '#7c3aed', '#6d28d9', '#5b21b6', '#4c1d95']

export default function Intelligence() {
  const { data: learn, isLoading: learnLoading, error: learnError, refetch: refetchLearn } =
    useQuery({ queryKey: ['db-learn-summary'], queryFn: getDbLearnSummary })

  const { data: recs, isLoading: recsLoading } =
    useQuery({ queryKey: ['db-recs'], queryFn: getDbRecommendations })

  const { data: nearMisses, isLoading: nmLoading } =
    useQuery({ queryKey: ['db-near-misses'], queryFn: () => getDbNearMisses(20) })

  const { data: aiDecisions } =
    useQuery({ queryKey: ['ai-decisions'], queryFn: getAiDecisions, refetchInterval: 15_000 })

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Intelligence"
        subtitle="Learn loop, AI recommendations, and near-miss patterns"
      />

      <div className="p-6 space-y-6">
        {/* Learn loop summary */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {learnLoading ? (
            <>
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </>
          ) : learnError ? (
            <div className="col-span-3">
              <ErrorState error={learnError as Error} onRetry={refetchLearn} />
            </div>
          ) : learn ? (
            <>
              <Card>
                <CardHeader title="Total Outcomes" />
                <div className="text-3xl font-semibold text-zinc-100 tabular-nums">
                  {learn.total_outcomes}
                </div>
                <p className="text-xs text-zinc-500 mt-1">Actions with recorded results</p>
              </Card>
              <Card>
                <CardHeader title="Success Rate" />
                <div className="text-3xl font-semibold text-emerald-400 tabular-nums">
                  {learn.success_rate != null
                    ? `${(learn.success_rate * 100).toFixed(1)}%`
                    : '—'}
                </div>
                <p className="text-xs text-zinc-500 mt-1">Auto-remediation success</p>
              </Card>
              <Card>
                <CardHeader title="Top Action" />
                <div className="text-base font-medium text-violet-400 truncate">
                  {learn.top_actions?.[0]?.action ?? '—'}
                </div>
                {learn.top_actions?.[0] && (
                  <p className="text-xs text-zinc-500 mt-1">
                    {(learn.top_actions[0].success_rate * 100).toFixed(0)}% success over{' '}
                    {learn.top_actions[0].count} runs
                  </p>
                )}
              </Card>
            </>
          ) : null}
        </div>

        {/* Top actions bar chart */}
        {learn && learn.top_actions?.length > 0 && (
          <Card>
            <CardHeader title="Action Performance" subtitle="Success rate by action" />
            <ResponsiveContainer width="100%" height={180}>
              <BarChart
                data={learn.top_actions.slice(0, 8).map((a) => ({
                  ...a,
                  pct: +(a.success_rate * 100).toFixed(1),
                }))}
                layout="vertical"
                margin={{ top: 0, right: 12, bottom: 0, left: 120 }}
              >
                <XAxis type="number" domain={[0, 100]} tick={{ fill: '#71717a', fontSize: 11 }} tickLine={false} axisLine={false} unit="%" />
                <YAxis type="category" dataKey="action" tick={{ fill: '#a1a1aa', fontSize: 11 }} tickLine={false} axisLine={false} width={116} />
                <Tooltip
                  contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => [`${v}%`, 'Success rate']}
                />
                <Bar dataKey="pct" radius={[0, 4, 4, 0]}>
                  {learn.top_actions.slice(0, 8).map((_, i) => (
                    <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Recommendations */}
          <Card>
            <CardHeader title="Recommendations" subtitle="AI-ranked actions for current conditions" />
            {recsLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-14 bg-zinc-800 rounded-lg animate-pulse" />
                ))}
              </div>
            ) : !recs?.items.length ? (
              <EmptyState
                icon={BrainCircuit}
                title="No recommendations"
                description="Recommendations appear as the learn loop accumulates outcome data."
              />
            ) : (
              <div className="space-y-2">
                {recs.items.slice(0, 8).map((rec, i) => (
                  <div key={rec.id} className="flex items-start gap-3 p-3 bg-zinc-800/50 rounded-lg">
                    <div className="w-5 h-5 rounded bg-violet-600/20 text-violet-400 flex items-center justify-center text-xs font-bold shrink-0">
                      {i + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-zinc-300 leading-snug">{rec.rationale}</div>
                      <div className="flex items-center gap-2 mt-1">
                        <code className="text-[10px] bg-zinc-800 text-violet-400 px-1.5 py-0.5 rounded">{rec.action}</code>
                        <span className="text-xs text-zinc-500">{rec.service}</span>
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-emerald-400 tabular-nums shrink-0">
                      {(rec.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Near-misses */}
          <Card>
            <CardHeader title="Near-Misses" subtitle="Incidents where actions narrowly succeeded or failed" />
            {nmLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-12 bg-zinc-800 rounded-lg animate-pulse" />
                ))}
              </div>
            ) : !nearMisses?.items.length ? (
              <EmptyState
                icon={AlertCircle}
                title="No near-misses detected"
                description="Near-miss events are flagged when verification results indicate marginal outcomes."
              />
            ) : (
              <div className="space-y-2">
                {nearMisses.items.map((nm) => (
                  <div key={nm.id} className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-zinc-200 truncate">{nm.service}</div>
                      <div className="text-xs text-zinc-500">
                        {nm.metric_name} · peak {nm.peak_value < 2 ? `${(nm.peak_value * 100).toFixed(1)}%` : nm.peak_value.toFixed(0)} · {nm.gap_percent}% below threshold
                      </div>
                    </div>
                    <Badge variant="warning">{nm.gap_percent.toFixed(1)}% gap</Badge>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* AI Decisions — the hero card */}
        <Card>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-violet-400" />
                AI Decisions
              </span>
            }
            subtitle="Claude's reasoning for every autonomous decision"
          />
          {!aiDecisions?.items.length ? (
            <EmptyState
              icon={BrainCircuit}
              title="No AI decisions yet"
              description="Send a signal that crosses a threshold to trigger the LLM Decide step."
            />
          ) : (
            <div className="space-y-4">
              {aiDecisions.items.map((d, i) => {
                const meta = d.metadata ?? {}
                const conf = meta.confidence != null ? (meta.confidence * 100).toFixed(0) : null
                return (
                  <div key={d.event_id ?? i} className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-700/50">
                    {/* Header row */}
                    <div className="flex items-center gap-2 mb-3 flex-wrap">
                      <code className="text-xs bg-violet-500/15 text-violet-300 px-2 py-0.5 rounded font-mono">
                        {meta.action ?? d.message.split(']')[0]?.replace('[', '') ?? 'action'}
                      </code>
                      {conf && (
                        <span className={`text-xs font-semibold tabular-nums ${
                          Number(conf) >= 80 ? 'text-emerald-400' :
                          Number(conf) >= 60 ? 'text-amber-400' : 'text-rose-400'
                        }`}>
                          {conf}% confidence
                        </span>
                      )}
                      {meta.escalate_immediately && (
                        <Badge variant="warning">escalated</Badge>
                      )}
                      {meta.model && (
                        <span className="text-[10px] text-zinc-600 font-mono ml-auto">
                          {meta.model}
                        </span>
                      )}
                      <span className="text-[10px] text-zinc-600">
                        {d.happened_at ? formatDistanceToNow(parseISO(d.happened_at), { addSuffix: true }) : ''}
                      </span>
                    </div>
                    {/* Reasoning */}
                    {meta.reasoning && (
                      <p className="text-sm text-zinc-300 leading-relaxed border-l-2 border-violet-500/40 pl-3">
                        {meta.reasoning}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </Card>

        {/* Recent outcomes */}
        {learn?.recent_outcomes && learn.recent_outcomes.length > 0 && (
          <Card>
            <CardHeader title="Recent Outcomes" />
            <div className="space-y-2">
              {learn.recent_outcomes.slice(0, 8).map((o, i) => (
                <div key={i} className="flex items-center gap-3 text-sm">
                  <Badge variant={o.result === 'success' ? 'success' : 'muted'} dot>
                    {o.result}
                  </Badge>
                  <span className="text-zinc-300 truncate flex-1">{o.action}</span>
                  <span className="text-zinc-500 text-xs shrink-0">{o.service}</span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
