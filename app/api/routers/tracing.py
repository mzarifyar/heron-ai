"""Service topology graph endpoint — powers the live service map.

Architecture: api-gateway → LB-Frontend → tier-1 services
                                         → LB-Service → tier-2 services
                                                       → LB-Database → tier-3 services

Each LB node is synthetic (computed here, not in DB). HAProxy timing
(Tq/Tc/Tr/Tt) is pulled from the ServiceEdgeMetric table.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import Incident, ServiceEdgeMetric, Signal

router = APIRouter(prefix="/tracing", tags=["tracing"])

# ── Layout constants ────────────────────────────────────────────────────────
# Column x-positions (left edge of each 170px-wide node)
# LB bars sit at x=-12 and span 1284px to cover all columns + 12px padding

COL_X = {
    "checkout-service":      0,
    "user-profile":          230,
    "auth-service":          440,
    "search-service":        650,
    "recommendation-engine": 860,
    "notification-service":  1060,
    "inventory-service":     0,       # same column as checkout
    "payment-processor":     650,     # same column as search (right of auth-db)
    "auth-db":               440,     # directly below auth-service
    "data-pipeline":         1060,    # same column as notification
    "api-gateway":           500,     # centred above tier-1
}

NODE_WIDTH   = 170
LB_WIDTH     = 1284    # COL_X["notification-service"] + NODE_WIDTH + 12*2 = 1284
LB_X         = -12     # left padding

TIER_Y       = {0: 60, 1: 290, 2: 490, 3: 680}
LB_Y         = {"lb-frontend": 165, "lb-service": 430, "lb-database": 620}

# Which services belong to which tier
TIER_SERVICES = {
    1: ["checkout-service", "user-profile", "auth-service",
        "search-service", "recommendation-engine", "notification-service"],
    2: ["inventory-service", "payment-processor"],
    3: ["auth-db", "data-pipeline"],
}

# Edges routed THROUGH each LB (lb_id: [(source, dest)])
LB_EDGES = {
    "lb-frontend": {
        "above": ["api-gateway"],
        "below": TIER_SERVICES[1],
    },
    "lb-service": {
        "above": TIER_SERVICES[1],
        "below": TIER_SERVICES[2],
    },
    "lb-database": {
        "above": TIER_SERVICES[2],
        "below": TIER_SERVICES[3],
    },
}

# Handle positions on each LB bar (pixel offset from bar left edge x=-12)
# = COL_X[service] + NODE_WIDTH/2 - LB_X  = COL_X + 85 + 12
def _handle_left(service: str) -> int:
    return COL_X.get(service, 440) + 85 + 12


def _edge_health(p99_ms: float, error_rate: float) -> str:
    if error_rate > 0.05 or p99_ms > 1000:
        return "critical"
    if error_rate > 0.02 or p99_ms > 500:
        return "warning"
    return "ok"


def _node_health(error_rate_pct: float, pool_pct: float, latency_p99: float) -> str:
    if error_rate_pct > 5 or pool_pct > 90 or latency_p99 > 1000:
        return "critical"
    if error_rate_pct > 2 or pool_pct > 80 or latency_p99 > 500:
        return "warning"
    return "ok"


@router.get("/graph")
def get_service_graph(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Live service topology with LB bars, node health, and HAProxy edge timing."""
    since_short = datetime.utcnow() - timedelta(hours=2)
    since_long  = datetime.utcnow() - timedelta(hours=24)

    # ── Raw edge metrics from DB ───────────────────────────────────────────
    def _fetch_edges(since: datetime):
        return db.execute(
            select(
                ServiceEdgeMetric.source_service,
                ServiceEdgeMetric.dest_service,
                func.avg(ServiceEdgeMetric.p50_ms).label("p50"),
                func.avg(ServiceEdgeMetric.p95_ms).label("p95"),
                func.avg(ServiceEdgeMetric.p99_ms).label("p99"),
                func.avg(ServiceEdgeMetric.rps).label("rps"),
                func.avg(ServiceEdgeMetric.error_rate).label("err"),
                func.avg(ServiceEdgeMetric.queue_time_ms).label("tq"),
                func.avg(ServiceEdgeMetric.connect_time_ms).label("tc"),
                func.avg(ServiceEdgeMetric.backend_time_ms).label("tr"),
                func.avg(ServiceEdgeMetric.total_time_ms).label("tt"),
                func.avg(ServiceEdgeMetric.active_connections).label("conns"),
                func.max(ServiceEdgeMetric.timestamp).label("last_seen"),
            )
            .where(
                ServiceEdgeMetric.timestamp >= since,
                ServiceEdgeMetric.source_service != ServiceEdgeMetric.dest_service,
            )
            .group_by(ServiceEdgeMetric.source_service, ServiceEdgeMetric.dest_service)
        ).all()

    raw_edges = _fetch_edges(since_short)
    if not raw_edges:
        raw_edges = _fetch_edges(since_long)

    # Index raw edges by dest service for quick lookup
    edge_by_dest: dict[str, Any] = {}
    for r in raw_edges:
        edge_by_dest[r.dest_service] = r

    # ── Chronicle history per service ─────────────────────────────────────
    all_services = list({r.dest_service for r in raw_edges} | {r.source_service for r in raw_edges})
    chron_rows = db.execute(
        select(
            Incident.service,
            func.count(Incident.id).label("total"),
            func.count(Incident.id).filter(Incident.auto_healed.is_(True)).label("healed"),
            func.avg(Incident.mttr_seconds).label("avg_mttr"),
        )
        .where(Incident.service.in_(all_services))
        .group_by(Incident.service)
    ).all()
    chronicle_by_svc = {
        r.service: {
            "incident_count":    int(r.total or 0),
            "auto_healed_count": int(r.healed or 0),
            "avg_mttr_seconds":  round(float(r.avg_mttr or 0)),
        }
        for r in chron_rows
    }

    last_inc_rows = db.execute(
        select(Incident)
        .where(Incident.service.in_(all_services))
        .order_by(Incident.started_at.desc())
    ).scalars().all()
    last_inc_by_svc: dict[str, dict] = {}
    for inc in last_inc_rows:
        if inc.service not in last_inc_by_svc:
            last_inc_by_svc[inc.service] = {
                "title": inc.title, "status": inc.status,
                "severity": inc.severity, "auto_healed": inc.auto_healed,
                "mttr_seconds": inc.mttr_seconds,
                "started_at": inc.started_at.isoformat(),
            }

    # ── Node metrics from signals ─────────────────────────────────────────
    since_sig = datetime.utcnow() - timedelta(hours=24)
    sig_rows = db.execute(
        select(Signal.service, Signal.metric_name, func.avg(Signal.value).label("v"))
        .where(Signal.timestamp >= since_sig)
        .group_by(Signal.service, Signal.metric_name)
    ).all()
    svc_metrics: dict[str, dict[str, float]] = {}
    for r in sig_rows:
        svc_metrics.setdefault(r.service, {})[r.metric_name] = r.v or 0.0

    # Always include every known service so nodes exist even with no live metrics.
    # DB data overlays metrics on top; topology is always visible.
    topology_svcs: set[str] = {"api-gateway"}
    for svcs in TIER_SERVICES.values():
        topology_svcs.update(svcs)
    all_svcs = topology_svcs | set(all_services) | set(svc_metrics.keys())

    # ── Service nodes ──────────────────────────────────────────────────────
    nodes = []
    for svc in sorted(all_svcs):
        if svc.startswith("lb-"):
            continue
        m      = svc_metrics.get(svc, {})
        p99    = m.get("latency_p99_ms", 0)
        err    = m.get("error_rate", 0) * 100
        pool   = m.get("connection_pool_pct", 0)
        cpu    = m.get("cpu_utilization", 0) * 100
        mem    = m.get("memory_utilization", 0) * 100
        rps    = m.get("request_rate_rps", 0)
        health = _node_health(err, pool, p99)

        # Determine tier from TIER_SERVICES mapping
        tier = 1
        for t, svcs in TIER_SERVICES.items():
            if svc in svcs:
                tier = t; break
        if svc == "api-gateway":
            tier = 0

        nodes.append({
            "id": svc, "service": svc, "node_type": "service",
            "health": health, "tier": tier,
            "x": COL_X.get(svc, 440),
            "y": TIER_Y.get(tier, 290),
            "latency_p99_ms": round(p99, 1),
            "error_rate_pct": round(err, 3),
            "rps": round(rps, 1),
            "cpu_pct": round(cpu, 1),
            "memory_pct": round(mem, 1),
            "pool_pct": round(pool, 1),
        })

    # ── LB bar synthetic nodes ─────────────────────────────────────────────
    lb_nodes = []
    for lb_id, cfg in LB_EDGES.items():
        tier_key = {"lb-frontend": 1, "lb-service": 2, "lb-database": 3}[lb_id]
        label = {"lb-frontend": "LB / HAProxy — Frontend",
                 "lb-service":  "LB / HAProxy — Service",
                 "lb-database": "LB / HAProxy — Database"}[lb_id]

        # Aggregate RPS = sum of RPS across services below this LB
        total_rps = sum(
            round(edge_by_dest[svc].rps or 0)
            for svc in cfg["below"]
            if svc in edge_by_dest
        )
        total_conns = sum(
            int(edge_by_dest[svc].conns or 0)
            for svc in cfg["below"]
            if svc in edge_by_dest
        )

        # Health = worst of services in this layer
        lb_health = "ok"
        for svc in cfg["below"]:
            m  = svc_metrics.get(svc, {})
            sh = _node_health(m.get("error_rate", 0)*100,
                              m.get("connection_pool_pct", 0),
                              m.get("latency_p99_ms", 0))
            if sh == "critical":
                lb_health = "critical"; break
            if sh == "warning":
                lb_health = "warning"

        # Handle positions (pixel offset within the 1284px bar)
        top_handles    = [{"id": f"top-{s}",    "left": _handle_left(s)} for s in cfg["above"]]
        bottom_handles = [{"id": f"bottom-{s}", "left": _handle_left(s)} for s in cfg["below"]]

        lb_nodes.append({
            "id": lb_id, "node_type": "lb_bar", "label": label,
            "lb_tier": tier_key,
            "x": LB_X, "y": LB_Y[lb_id],
            "width": LB_WIDTH, "health": lb_health,
            "total_rps": total_rps, "active_connections": total_conns,
            "top_handles": top_handles,
            "bottom_handles": bottom_handles,
        })

    # ── Edges through LB bars ──────────────────────────────────────────────
    def _haproxy_data(r: Any) -> dict:
        if r is None:
            return {}
        tq = round(float(r.tq or 0), 3)
        tc = round(float(r.tc or 0), 3)
        tr = round(float(r.tr or 0), 1)
        tt = round(float(r.tt or 0), 1) or round(tq + tc + tr, 1)
        return {
            "tq_ms": tq, "tc_ms": tc,
            "tr_ms": tr, "tt_ms": tt,
            "active_connections": int(r.conns or 0),
        }

    def _chronicle(svc: str) -> dict:
        return {
            **chronicle_by_svc.get(svc, {"incident_count": 0, "auto_healed_count": 0, "avg_mttr_seconds": 0}),
            "last_incident": last_inc_by_svc.get(svc),
        }

    edges = []

    # api-gateway → lb-frontend (×2 for redundancy)
    r_gw = edge_by_dest.get("auth-service")   # use auth latency as proxy for GW→LB
    for i, (src_h, tgt_h) in enumerate([("src-left", "top-api-gateway-1"),
                                         ("src-right", "top-api-gateway-2")]):
        edges.append({
            "id": f"gw-lb1-{i}", "edge_type": "redundant",
            "source": "api-gateway", "target": "lb-frontend",
            "sourceHandle": src_h, "targetHandle": tgt_h,
            "health": "ok", "rps": 0, "error_rate_pct": 0,
            "p50_ms": 0, "p95_ms": 0, "p99_ms": 0,
            "haproxy": {}, "chronicle": {},
            "label": "redundant" if i == 1 else "",
        })

    # lb → service (downward) and service → lb (upward)
    lb_sequence = [
        ("lb-frontend",  TIER_SERVICES[1]),
        ("lb-service",   TIER_SERVICES[2]),
        ("lb-database",  TIER_SERVICES[3]),
    ]
    for lb_id, svcs in lb_sequence:
        for svc in svcs:
            r = edge_by_dest.get(svc)
            hp = _haproxy_data(r)
            chron = _chronicle(svc)
            h = _edge_health(r.p99 if r else 0, r.err if r else 0)

            # LB → service (request, downward)
            edges.append({
                "id": f"{lb_id}->{svc}", "edge_type": "lb_to_service",
                "source": lb_id, "target": svc,
                "sourceHandle": f"bottom-{svc}", "targetHandle": "top",
                "health": h,
                "rps":            round(r.rps or 0, 1)  if r else 0,
                "error_rate_pct": round((r.err or 0)*100, 3) if r else 0,
                "p50_ms": round(r.p50 or 0, 1) if r else 0,
                "p95_ms": round(r.p95 or 0, 1) if r else 0,
                "p99_ms": round(r.p99 or 0, 1) if r else 0,
                "haproxy": hp,
                "chronicle": chron,
            })

            # service → LB (response, upward) — lighter visual
            edges.append({
                "id": f"{svc}->{lb_id}", "edge_type": "service_to_lb",
                "source": svc, "target": lb_id,
                "sourceHandle": "bottom", "targetHandle": f"top-{svc}",
                "health": h, "rps": 0, "error_rate_pct": 0,
                "p50_ms": 0, "p95_ms": 0, "p99_ms": 0,
                "haproxy": {}, "chronicle": {},
            })

    # Same-tier direct edges (e.g. user-profile → auth-service, within tier 1)
    for r in raw_edges:
        src_tier = next((t for t, s in TIER_SERVICES.items() if r.source_service in s), 0)
        dst_tier = next((t for t, s in TIER_SERVICES.items() if r.dest_service in s), 0)
        if src_tier == dst_tier and src_tier > 0:
            hp    = _haproxy_data(r)
            chron = _chronicle(r.dest_service)
            h     = _edge_health(r.p99 or 0, r.err or 0)
            edges.append({
                "id": f"{r.source_service}=>{r.dest_service}", "edge_type": "same_tier",
                "source": r.source_service, "target": r.dest_service,
                "sourceHandle": "bottom", "targetHandle": "top",
                "health": h,
                "rps":            round(r.rps or 0, 1),
                "error_rate_pct": round((r.err or 0)*100, 3),
                "p50_ms": round(r.p50 or 0, 1),
                "p95_ms": round(r.p95 or 0, 1),
                "p99_ms": round(r.p99 or 0, 1),
                "haproxy": hp,
                "chronicle": chron,
            })

    return {
        "nodes":       nodes,
        "lb_nodes":    lb_nodes,
        "edges":       edges,
        "computed_at": datetime.utcnow().isoformat(),
        "node_count":  len(nodes),
        "lb_count":    len(lb_nodes),
        "edge_count":  len(edges),
    }


