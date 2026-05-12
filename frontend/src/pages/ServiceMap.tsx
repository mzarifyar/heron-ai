import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ReactFlow, Background, Controls, MiniMap,
  ReactFlowProvider, Panel,
  Handle, Position,
  type NodeProps, type EdgeProps,
  getBezierPath, EdgeLabelRenderer, BaseEdge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { AlertTriangle, Zap, RefreshCw } from 'lucide-react'
import api from '../api/client'
import PageHeader from '../components/layout/PageHeader'
import Button from '../components/ui/Button'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ServiceNode {
  id: string; service: string; node_type: 'service'
  health: string; latency_p99_ms: number; error_rate_pct: number; rps: number
  x: number; y: number
}
interface LBNode {
  id: string; node_type: 'lb_bar'; label: string; health: string
  total_rps: number; x: number; y: number; width: number
  top_handles: Array<{id:string;left:number}>
  bottom_handles: Array<{id:string;left:number}>
}
interface ServiceEdge {
  id: string; source: string; target: string
  sourceHandle?: string; targetHandle?: string
  edge_type: string; health: string
  rps: number; error_rate_pct: number; p99_ms: number
  chronicle: { incident_count?: number; auto_healed_count?: number }
}
interface GraphData {
  nodes: ServiceNode[]; lb_nodes: LBNode[]; edges: ServiceEdge[]
  node_count: number; lb_count: number; edge_count: number
}

// ── Colours ───────────────────────────────────────────────────────────────────

const HC: Record<string, string> = {
  ok: '#10b981', warning: '#f59e0b', critical: '#f43f5e', unknown: '#52525b',
}
const hc = (h: string) => HC[h] ?? HC.unknown

// ── Service Node ──────────────────────────────────────────────────────────────

