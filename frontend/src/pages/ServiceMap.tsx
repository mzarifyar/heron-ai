import React, { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  ReactFlowProvider, Panel,
  Handle, Position,
  type NodeProps, type EdgeProps,
  getBezierPath, EdgeLabelRenderer, BaseEdge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { RefreshCw, AlertTriangle, Zap } from 'lucide-react'
import api from '../api/client'
import PageHeader from '../components/layout/PageHeader'
import Button from '../components/ui/Button'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ServiceNode {
  id: string; service: string; node_type: 'service'
  health: string; tier: number; x: number; y: number
  latency_p99_ms: number; error_rate_pct: number; rps: number
  cpu_pct: number; memory_pct: number; pool_pct: number
}
interface LBNode {
  id: string; node_type: 'lb_bar'; label: string; lb_tier: number
  x: number; y: number; width: number; health: string
  total_rps: number; active_connections: number
  top_handles: Array<{id:string;left:number}>
  bottom_handles: Array<{id:string;left:number}>
}
interface ServiceEdge {
  id: string; edge_type: string; source: string; target: string
  sourceHandle?: string; targetHandle?: string
  health: string; rps: number; error_rate_pct: number
  p50_ms: number; p95_ms: number; p99_ms: number
  haproxy: {tq_ms?:number;tc_ms?:number;tr_ms?:number;tt_ms?:number;active_connections?:number}
  chronicle: {incident_count?:number;auto_healed_count?:number;avg_mttr_seconds?:number;last_incident?:{title:string;severity:string;auto_healed:boolean;mttr_seconds:number|null}|null}
}
interface GraphData {
  nodes: ServiceNode[]; lb_nodes: LBNode[]; edges: ServiceEdge[]
  node_count: number; lb_count: number; edge_count: number
}

// ── Colors ────────────────────────────────────────────────────────────────────

const HC: Record<string,string> = { ok:'#10b981', warning:'#f59e0b', critical:'#f43f5e', unknown:'#52525b' }
const hc = (h: string) => HC[h] ?? HC.unknown

// ── Service Node ──────────────────────────────────────────────────────────────

function ServiceNodeComponent({ data, selected }: NodeProps) {
  const n = data as unknown as ServiceNode
  const co = hc(n.health)
  return (
    <div style={{
      background: `rgba(${n.health==='critical'?'244,63,94':n.health==='warning'?'245,158,11':'16,185,129'},0.10)`,
      border:`1.5px solid ${co}`, borderRadius:14, padding:'10px 14px', minWidth:160,
      boxShadow: selected?`0 0 0 2px #8b5cf6,0 0 18px ${co}44`:`0 0 14px ${co}33`,
      transition:'box-shadow 0.2s', cursor:'pointer', position:'relative',
    }}>
      <Handle type="target" position={Position.Top}    id="top"       style={{background:co,border:'none',width:7,height:7,top:-4}} />
      <Handle type="source" position={Position.Bottom} id="bottom"    style={{background:co,border:'none',width:7,height:7,bottom:-4}} />
      <Handle type="source" position={Position.Bottom} id="src-left"  style={{background:co,border:'none',width:6,height:6,bottom:-3,left:'30%'}} />
      <Handle type="source" position={Position.Bottom} id="src-right" style={{background:co,border:'none',width:6,height:6,bottom:-3,left:'70%'}} />
      <div style={{display:'flex',alignItems:'center',gap:7,marginBottom:8}}>
        <span style={{width:8,height:8,borderRadius:'50%',background:co,boxShadow:n.health==='critical'?`0 0 6px ${co}`:undefined}}/>
        <span style={{fontSize:11,fontWeight:700,color:'#f4f4f5',letterSpacing:'-0.01em'}}>{n.service}</span>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'3px 8px'}}>
        {[
          {k:'p99',v:n.latency_p99_ms>0?`${n.latency_p99_ms.toFixed(0)}ms`:'—'},
          {k:'err',v:`${n.error_rate_pct.toFixed(1)}%`,warn:n.error_rate_pct>2,crit:n.error_rate_pct>5},
          {k:'rps',v:n.rps>0?n.rps.toFixed(0):'—'},
          {k:'pool',v:n.pool_pct>0?`${n.pool_pct.toFixed(0)}%`:'—',warn:n.pool_pct>80,crit:n.pool_pct>90},
        ].map(({k,v,warn,crit}) => (
          <div key={k} style={{display:'flex',justifyContent:'space-between'}}>
            <span style={{fontSize:9,color:'#52525b',textTransform:'uppercase',letterSpacing:'0.08em'}}>{k}</span>
            <span style={{fontSize:11,fontWeight:500,fontVariantNumeric:'tabular-nums',color:crit?'#f43f5e':warn?'#f59e0b':'#d4d4d8'}}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── LB Bar Node ───────────────────────────────────────────────────────────────

function LBBarNodeComponent({ data }: NodeProps) {
  const lb = data as unknown as LBNode
  const bc = lb.health==='critical'?HC.critical:lb.health==='warning'?HC.warning:'rgba(139,92,246,0.45)'
  return (
    <div style={{
      width:lb.width, height:40, position:'relative',
      background:'linear-gradient(90deg,rgba(139,92,246,0.07),rgba(139,92,246,0.14),rgba(139,92,246,0.07))',
      border:`1px solid ${bc}`, borderRadius:9,
      display:'flex', alignItems:'center', padding:'0 14px', gap:12,
      boxShadow:'0 0 22px rgba(139,92,246,0.2)',
    }}>
      {lb.top_handles?.map(h=>(
        <Handle key={h.id} id={h.id} type="target" position={Position.Top}
          style={{left:h.left,background:bc,border:'none',width:7,height:7,top:-4}} />
      ))}
      {lb.bottom_handles?.map(h=>(
        <Handle key={h.id} id={h.id} type="source" position={Position.Bottom}
          style={{left:h.left,background:bc,border:'none',width:7,height:7,bottom:-4}} />
      ))}
      <div style={{display:'flex',gap:3,flexShrink:0}}>
        {[0,1,2].map(i=><div key={i} style={{width:5,height:5,borderRadius:'50%',background:i===0?bc:'rgba(139,92,246,0.25)',boxShadow:i===0?`0 0 5px ${bc}`:undefined}}/>)}
      </div>
      <span style={{fontSize:10,fontFamily:'"JetBrains Mono",monospace',color:'#a78bfa',fontWeight:700,letterSpacing:'0.12em',flexShrink:0}}>
        {lb.label}
      </span>
      <div style={{display:'flex',gap:2,alignItems:'flex-end',height:20,flex:1,overflow:'hidden'}}>
        {Array.from({length:26}).map((_,i)=>(
          <div key={i} style={{width:3,height:`${20*(0.15+0.85*((Math.sin(i*0.9)+1)/2))}px`,background:`rgba(139,92,246,${0.18+0.45*((Math.sin(i*1.1)+1)/2)})`,borderRadius:1,flexShrink:0}}/>
        ))}
      </div>
      <div style={{display:'flex',gap:10,alignItems:'center',flexShrink:0,fontSize:10}}>
        {lb.total_rps>0&&<span style={{color:'#71717a'}}><span style={{color:'#a78bfa',fontWeight:600}}>{lb.total_rps.toLocaleString()}</span> rps</span>}
        {lb.active_connections>0&&<span style={{color:'#71717a'}}><span style={{color:'#67e8f9'}}>{lb.active_connections}</span> conn</span>}
        <span style={{fontSize:8,padding:'1px 5px',borderRadius:3,background:'rgba(139,92,246,0.2)',color:'#a78bfa',letterSpacing:'0.06em'}}>{lb.health.toUpperCase()}</span>
      </div>
    </div>
  )
}

// ── Edge ──────────────────────────────────────────────────────────────────────

function ServiceEdgeComponent({ id,sourceX,sourceY,targetX,targetY,sourcePosition,targetPosition,data,selected }: EdgeProps) {
  const e = (data??{}) as unknown as ServiceEdge
  const [hovered,setHovered] = useState(false)
  const isUp   = e.edge_type==='service_to_lb'
  const isRed  = e.edge_type==='redundant'
  const color  = isUp?'rgba(139,92,246,0.28)':isRed?'rgba(139,92,246,0.55)':(HC[e.health]??HC.unknown)
  const [path,lx,ly] = getBezierPath({sourceX,sourceY,sourcePosition,targetX,targetY,targetPosition})
  const sw = isUp?1:Math.max(1.5,Math.min(4,(e.rps??0)/300))
  const showTip = hovered&&!isUp&&!isRed

  return (
    <>
      <BaseEdge id={id} path={path} style={{stroke:color,strokeWidth:sw,opacity:isUp?0.22:selected||hovered?1:0.6,strokeDasharray:isUp?'4 7':undefined,transition:'opacity 0.2s'}}/>
      {!isUp&&!isRed&&(
        <path d={path} fill="none" stroke={color} strokeWidth={sw+1} strokeDasharray="5 10" strokeLinecap="round"
          style={{opacity:0.5,animation:'flowAnim 1.8s linear infinite'}}/>
      )}
      <path d={path} fill="none" stroke="transparent" strokeWidth={18}
        onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)} style={{cursor:'default'}}/>

      <EdgeLabelRenderer>
        {showTip&&(
          <div style={{position:'absolute',transform:`translate(-50%,-100%) translate(${lx}px,${ly-8}px)`,pointerEvents:'none',zIndex:999}}>
            <div style={{background:'#0a0a0b',border:'1px solid #27272a',borderRadius:14,padding:'12px 14px',fontSize:11,color:'#a1a1aa',boxShadow:'0 12px 32px rgba(0,0,0,0.8)',minWidth:220}}>
              <div style={{fontWeight:700,marginBottom:10,fontSize:12}}>
                <span style={{color:'#a78bfa'}}>{e.source?.replace(/^lb-[a-z]+$/,'LB')}</span>
                <span style={{color:'#3f3f46',margin:'0 6px'}}>→</span>
                <span style={{color:'#67e8f9'}}>{e.target}</span>
              </div>

              {/* HAProxy timing */}
              {(e.haproxy?.tt_ms??0)>0&&(
                <div style={{marginBottom:10}}>
                  <div style={{fontSize:9,color:'#52525b',textTransform:'uppercase',letterSpacing:'0.08em',marginBottom:6}}>HAProxy Timing</div>
                  <div style={{display:'grid',gridTemplateColumns:'auto 1fr auto',gap:'4px 8px',alignItems:'center'}}>
                    {[
                      {label:'Queue',  val:e.haproxy.tq_ms??0,key:'Tq',warn:(e.haproxy.tq_ms??0)>2},
                      {label:'Connect',val:e.haproxy.tc_ms??0,key:'Tc',warn:false},
                      {label:'Backend',val:e.haproxy.tr_ms??0,key:'Tr',warn:false},
                    ].map(({label,val,key,warn})=>{
                      const c = warn?'#f59e0b':'#6b7280'
                      const pct = (e.haproxy?.tt_ms??1)>0?Math.min(100,(val/(e.haproxy?.tt_ms??1))*100):0
                      return (
                        <React.Fragment key={key}>
                          <span style={{fontSize:10,color:'#52525b'}}>{label}</span>
                          <div style={{height:4,background:'#1f1f1f',borderRadius:2,overflow:'hidden'}}>
                            <div style={{height:'100%',width:`${pct}%`,background:c,borderRadius:2}}/>
                          </div>
                          <span style={{fontSize:11,fontWeight:600,fontVariantNumeric:'tabular-nums',color:c,textAlign:'right'}}>{val.toFixed(2)}ms</span>
                        </React.Fragment>
                      )
                    })}
                    <span style={{color:'#a78bfa',fontWeight:700,fontSize:11}}>Total Tt</span>
                    <div style={{height:4,background:'rgba(139,92,246,0.3)',borderRadius:2}}/>
                    <span style={{fontSize:14,fontWeight:800,fontVariantNumeric:'tabular-nums',color:'#a78bfa',textAlign:'right'}}>{(e.haproxy.tt_ms??0).toFixed(1)}ms</span>
                  </div>
                  {(e.haproxy.tq_ms??0)>2&&<div style={{fontSize:9,color:'#f59e0b',marginTop:4}}>⚠ High Tq — backend saturation</div>}
                </div>
              )}

              {/* Percentiles + traffic */}
              {e.p99_ms>0&&(
                <div style={{marginBottom:8}}>
                  <div style={{fontSize:9,color:'#52525b',textTransform:'uppercase',letterSpacing:'0.08em',marginBottom:4}}>Percentiles</div>
                  <div style={{display:'flex',gap:12,alignItems:'baseline'}}>
                    {[['p50',e.p50_ms],['p95',e.p95_ms],['p99',e.p99_ms]].map(([k,v])=>(
                      <div key={k as string} style={{textAlign:'center'}}>
                        <div style={{fontSize:8,color:'#52525b',textTransform:'uppercase'}}>{k}</div>
                        <div style={{fontSize:12,fontWeight:700,fontVariantNumeric:'tabular-nums',color:'#d4d4d8'}}>{(v as number).toFixed(0)}ms</div>
                      </div>
                    ))}
                    <div style={{marginLeft:'auto',textAlign:'right'}}>
                      <div style={{fontSize:8,color:'#52525b',textTransform:'uppercase'}}>err</div>
                      <div style={{fontSize:12,fontWeight:700,color:e.error_rate_pct>2?'#f43f5e':'#d4d4d8'}}>{e.error_rate_pct.toFixed(2)}%</div>
                    </div>
                  </div>
                </div>
              )}
              <div style={{display:'flex',gap:10,marginBottom:(e.chronicle?.incident_count??0)>0?8:0}}>
                {e.rps>0&&<span><span style={{color:'#67e8f9',fontWeight:600}}>{e.rps.toFixed(0)}</span> <span style={{color:'#52525b',fontSize:10}}>rps</span></span>}
                {(e.haproxy?.active_connections??0)>0&&<span><span style={{color:'#a78bfa',fontWeight:600}}>{e.haproxy.active_connections}</span> <span style={{color:'#52525b',fontSize:10}}>conn</span></span>}
              </div>

              {/* Chronicle */}
              {(e.chronicle?.incident_count??0)>0&&(
                <div style={{borderTop:'1px solid #1a1a1a',paddingTop:8}}>
                  <div style={{display:'flex',gap:8,marginBottom:6,flexWrap:'wrap',fontSize:10}}>
                    <span style={{color:'#52525b',fontSize:9,textTransform:'uppercase',letterSpacing:'0.07em'}}>Chronicle</span>
                    <span style={{color:'#a78bfa',fontWeight:700}}>{e.chronicle.incident_count}</span><span style={{color:'#52525b'}}>incidents</span>
                    <span style={{color:'#10b981',fontWeight:700}}>{e.chronicle.auto_healed_count}</span><span style={{color:'#52525b'}}>auto-healed</span>
                    {(e.chronicle.avg_mttr_seconds??0)>0&&(
                      <span style={{color:'#fbbf24',fontWeight:700}}>
                        {(e.chronicle.avg_mttr_seconds!)<60?`${e.chronicle.avg_mttr_seconds}s`:`${Math.round(e.chronicle.avg_mttr_seconds!/60)}m`}
                        <span style={{color:'#52525b',fontWeight:400}}> avg MTTR</span>
                      </span>
                    )}
                  </div>
                  {e.chronicle.last_incident&&(
                    <div style={{background:'#111113',border:'1px solid #27272a',borderRadius:8,padding:'7px 9px'}}>
                      <div style={{fontSize:9,color:'#52525b',textTransform:'uppercase',marginBottom:4}}>Last incident</div>
                      <div style={{color:'#e4e4e7',fontSize:11,fontWeight:500,lineHeight:1.35,marginBottom:5,maxWidth:280,whiteSpace:'normal'}}>
                        {e.chronicle.last_incident.title}
                      </div>
                      <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
                        <span style={{
                          fontSize:9,padding:'1px 6px',borderRadius:4,fontWeight:700,
                          background:e.chronicle.last_incident.severity==='sev1'?'rgba(244,63,94,0.2)':'rgba(245,158,11,0.2)',
                          color:e.chronicle.last_incident.severity==='sev1'?'#f87171':'#fbbf24',
                          border:`1px solid ${e.chronicle.last_incident.severity==='sev1'?'rgba(244,63,94,0.4)':'rgba(245,158,11,0.4)'}`,
                        }}>{e.chronicle.last_incident.severity}</span>
                        {e.chronicle.last_incident.auto_healed?(
                          <span style={{fontSize:10,color:'#10b981',fontWeight:600}}>
                            ✓ auto-healed
                            {e.chronicle.last_incident.mttr_seconds!=null&&(
                              <span style={{color:'#6ee7b7'}}>{' '}in {e.chronicle.last_incident.mttr_seconds<60?`${e.chronicle.last_incident.mttr_seconds}s`:`${Math.floor(e.chronicle.last_incident.mttr_seconds/60)}m ${e.chronicle.last_incident.mttr_seconds%60}s`}</span>
                            )}
                          </span>
                        ):<span style={{fontSize:10,color:'#71717a'}}>manual resolve</span>}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  )
}

// ── Critical Paths Panel ──────────────────────────────────────────────────────

interface CriticalPath {
  services:string[];hops:Array<{from:string;to:string;p99_ms:number;tt_ms:number;tq_ms:number;tc_ms:number;tr_ms:number;rps:number}>
  total_p99_ms:number;total_tt_ms:number;bottleneck:string;bottleneck_tt:number;bottleneck_pct:number
}

function CriticalPathsPanel() {
  const [open,setOpen] = useState(false)
  const {data} = useQuery({
    queryKey:['critical-paths'],
    queryFn:()=>api.get('/api/v1/tracing/paths?max_paths=7').then(r=>r.data as {paths:CriticalPath[]}),
    refetchInterval:30_000,
  })
  const paths = data?.paths??[]

  return (
    <div style={{borderTop:'1px solid #1a1a1a',background:'#09090b',flexShrink:0}}>
      <button onClick={()=>setOpen(o=>!o)} style={{width:'100%',display:'flex',alignItems:'center',justifyContent:'space-between',padding:'8px 20px',background:'none',border:'none',cursor:'pointer',color:'#a1a1aa',fontSize:12,fontWeight:500}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <span style={{fontSize:14,color:'#6366f1'}}>⇢</span>
          <span>E2E Critical Paths</span>
          {paths.length>0&&<span style={{background:'#1a1a1a',borderRadius:10,padding:'1px 7px',fontSize:10,color:'#71717a'}}>{paths.length} paths</span>}
          {paths[0]&&<span style={{color:'#f43f5e',fontSize:11,fontVariantNumeric:'tabular-nums'}}>slowest: {paths[0].total_tt_ms.toFixed(0)}ms <span style={{color:'#52525b',fontSize:9}}>Tt</span></span>}
        </div>
        <span style={{fontSize:16}}>{open?'▾':'▸'}</span>
      </button>

      {open&&(
        <div style={{padding:'0 20px 16px',overflowX:'auto'}}>
          {paths.length===0?<p style={{color:'#52525b',fontSize:12,margin:0}}>No path data yet.</p>:(
            <div style={{display:'flex',flexDirection:'column',gap:10}}>
              {paths.map((p,i)=>(
                <div key={i} style={{background:'#0f0f10',borderRadius:10,padding:'10px 14px',border:'1px solid #1a1a1a',overflowX:'auto'}}>
                  <div style={{display:'flex',gap:20,marginBottom:10,alignItems:'baseline'}}>
                    <div>
                      <span style={{fontSize:20,fontWeight:800,fontVariantNumeric:'tabular-nums',color:p.total_tt_ms>800?'#f43f5e':p.total_tt_ms>400?'#f59e0b':'#10b981'}}>{p.total_tt_ms.toFixed(0)}ms</span>
                      <span style={{fontSize:9,color:'#52525b',marginLeft:4}}>Tt</span>
                    </div>
                    <span style={{color:'#3f3f46',fontSize:10}}>p99: <span style={{color:'#71717a'}}>{p.total_p99_ms.toFixed(0)}ms</span></span>
                    <span style={{color:'#3f3f46',fontSize:10}}>bottleneck: <span style={{color:'#f59e0b',fontWeight:600}}>{p.bottleneck} ({p.bottleneck_pct.toFixed(0)}%)</span></span>
                  </div>
                  <div style={{display:'flex',alignItems:'center',gap:0,flexWrap:'nowrap',overflowX:'auto'}}>
                    <div style={{background:'#1a1a1e',borderRadius:6,padding:'4px 9px',fontSize:11,fontWeight:600,color:'#d4d4d8',flexShrink:0}}>{p.services[0]}</div>
                    {p.hops.map((h,hi)=>{
                      const pct=p.total_tt_ms>0?h.tt_ms/p.total_tt_ms:0
                      const ac=pct>0.6?'#f43f5e':pct>0.35?'#f59e0b':'#6b7280'
                      const isBot=h.to===p.bottleneck
                      return (
                        <React.Fragment key={hi}>
                          <div style={{display:'flex',flexDirection:'column',alignItems:'center',margin:'0 4px',flexShrink:0,minWidth:68}}>
                            <span style={{fontSize:10,fontWeight:700,color:ac,fontVariantNumeric:'tabular-nums'}}>{h.tt_ms.toFixed(0)}ms</span>
                            <div style={{display:'flex',gap:2,fontSize:8,color:'#52525b'}}>
                              <span style={{color:h.tq_ms>2?'#f59e0b':'#52525b'}} title="Queue">Tq{h.tq_ms.toFixed(1)}</span>
                              <span title="Connect">Tc{h.tc_ms.toFixed(1)}</span>
                              <span title="Backend">Tr{h.tr_ms.toFixed(0)}</span>
                            </div>
                            <span style={{color:ac,fontSize:14,lineHeight:1}}>→</span>
                          </div>
                          <div style={{background:isBot?'rgba(244,63,94,0.15)':'#1a1a1e',border:isBot?'1px solid rgba(244,63,94,0.4)':'1px solid transparent',borderRadius:6,padding:'4px 9px',fontSize:11,fontWeight:600,color:isBot?'#f87171':'#d4d4d8',flexShrink:0,position:'relative'}}>
                            {h.to}
                            {isBot&&<span style={{position:'absolute',top:-8,right:-2,fontSize:9,color:'#f43f5e',fontWeight:700}}>{p.bottleneck_pct.toFixed(0)}%</span>}
                          </div>
                        </React.Fragment>
                      )
                    })}
                  </div>
                </div>
              ))}
              <p style={{fontSize:10,color:'#252525',textAlign:'right',margin:'2px 0 0'}}>Tt = HAProxy total (Tq+Tc+Tr). Amber Tq = backend saturation.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

const nodeTypes = { serviceNode: ServiceNodeComponent, lbBarNode: LBBarNodeComponent }
const edgeTypes = { default: ServiceEdgeComponent }

function MapInner() {
  const {data:graph,isLoading,refetch} = useQuery({
    queryKey:['service-graph'],
    queryFn:()=>api.get('/api/v1/tracing/graph').then(r=>r.data as GraphData),
    refetchInterval:15_000,
  })

  const rfNodes = useMemo(()=>{
    if(!graph) return []
    const svcNodes = graph.nodes.map(n=>({id:n.id,type:'serviceNode',position:{x:n.x,y:n.y},data:n as unknown as Record<string,unknown>}))
    const lbNodes  = (graph.lb_nodes??[]).map(lb=>({id:lb.id,type:'lbBarNode',position:{x:lb.x,y:lb.y},data:lb as unknown as Record<string,unknown>,selectable:false,draggable:false}))
    return [...svcNodes,...lbNodes]
  },[graph])

  const rfEdges = useMemo(()=>(graph?.edges??[]).map(e=>({
    id:e.id,source:e.source,target:e.target,
    sourceHandle:e.sourceHandle,targetHandle:e.targetHandle,
    type:'default',
    data:e as unknown as Record<string,unknown>,
  })),[graph])

  const [nodes,,onNodesChange] = useNodesState(rfNodes)
  const [edges,,onEdgesChange] = useEdgesState(rfEdges)
  const syncedNodes = rfNodes.length?rfNodes:nodes
  const syncedEdges = rfEdges.length?rfEdges:edges

  const criticals = graph?.nodes.filter(n=>n.health==='critical').length??0
  const warnings  = graph?.nodes.filter(n=>n.health==='warning').length??0

  return (
    <div className="animate-fade-in h-full flex flex-col">
      <PageHeader title="Service Map"
        subtitle="HAProxy LB tiers — hover any edge for Tq/Tc/Tr/Tt breakdown + Chronicle history"
        actions={
          <div className="flex items-center gap-3">
            {criticals>0&&<span className="flex items-center gap-1.5 text-xs text-rose-400"><AlertTriangle className="w-3 h-3"/>{criticals} critical</span>}
            {warnings>0&&<span className="flex items-center gap-1.5 text-xs text-amber-400"><Zap className="w-3 h-3"/>{warnings} warning</span>}
            <Button variant="ghost" size="sm" onClick={()=>refetch()}><RefreshCw className="w-3.5 h-3.5"/>Refresh</Button>
          </div>
        }
      />
      <div style={{flex:1,position:'relative',minHeight:0}}>
        <style>{`@keyframes flowAnim{from{stroke-dashoffset:18}to{stroke-dashoffset:0}}`}</style>
        <ReactFlow nodes={syncedNodes} edges={syncedEdges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes} edgeTypes={edgeTypes}
          fitView fitViewOptions={{padding:0.1}} style={{background:'#09090b'}}
          proOptions={{hideAttribution:true}} defaultEdgeOptions={{type:'default'}}>
          <Background color="#1a1a1e" gap={32} size={1}/>
          <Controls style={{background:'#18181b',border:'1px solid #27272a',borderRadius:8}}/>
          <MiniMap style={{background:'#18181b',border:'1px solid #27272a',borderRadius:8}}
            nodeColor={n=>{const d=n.data as any;if(d?.node_type==='lb_bar')return '#8b5cf6';return HC[d?.health??'unknown']??HC.unknown}}
            maskColor="rgba(9,9,11,0.7)"/>
          <Panel position="top-left">
            <div style={{background:'#18181b',border:'1px solid #27272a',borderRadius:10,padding:'7px 12px',display:'flex',gap:14,fontSize:11,flexWrap:'wrap'}}>
              {[['#10b981','Healthy'],['#f59e0b','Warning'],['#f43f5e','Critical'],['#8b5cf6','LB / HAProxy']].map(([c,l])=>(
                <div key={l} style={{display:'flex',alignItems:'center',gap:5}}>
                  <span style={{width:8,height:8,borderRadius:l==='LB / HAProxy'?2:'50%',background:c,display:'inline-block'}}/>
                  <span style={{color:'#a1a1aa'}}>{l}</span>
                </div>
              ))}
              {graph&&<span style={{color:'#3f3f46',marginLeft:6}}>{graph.node_count} services · {graph.lb_count} LBs · {graph.edge_count} edges</span>}
            </div>
          </Panel>
        </ReactFlow>
        {isLoading&&(
          <div style={{position:'absolute',inset:0,background:'rgba(9,9,11,0.7)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:20}}>
            <div style={{color:'#a1a1aa',fontSize:13}}>Loading service graph…</div>
          </div>
        )}
      </div>
      <CriticalPathsPanel/>
    </div>
  )
}

export default function ServiceMap() {
  return <ReactFlowProvider><MapInner/></ReactFlowProvider>
}
