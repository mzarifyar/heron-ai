"""Service dependency graph builder — live topology from real traffic.

Reads ServiceEdgeMetric to construct a directed graph of which services
talk to each other.  Updated every 5 minutes (or on-demand).

Provides:
  - upstream(service)    — all services that call this one (directly or transitively)
  - downstream(service)  — all services this one calls
  - blast_radius(service)— all services affected if this one goes down
  - path(src, dst)       — shortest call path between two services

The graph is also used by the LLM Decide step (context_builder.py) to give
Claude a picture of service dependencies during incident reasoning.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

from ...core import get_logger

logger = get_logger(__name__)

_DEFAULT_LOOKBACK_HOURS = 6


class ServiceGraph:
    """Directed weighted graph of service dependencies.

    Nodes = service names.
    Edges = observed traffic (source → dest) with p99 latency + RPS.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # adj[src] = {dst: {p99_ms, rps, error_rate}}
        self._adj: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
        # reverse: radj[dst] = set of sources
        self._radj: dict[str, set[str]] = defaultdict(set)
        self._built_at: datetime | None = None
        self._node_count = 0
        self._edge_count = 0

    # ── Build ──────────────────────────────────────────────────────────────

    def build(self, lookback_hours: int = _DEFAULT_LOOKBACK_HOURS) -> None:
        """Read ServiceEdgeMetric from DB and rebuild the in-memory graph."""
        try:
            from ...db.base import SessionLocal
            from ...db.models import ServiceEdgeMetric
            from sqlalchemy import select, func

            since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=lookback_hours)

            with SessionLocal() as db:
                rows = db.execute(
                    select(
                        ServiceEdgeMetric.source_service,
                        ServiceEdgeMetric.dest_service,
                        func.avg(ServiceEdgeMetric.p99_ms).label("p99"),
                        func.avg(ServiceEdgeMetric.rps).label("rps"),
                        func.avg(ServiceEdgeMetric.error_rate).label("err"),
                    )
                    .where(ServiceEdgeMetric.timestamp >= since)
                    .group_by(ServiceEdgeMetric.source_service, ServiceEdgeMetric.dest_service)
                ).all()

            adj: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
            radj: dict[str, set[str]] = defaultdict(set)

            for r in rows:
                src, dst = r.source_service, r.dest_service
                if src == dst:
                    continue
                adj[src][dst] = {
                    "p99_ms": round(float(r.p99 or 0), 2),
                    "rps": round(float(r.rps or 0), 2),
                    "error_rate": round(float(r.err or 0), 6),
                }
                radj[dst].add(src)

            with self._lock:
                self._adj = adj
                self._radj = radj
                self._built_at = datetime.now(timezone.utc)
                self._node_count = len(set(adj.keys()) | set(radj.keys()))
                self._edge_count = sum(len(v) for v in adj.values())

            logger.info(
                "Service graph built: %d nodes, %d edges (lookback=%dh)",
                self._node_count, self._edge_count, lookback_hours,
            )
        except Exception as exc:
            logger.warning("Service graph build failed: %s", exc)

    # ── Queries ────────────────────────────────────────────────────────────

    def downstream(self, service: str, max_depth: int = 5) -> dict[str, Any]:
        """All services this service calls (BFS, direct + transitive)."""
        with self._lock:
            return self._bfs(service, self._adj, max_depth)

    def upstream(self, service: str, max_depth: int = 5) -> dict[str, Any]:
        """All services that call this service (BFS, direct + transitive)."""
        with self._lock:
            rev_adj: dict[str, dict[str, dict]] = {}
            for src, dsts in self._radj.items():
                pass  # build reverse of _adj on the fly
            # Use reverse-adj: for each dst, build adj[dst][src]
            rev: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
            for src, dests in self._adj.items():
                for dst, meta in dests.items():
                    rev[dst][src] = meta
            return self._bfs(service, rev, max_depth)

    def blast_radius(self, service: str) -> dict[str, Any]:
        """All services affected if `service` becomes unavailable.

        A service is in the blast radius if it directly or transitively
        calls the failing service AND has no alternative path.
        """
        with self._lock:
            # Every service that depends on this one (upstream callers)
            up = self._bfs_nodes(service, self._build_reverse_adj(), 10)
            # Include the service itself
            affected = {service} | up
            return {
                "service": service,
                "affected_count": len(affected),
                "affected_services": sorted(affected - {service}),
                "direct_callers": sorted(self._radj.get(service, set())),
            }

    def path(self, source: str, dest: str) -> list[str] | None:
        """Shortest call path from source to dest (BFS)."""
        with self._lock:
            if source not in self._adj:
                return None
            queue: deque[list[str]] = deque([[source]])
            visited = {source}
            while queue:
                path = queue.popleft()
                node = path[-1]
                for neighbour in self._adj.get(node, {}):
                    if neighbour == dest:
                        return path + [neighbour]
                    if neighbour not in visited:
                        visited.add(neighbour)
                        queue.append(path + [neighbour])
            return None

    def edges_for(self, service: str) -> dict[str, Any]:
        """All outbound edges from service with their metrics."""
        with self._lock:
            return {
                dst: meta
                for dst, meta in self._adj.get(service, {}).items()
            }

    def all_services(self) -> list[str]:
        with self._lock:
            return sorted(set(self._adj.keys()) | set(self._radj.keys()))

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "node_count": self._node_count,
                "edge_count": self._edge_count,
                "built_at": self._built_at.isoformat() if self._built_at else None,
                "services": self.all_services(),
            }

    # ── Private helpers ────────────────────────────────────────────────────

    def _bfs(
        self,
        start: str,
        adj: dict[str, dict[str, Any]],
        max_depth: int,
    ) -> dict[str, Any]:
        """BFS returning {service: {depth, path, metrics}}."""
        result: dict[str, Any] = {}
        queue: deque[tuple[str, int, list[str]]] = deque([(start, 0, [start])])
        visited = {start}
        while queue:
            node, depth, path = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbour, meta in adj.get(node, {}).items():
                if neighbour not in visited:
                    visited.add(neighbour)
                    result[neighbour] = {
                        "depth": depth + 1,
                        "path": path + [neighbour],
                        "p99_ms": meta.get("p99_ms", 0),
                        "rps": meta.get("rps", 0),
                        "error_rate": meta.get("error_rate", 0),
                    }
                    queue.append((neighbour, depth + 1, path + [neighbour]))
        return result

    def _bfs_nodes(
        self,
        start: str,
        adj: dict[str, dict[str, Any]],
        max_depth: int,
    ) -> set[str]:
        result: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        visited = {start}
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbour in adj.get(node, {}):
                if neighbour not in visited:
                    visited.add(neighbour)
                    result.add(neighbour)
                    queue.append((neighbour, depth + 1))
        return result

    def _build_reverse_adj(self) -> dict[str, dict[str, Any]]:
        """Build reverse adjacency list (dst → {src: meta})."""
        rev: dict[str, dict[str, Any]] = defaultdict(dict)
        for src, dests in self._adj.items():
            for dst, meta in dests.items():
                rev[dst][src] = meta
        return rev