function ServiceNodeComponent({ data, selected }: NodeProps) {
  const n = data as unknown as ServiceNode
  const color = hc(n.health)
  return (
    <div style={{
      background: '#111113',
      border: `1.5px solid ${color}`,
      borderRadius: 12,
      padding: '10px 14px',
      minWidth: 148,
      boxShadow: selected ? `0 0 0 2px #8b5cf6` : `0 2px 12px rgba(0,0,0,0.5)`,
      cursor: 'pointer',
    }}>
      <Handle type="target" position={Position.Top}    id="top"    style={{ background: color, border: 'none', width: 7, height: 7 }} />
      <Handle type="source" position={Position.Bottom} id="bottom" style={{ background: color, border: 'none', width: 7, height: 7 }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0,
          boxShadow: n.health === 'critical' ? `0 0 6px ${color}` : undefined }} />
        <span style={{ fontSize: 12, fontWeight: 700, color: '#f4f4f5', letterSpacing: '-0.01em',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {n.service}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 12 }}>
        {[
          { k: 'p99',  v: n.latency_p99_ms > 0 ? `${n.latency_p99_ms.toFixed(0)}ms` : '—' },
          { k: 'err',  v: `${n.error_rate_pct.toFixed(1)}%`, warn: n.error_rate_pct > 2, crit: n.error_rate_pct > 5 },
          { k: 'rps',  v: n.rps > 0 ? n.rps.toFixed(0) : '—' },
        ].map(({ k, v, warn, crit }) => (
          <div key={k}>
            <div style={{ fontSize: 9, color: '#52525b', textTransform: 'uppercase', letterSpacing: '0.07em' }}>{k}</div>
            <div style={{ fontSize: 11, fontWeight: 600, fontVariantNumeric: 'tabular-nums',
              color: crit ? '#f43f5e' : warn ? '#f59e0b' : '#a1a1aa' }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── LB Node ───────────────────────────────────────────────────────────────────

function LBNodeComponent({ data }: NodeProps) {
  const lb = data as unknown as LBNode
  const color = lb.health === 'critical' ? HC.critical : lb.health === 'warning' ? HC.warning : '#8b5cf6'
  return (
    <div style={{
      width: lb.width, height: 36, position: 'relative',
      background: 'rgba(139,92,246,0.06)',
      border: `1px solid ${color}`,
      borderRadius: 8,
      display: 'flex', alignItems: 'center', padding: '0 12px', gap: 10,
    }}>
      {lb.top_handles?.map(h => (
        <Handle key={h.id} id={h.id} type="target" position={Position.Top}
          style={{ left: h.left, background: color, border: 'none', width: 6, height: 6, top: -3 }} />
      ))}
      {lb.bottom_handles?.map(h => (
        <Handle key={h.id} id={h.id} type="source" position={Position.Bottom}
          style={{ left: h.left, background: color, border: 'none', width: 6, height: 6, bottom: -3 }} />
      ))}
      <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#a78bfa', fontWeight: 700,
        letterSpacing: '0.1em', whiteSpace: 'nowrap' }}>
        {lb.label}
      </span>
      {lb.total_rps > 0 && (
        <span style={{ fontSize: 10, color: '#52525b', marginLeft: 'auto', whiteSpace: 'nowrap' }}>
          <span style={{ color: '#a78bfa', fontWeight: 600 }}>{lb.total_rps.toLocaleString()}</span> rps
        </span>
      )}
    </div>
  )
}

// ── Edge ──────────────────────────────────────────────────────────────────────

function ServiceEdgeComponent({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const e = (data ?? {}) as unknown as ServiceEdge
  const [hovered, setHovered] = useState(false)
  const isUplink = e.edge_type === 'service_to_lb' || e.edge_type === 'redundant'
  const color = isUplink ? 'rgba(139,92,246,0.3)' : hc(e.health)
  const width = isUplink ? 1 : Math.max(1.5, Math.min(4, (e.rps ?? 0) / 300))
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })

  return (
    <>
      <BaseEdge id={id} path={path} style={{
        stroke: color, strokeWidth: width,
        opacity: isUplink ? 0.3 : hovered ? 1 : 0.65,
        strokeDasharray: isUplink ? '4 6' : undefined,
        transition: 'opacity 0.15s',
      }} />
      {/* invisible fat hit area for hover */}
      <path d={path} fill="none" stroke="transparent" strokeWidth={16}
        onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
        style={{ cursor: 'default' }} />

      <EdgeLabelRenderer>
        {hovered && !isUplink && (
          <div style={{
            position: 'absolute',
            transform: `translate(-50%, -100%) translate(${lx}px,${ly - 10}px)`,
            pointerEvents: 'none', zIndex: 999,
          }}>
            <div style={{
              background: '#0f0f10', border: '1px solid #27272a', borderRadius: 10,
              padding: '10px 13px', fontSize: 11, color: '#a1a1aa',
              boxShadow: '0 8px 24px rgba(0,0,0,0.7)', minWidth: 180,
            }}>
              <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 12 }}>
                <span style={{ color: '#a78bfa' }}>{e.source}</span>
                <span style={{ color: '#3f3f46', margin: '0 5px' }}>→</span>
                <span style={{ color: '#67e8f9' }}>{e.target}</span>
              </div>
              <div style={{ display: 'flex', gap: 14 }}>
                {[
                  { k: 'p99',  v: e.p99_ms > 0 ? `${e.p99_ms.toFixed(0)}ms` : '—' },
                  { k: 'err',  v: `${e.error_rate_pct.toFixed(2)}%`, warn: e.error_rate_pct > 1 },
                  { k: 'rps',  v: e.rps > 0 ? e.rps.toFixed(0) : '—' },
                ].map(({ k, v, warn }) => (
                  <div key={k}>
                    <div style={{ fontSize: 9, color: '#52525b', textTransform: 'uppercase', letterSpacing: '0.07em' }}>{k}</div>
                    <div style={{ fontSize: 12, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                      color: warn ? '#f59e0b' : '#d4d4d8' }}>{v}</div>
                  </div>
                ))}
              </div>
              {(e.chronicle?.incident_count ?? 0) > 0 && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #1a1a1a',
                  fontSize: 10, color: '#52525b' }}>
                  <span style={{ color: '#a78bfa', fontWeight: 600 }}>{e.chronicle.incident_count}</span> incidents ·{' '}
                  <span style={{ color: '#10b981', fontWeight: 600 }}>{e.chronicle.auto_healed_count ?? 0}</span> auto-healed
                </div>
              )}
            </div>
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

const nodeTypes = { serviceNode: ServiceNodeComponent, lbBarNode: LBNodeComponent }
const edgeTypes = { default: ServiceEdgeComponent }

function MapInner() {
  const { data: graph, isLoading, refetch } = useQuery({
    queryKey: ['service-graph'],
    queryFn: () => api.get('/api/v1/tracing/graph').then(r => r.data as GraphData),
    refetchInterval: 15_000,
  })

  const rfNodes = useMemo(() => {
    if (!graph) return []
    const svc = graph.nodes.map(n => ({
      id: n.id, type: 'serviceNode',
      position: { x: n.x, y: n.y },
      data: n as unknown as Record<string, unknown>,
    }))
    const lbs = (graph.lb_nodes ?? []).map(lb => ({
      id: lb.id, type: 'lbBarNode',
      position: { x: lb.x, y: lb.y },
      data: lb as unknown as Record<string, unknown>,
      selectable: false, draggable: false,
    }))
    return [...svc, ...lbs]
  }, [graph])

  const rfEdges = useMemo(() => (graph?.edges ?? []).map(e => ({
    id: e.id, source: e.source, target: e.target,
    sourceHandle: e.sourceHandle, targetHandle: e.targetHandle,
    type: 'default',
    data: e as unknown as Record<string, unknown>,
  })), [graph])

  const criticals = graph?.nodes.filter(n => n.health === 'critical').length ?? 0
  const warnings  = graph?.nodes.filter(n => n.health === 'warning').length ?? 0

  return (
    <div className="animate-fade-in h-full flex flex-col">
      <PageHeader
        title="Service Map"
        subtitle="Live service topology — hover any edge for latency and traffic details"
        actions={
          <div className="flex items-center gap-3">
            {criticals > 0 && (
              <span className="flex items-center gap-1.5 text-xs text-rose-400">
                <AlertTriangle className="w-3 h-3" />{criticals} critical
              </span>
            )}
            {warnings > 0 && (
              <span className="flex items-center gap-1.5 text-xs text-amber-400">
                <Zap className="w-3 h-3" />{warnings} warning
              </span>
            )}
            <Button variant="ghost" size="sm" onClick={() => refetch()}>
              <RefreshCw className="w-3.5 h-3.5" />Refresh
            </Button>
          </div>
        }
      />

      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        {isLoading && !graph && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', color: '#52525b', fontSize: 13, zIndex: 10 }}>
            Loading service graph…
          </div>
        )}
        <ReactFlow
          nodes={rfNodes} edges={rfEdges}
          nodeTypes={nodeTypes} edgeTypes={edgeTypes}
          fitView fitViewOptions={{ padding: 0.12 }}
          style={{ background: '#09090b' }}
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={{ type: 'default' }}
        >
          <Background color="#1a1a1e" gap={32} size={1} />
          <Controls style={{ background: '#18181b', border: '1px solid #27272a', borderRadius: 8 }} />
          <MiniMap
            style={{ background: '#18181b', border: '1px solid #27272a', borderRadius: 8 }}
            nodeColor={n => {
              const d = n.data as any
              return d?.node_type === 'lb_bar' ? '#8b5cf6' : (HC[d?.health] ?? HC.unknown)
            }}
            maskColor="rgba(9,9,11,0.75)"
          />
          <Panel position="top-left">
            <div style={{
              background: '#18181b', border: '1px solid #27272a', borderRadius: 10,
              padding: '7px 12px', display: 'flex', gap: 14, fontSize: 11, alignItems: 'center',
            }}>
              {[['#10b981','Healthy'],['#f59e0b','Warning'],['#f43f5e','Critical'],['#8b5cf6','LB']].map(([c, l]) => (
                <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ width: 8, height: 8, borderRadius: l === 'LB' ? 2 : '50%',
                    background: c, display: 'inline-block' }} />
                  <span style={{ color: '#71717a' }}>{l}</span>
                </div>
              ))}
              {graph && (
                <span style={{ color: '#3f3f46', borderLeft: '1px solid #27272a', paddingLeft: 12 }}>
                  {graph.node_count} services · {graph.lb_count} LBs · {graph.edge_count} edges
                </span>
              )}
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  )
}

export default function ServiceMap() {
  return <ReactFlowProvider><MapInner /></ReactFlowProvider>
}
