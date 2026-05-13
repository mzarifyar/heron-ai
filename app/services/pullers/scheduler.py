"""Configurable background scheduler for external data pullers.

"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Any, Dict, List
import random
import time

from ...core import get_logger, get_settings
from ...store import checkpoint
from ...store.local_db import local_state_db
from .config import PullerSourceConfig, PullersConfig, load_pullers_config
from .cluster_hygiene_puller import ClusterHygienePuller
from .cursor_store import PullerCursorStore
from .devops_portal_puller import DevOpsPortalPuller
from .jira_puller import JiraPuller
from .prometheus_puller import prometheus_puller
from .cloudwatch_puller import cloudwatch_puller
from .datadog_puller import datadog_puller

logger = get_logger(__name__)


class PullerManager:
    """Provides PullerManager behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(
        self,
        *,
        config_path: str | None = None,
        state_path: str | None = None,
        scheduler_enabled: bool | None = None,
    ) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        settings = get_settings()
        self._config_path = config_path or settings.pullers_config_path
        self._state_path = state_path or settings.pullers_state_path
        self._scheduler_enabled_override = scheduler_enabled
        self._config: PullersConfig = load_pullers_config(self._config_path)
        self._cursor_store = PullerCursorStore(self._state_path)
        self._jira_puller = JiraPuller()
        self._devops_puller = DevOpsPortalPuller()
        self._cluster_hygiene_puller = ClusterHygienePuller()
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._source_state: Dict[str, Dict[str, Any]] = {}
        self._ensure_sources_state()

    def _ensure_sources_state(self) -> None:
        """Ensures sources state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        for name, cfg in self._config.sources.items():
            state = self._source_state.setdefault(name, {})
            state.setdefault("source", name)
            state.setdefault("enabled", cfg.enabled)
            state.setdefault("interval_seconds", cfg.interval_seconds)
            state.setdefault("range_hours", cfg.range_hours)
            state.setdefault("batch_size", cfg.batch_size)
            state.setdefault("jitter_seconds", cfg.jitter_seconds)
            state.setdefault("runs", 0)
            state.setdefault("running", False)
            state.setdefault("last_status", "never")
            state.setdefault("last_run_at", None)
            state.setdefault("last_duration_ms", None)
            state.setdefault("last_error", None)
            state.setdefault("last_result", None)
            state.setdefault("next_run_at", None)

    def _refresh_config(self) -> None:
        """Builds refresh config using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            self._config = load_pullers_config(self._config_path)
            self._ensure_sources_state()
            for name, cfg in self._config.sources.items():
                state = self._source_state[name]
                state["enabled"] = cfg.enabled
                state["interval_seconds"] = cfg.interval_seconds
                state["range_hours"] = cfg.range_hours
                state["batch_size"] = cfg.batch_size
                state["jitter_seconds"] = cfg.jitter_seconds

    def _scheduler_enabled(self) -> bool:
        """Builds scheduler enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if self._scheduler_enabled_override is not None:
            return self._scheduler_enabled_override
        settings = get_settings()
        if settings.pullers_scheduler_enabled is not None:
            return settings.pullers_scheduler_enabled
        return self._config.scheduler_enabled

    def start(self) -> None:
        """Starts the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._refresh_config()
        if not self._scheduler_enabled():
            logger.info("Puller scheduler disabled")
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run_loop, name="puller-scheduler", daemon=True)
            self._thread.start()
        logger.info("Puller scheduler started")

    def stop(self) -> None:
        """Stops the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=2)
        logger.info("Puller scheduler stopped")

    def _run_loop(self) -> None:
        """Runs loop using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        while not self._stop_event.is_set():
            self._refresh_config()
            now = datetime.now(timezone.utc)
            due_sources: List[str] = []

            with self._lock:
                for name, cfg in self._config.sources.items():
                    if not cfg.enabled:
                        continue
                    state = self._source_state[name]
                    if state.get("running"):
                        continue
                    next_run = _parse_iso(state.get("next_run_at"))
                    if next_run is None or now >= next_run:
                        due_sources.append(name)

            for name in due_sources:
                self._execute_source(name=name, reason="scheduled", force=False)

            time.sleep(1.0)

    def _resolve_source_config(self, source: str) -> PullerSourceConfig:
        """Resolves source config using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        cfg = self._config.sources.get(source)
        if cfg is None:
            raise ValueError(f"Unknown puller source: {source}")
        return cfg

    def _run_jira_once(self, cfg: PullerSourceConfig) -> Dict[str, Any]:
        """Runs jira once using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        summary = self._jira_puller.run(range_hours=cfg.range_hours)
        return {
            "summary": summary,
            "cursor": {"last_run_utc": checkpoint.read_last_run_iso()},
        }

    def _run_devops_once(self, cfg: PullerSourceConfig) -> Dict[str, Any]:
        """Runs devops once using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        source_cursor = self._cursor_store.read_all().get("sources", {}).get("devops_portal", {})
        summary, next_cursor = self._devops_puller.run(
            range_hours=cfg.range_hours,
            batch_size=cfg.batch_size,
            cursor=source_cursor if isinstance(source_cursor, dict) else {},
        )
        return {
            "summary": summary,
            "cursor": next_cursor,
        }

    def _run_cluster_hygiene_once(self, cfg: PullerSourceConfig) -> Dict[str, Any]:
        """Runs cluster hygiene once using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        source_cursor = self._cursor_store.read_all().get("sources", {}).get("cluster_hygiene", {})
        summary, next_cursor = self._cluster_hygiene_puller.run(
            range_hours=cfg.range_hours,
            batch_size=cfg.batch_size,
            cursor=source_cursor if isinstance(source_cursor, dict) else {},
        )
        return {
            "summary": summary,
            "cursor": next_cursor,
        }

    def _run_prometheus_once(self, cfg: PullerSourceConfig) -> Dict[str, Any]:
        """Pull from Prometheus/Alertmanager and ingest signals into Sense."""
        if not prometheus_puller.is_configured():
            return {"summary": {"status": "not_configured",
                                "hint": "Set PROMETHEUS_ALERTMANAGER_URL or PROMETHEUS_URL in .env"},
                    "cursor": {}}
        source_cursor = self._cursor_store.read_all().get("sources", {}).get("prometheus", {})
        result = prometheus_puller.pull(
            range_hours=cfg.range_hours,
            batch_size=cfg.batch_size,
            cursor=source_cursor if isinstance(source_cursor, dict) else {},
        )
        accepted = dropped = 0
        if result.signals:
            from ...schemas.signal import SignalContext, SignalIngestRequest
            from ..sense import sense_service
            import os
            # Group signals by service for ingest
            by_service: Dict[str, List] = {}
            for sig in result.signals:
                svc = (sig.details or {}).get("labels", {}).get("service", "prometheus") \
                      if isinstance(sig.details, dict) else "prometheus"
                by_service.setdefault(svc, []).append(sig)
            for svc, sigs in by_service.items():
                context = SignalContext(
                    service=svc, tier="backend", environment="prod",
                    region="unknown", org_id="default",
                    labels={"source": "prometheus"},
                )
                req = SignalIngestRequest(source="prometheus", context=context, signals=sigs)
                try:
                    resp = sense_service.ingest(req, token=None)
                    accepted += resp.accepted
                    dropped  += resp.dropped
                except Exception as exc:
                    logger.warning("Prometheus ingest failed for service %s: %s", svc, exc)
        return {
            "summary": {
                "signals_pulled": len(result.signals),
                "accepted": accepted, "dropped": dropped,
                "errors": len(result.errors),
            },
            "cursor": result.next_cursor,
        }

    def _run_generic_puller_once(self, puller: Any, cfg: Any, source_name: str) -> Dict[str, Any]:
        """Generic helper for any AlertSourceAdapter (CloudWatch, Datadog, etc.)."""
        from ...schemas.signal import SignalContext, SignalIngestRequest
        from ..sense import sense_service

        if not puller.is_configured():
            return {"summary": {"status": "not_configured",
                                "hint": f"Set {source_name.upper()} credentials in .env"},
                    "cursor": {}}
        cursor = self._cursor_store.read_all().get("sources", {}).get(source_name, {})
        result = puller.pull(
            range_hours=cfg.range_hours,
            batch_size=cfg.batch_size,
            cursor=cursor if isinstance(cursor, dict) else {},
        )
        accepted = 0
        if result.signals:
            by_service: Dict[str, List] = {}
            for sig in result.signals:
                svc = (sig.details or {}).get("service", source_name) \
                      if isinstance(sig.details, dict) else source_name
                by_service.setdefault(svc, []).append(sig)
            for svc, sigs in by_service.items():
                context = SignalContext(
                    service=svc, tier="backend", environment="prod",
                    region="unknown", labels={"source": source_name},
                )
                req = SignalIngestRequest(source=source_name, context=context, signals=sigs)
                try:
                    r = sense_service.process(req)
                    accepted += r.accepted
                except Exception:
                    pass
        new_cursor = self._cursor_store.read_all()
        new_cursor.setdefault("sources", {})[source_name] = result.next_cursor
        self._cursor_store.write(new_cursor)
        return {
            "summary": {"accepted": accepted, "total": len(result.signals), "errors": result.errors},
            "cursor": result.next_cursor,
        }

    def _execute_source(self, *, name: str, reason: str, force: bool) -> Dict[str, Any]:
        """Builds execute source using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self._refresh_config()
        cfg = self._resolve_source_config(name)
        if not cfg.enabled and not force:
            return {
                "source": name,
                "status": "skipped",
                "reason": "disabled",
                "detail": "Source disabled in pullers config.",
            }

        started_at = datetime.now(timezone.utc)
        with self._lock:
            state = self._source_state[name]
            state["running"] = True
            state["last_error"] = None

        status = "ok"
        details: Dict[str, Any] = {}
        error_message: str | None = None
        try:
            if name == "jira":
                details = self._run_jira_once(cfg)
            elif name == "devops_portal":
                details = self._run_devops_once(cfg)
            elif name == "cluster_hygiene":
                details = self._run_cluster_hygiene_once(cfg)
            elif name == "prometheus":
                details = self._run_prometheus_once(cfg)
            elif name == "cloudwatch":
                details = self._run_generic_puller_once(cloudwatch_puller, cfg, "cloudwatch")
            elif name == "datadog":
                details = self._run_generic_puller_once(datadog_puller, cfg, "datadog")
            else:
                raise ValueError(f"Unsupported puller source: {name}")
        except Exception as exc:  # pragma: no cover - defensive
            status = "error"
            error_message = str(exc)
            details = {"summary": {}, "cursor": {}}

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        next_run_at = completed_at + timedelta(seconds=cfg.interval_seconds)
        if cfg.jitter_seconds > 0:
            next_run_at += timedelta(seconds=random.randint(0, cfg.jitter_seconds))

        cursor = details.get("cursor")
        if isinstance(cursor, dict) and cursor:
            self._cursor_store.upsert_source(name, cursor)

        with self._lock:
            state = self._source_state[name]
            state["running"] = False
            state["runs"] = int(state.get("runs", 0)) + 1
            state["last_status"] = status
            state["last_run_at"] = completed_at.isoformat()
            state["last_duration_ms"] = duration_ms
            state["last_error"] = error_message
            state["last_result"] = details.get("summary", {})
            state["next_run_at"] = next_run_at.isoformat()

        summary_payload = details.get("summary", {})
        if not isinstance(summary_payload, dict):
            summary_payload = {}
        if name == "cluster_hygiene":
            findings = summary_payload.pop("_findings", [])
            if isinstance(findings, list):
                local_state_db.record_cluster_hygiene_report(
                    source=name,
                    status=status,
                    reason=reason,
                    started_at=started_at.isoformat(),
                    completed_at=completed_at.isoformat(),
                    duration_ms=duration_ms,
                    summary=summary_payload,
                    findings=findings,
                    error=error_message,
                )

        result = {
            "source": name,
            "reason": reason,
            "status": status,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": duration_ms,
            "summary": summary_payload,
            "cursor": cursor or {},
        }
        if error_message:
            result["error"] = error_message

        local_state_db.record_puller_run(
            source=name,
            status=status,
            reason=reason,
            started_at=result["started_at"],
            completed_at=result["completed_at"],
            duration_ms=duration_ms,
            summary=summary_payload,
            error=error_message,
        )
        return result

    def run_now(self, source: str = "jira") -> Dict[str, Any]:
        """Runs now using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if source == "all":
            names = [name for name, cfg in self._config.sources.items() if cfg.enabled]
            if not names:
                return {"requested": source, "results": []}
            return {
                "requested": source,
                "results": [self._execute_source(name=name, reason="manual", force=False) for name in names],
            }
        self._resolve_source_config(source)
        return {"requested": source, "results": [self._execute_source(name=source, reason="manual", force=True)]}

    def status(self) -> Dict[str, Any]:
        """Builds status using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self._refresh_config()
        with self._lock:
            sources = [dict(self._source_state[name]) for name in sorted(self._source_state.keys())]
            running = bool(self._thread and self._thread.is_alive())
        return {
            "scheduler": {"enabled": self._scheduler_enabled(), "running": running},
            "sources": sources,
        }

    def cursors(self) -> Dict[str, Any]:
        """Builds cursors using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return self._cursor_store.read_all()


def _parse_iso(value: Any) -> datetime | None:
    """Parses iso using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


puller_manager = PullerManager()