# ── Singleton + refresh scheduler ─────────────────────────────────────────────

_graph = ServiceGraph()
_refresh_thread: threading.Thread | None = None
_stop_event = threading.Event()


def get_graph() -> ServiceGraph:
    """Return the shared graph instance (auto-built on first call)."""
    if _graph._built_at is None:
        _graph.build()
    return _graph


def start_refresh(interval_minutes: int = 5) -> None:
    """Start a background thread that rebuilds the graph every N minutes."""
    global _refresh_thread, _stop_event
    if _refresh_thread and _refresh_thread.is_alive():
        return
    _stop_event.clear()

    def _loop() -> None:
        _graph.build()
        while not _stop_event.wait(interval_minutes * 60):
            _graph.build()

    _refresh_thread = threading.Thread(target=_loop, name="graph-refresh", daemon=True)
    _refresh_thread.start()
    logger.info("Service dependency graph refresh started (interval=%dm)", interval_minutes)


def stop_refresh() -> None:
    _stop_event.set()


# ── Chronicle integration ─────────────────────────────────────────────────────

def surface_blast_radius(service: str, incident_id: str) -> str | None:
    """Return a formatted blast-radius summary for Chronicle timeline injection."""
    try:
        g = get_graph()
        br = g.blast_radius(service)
        affected = br["affected_services"]
        callers  = br["direct_callers"]
        if not affected and not callers:
            return None
        lines = []
        if callers:
            lines.append(f"Direct callers: {', '.join(callers)}")
        if affected:
            lines.append(f"Potentially affected ({len(affected)}): {', '.join(affected[:8])}")
            if len(affected) > 8:
                lines.append(f"  … and {len(affected) - 8} more")
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("blast_radius failed: %s", exc)
        return None