@router.get("/paths")
def get_critical_paths(max_paths: int = 7, db: Session = Depends(get_db)) -> dict[str, Any]:
    """E2E critical paths with per-hop HAProxy timing breakdown."""
    since = datetime.utcnow() - timedelta(hours=24)

    rows = db.execute(
        select(
            ServiceEdgeMetric.source_service,
            ServiceEdgeMetric.dest_service,
            func.avg(ServiceEdgeMetric.p99_ms).label("p99"),
            func.avg(ServiceEdgeMetric.p50_ms).label("p50"),
            func.avg(ServiceEdgeMetric.rps).label("rps"),
            func.avg(ServiceEdgeMetric.queue_time_ms).label("tq"),
            func.avg(ServiceEdgeMetric.connect_time_ms).label("tc"),
            func.avg(ServiceEdgeMetric.backend_time_ms).label("tr"),
            func.avg(ServiceEdgeMetric.total_time_ms).label("tt"),
        )
        .where(
            ServiceEdgeMetric.timestamp >= since,
            ServiceEdgeMetric.source_service != ServiceEdgeMetric.dest_service,
        )
        .group_by(ServiceEdgeMetric.source_service, ServiceEdgeMetric.dest_service)
    ).all()

    if not rows:
        return {"paths": [], "computed_at": datetime.utcnow().isoformat()}

    adj: dict[str, list] = {}
    all_targets: set[str] = set()
    for r in rows:
        adj.setdefault(r.source_service, []).append({
            "dest": r.dest_service,
            "p99": r.p99 or 0, "p50": r.p50 or 0, "rps": r.rps or 0,
            "tq": r.tq or 0, "tc": r.tc or 0, "tr": r.tr or 0,
            "tt": r.tt or round((r.tq or 0) + (r.tc or 0) + (r.p50 or 0), 1),
        })
        all_targets.add(r.dest_service)

    entry_points = set(adj.keys()) - all_targets
    if not entry_points:
        entry_points = set(adj.keys())

    all_paths: list[dict] = []

    def dfs(cur: str, svc_path: list, hop_path: list, visited: set) -> None:
        if len(svc_path) > 1:
            total_tt = sum(h["tt"] for h in hop_path)
            total_p99 = sum(h["p99"] for h in hop_path)
            bottleneck = max(hop_path, key=lambda h: h["tt"])
            all_paths.append({
                "services": list(svc_path),
                "hops": [
                    {
                        "from": h["src"], "to": h["dest"],
                        "p99_ms":  round(h["p99"], 1),
                        "p50_ms":  round(h["p50"], 1),
                        "rps":     round(h["rps"], 1),
                        "tq_ms":   round(h["tq"], 3),
                        "tc_ms":   round(h["tc"], 3),
                        "tr_ms":   round(h["tr"], 1),
                        "tt_ms":   round(h["tt"], 1),
                    }
                    for h in hop_path
                ],
                "total_p99_ms":  round(total_p99, 1),
                "total_tt_ms":   round(total_tt, 1),
                "bottleneck":    bottleneck["dest"],
                "bottleneck_tt": round(bottleneck["tt"], 1),
                "bottleneck_pct": round(bottleneck["tt"] / total_tt * 100, 1) if total_tt > 0 else 0,
            })
        if cur not in adj or cur in visited:
            return
        visited.add(cur)
        for edge in adj[cur]:
            if edge["dest"] not in visited:
                dfs(edge["dest"],
                    svc_path + [edge["dest"]],
                    hop_path + [{**edge, "src": cur}],
                    visited.copy())

    for ep in sorted(entry_points):
        dfs(ep, [ep], [], set())

    seen: set[str] = set()
    unique: list[dict] = []
    for p in sorted(all_paths, key=lambda x: x["total_tt_ms"], reverse=True):
        key = "→".join(p["services"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return {
        "paths": unique[:max_paths],
        "total_found": len(unique),
        "computed_at": datetime.utcnow().isoformat(),
    }
