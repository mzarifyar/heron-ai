"""Local lightweight SQLite state for puller visibility.

"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional
import json
import sqlite3

from ..core import get_settings


class LocalStateDB:
    """Provides LocalStateDB behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self, path: Optional[str] = None) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.path = path
        self._lock = Lock()

    def _db_path(self) -> Path:
        """Builds db path using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        configured = self.path or get_settings().local_db_path
        return Path(configured)

    def _connect(self) -> sqlite3.Connection:
        """Builds connect using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        db_path = self._db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        """Ensures schema using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS puller_runs (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      source TEXT NOT NULL,
                      status TEXT NOT NULL,
                      reason TEXT NOT NULL,
                      started_at TEXT NOT NULL,
                      completed_at TEXT NOT NULL,
                      duration_ms INTEGER NOT NULL,
                      summary_json TEXT,
                      error TEXT,
                      created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_puller_runs_source_completed
                      ON puller_runs (source, completed_at DESC);

                    CREATE TABLE IF NOT EXISTS jira_tickets (
                      ticket_key TEXT PRIMARY KEY,
                      summary TEXT,
                      labels_json TEXT NOT NULL,
                      group_name TEXT,
                      context_json TEXT NOT NULL,
                      ingest_status TEXT NOT NULL,
                      first_seen_at TEXT NOT NULL,
                      last_seen_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_jira_tickets_last_seen
                      ON jira_tickets (last_seen_at DESC);

                    CREATE TABLE IF NOT EXISTS cluster_hygiene_runs (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      source TEXT NOT NULL,
                      status TEXT NOT NULL,
                      reason TEXT NOT NULL,
                      started_at TEXT NOT NULL,
                      completed_at TEXT NOT NULL,
                      duration_ms INTEGER NOT NULL,
                      summary_json TEXT NOT NULL,
                      error TEXT,
                      created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_cluster_hygiene_runs_completed
                      ON cluster_hygiene_runs (completed_at DESC);

                    CREATE TABLE IF NOT EXISTS cluster_hygiene_findings (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      run_id INTEGER NOT NULL,
                      cluster_name TEXT NOT NULL,
                      cluster_display_name TEXT,
                      namespace TEXT NOT NULL,
                      pod_name TEXT NOT NULL,
                      status TEXT NOT NULL,
                      phase TEXT,
                      reason TEXT,
                      node_name TEXT,
                      restart_count INTEGER NOT NULL DEFAULT 0,
                      created_at TEXT NOT NULL,
                      FOREIGN KEY(run_id) REFERENCES cluster_hygiene_runs(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_cluster_hygiene_findings_run
                      ON cluster_hygiene_findings (run_id, cluster_name, namespace, pod_name);

                    CREATE TABLE IF NOT EXISTS diagnostics_runs (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ticket_key TEXT NOT NULL,
                      runbook_id TEXT,
                      status TEXT NOT NULL,
                      execution_mode TEXT NOT NULL,
                      started_at TEXT NOT NULL,
                      finished_at TEXT NOT NULL,
                      payload_json TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_diagnostics_runs_ticket_created
                      ON diagnostics_runs (ticket_key, created_at DESC);

                    CREATE TABLE IF NOT EXISTS diagnostics_steps (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      diagnostics_run_id INTEGER NOT NULL,
                      pass_name TEXT NOT NULL,
                      step_index INTEGER,
                      status TEXT NOT NULL,
                      command TEXT,
                      stdout TEXT,
                      stderr TEXT,
                      duration_ms INTEGER,
                      created_at TEXT NOT NULL,
                      FOREIGN KEY(diagnostics_run_id) REFERENCES diagnostics_runs(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_diagnostics_steps_run
                      ON diagnostics_steps (diagnostics_run_id, pass_name, step_index);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def record_puller_run(
        self,
        *,
        source: str,
        status: str,
        reason: str,
        started_at: str,
        completed_at: str,
        duration_ms: int,
        summary: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        """Records puller run using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO puller_runs (
                      source, status, reason, started_at, completed_at, duration_ms, summary_json, error, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        status,
                        reason,
                        started_at,
                        completed_at,
                        int(duration_ms),
                        json.dumps(summary or {}),
                        error,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def upsert_jira_ticket(
        self,
        *,
        ticket_key: str,
        summary: str,
        labels: List[str],
        group_name: Optional[str],
        context: Dict[str, Any],
        ingest_status: str,
    ) -> None:
        """Upserts jira ticket using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO jira_tickets (
                      ticket_key, summary, labels_json, group_name, context_json, ingest_status, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticket_key) DO UPDATE SET
                      summary=excluded.summary,
                      labels_json=excluded.labels_json,
                      group_name=excluded.group_name,
                      context_json=excluded.context_json,
                      ingest_status=excluded.ingest_status,
                      last_seen_at=excluded.last_seen_at
                    """,
                    (
                        ticket_key,
                        summary,
                        json.dumps(labels),
                        group_name,
                        json.dumps(context or {}),
                        ingest_status,
                        now,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_puller_runs(self, *, limit: int = 50, source: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists puller runs using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        query = """
            SELECT id, source, status, reason, started_at, completed_at, duration_ms, summary_json, error, created_at
            FROM puller_runs
        """
        params: List[Any] = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY completed_at DESC LIMIT ?"
        params.append(int(limit))

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        items: List[Dict[str, Any]] = []
        for row in rows:
            summary_raw = row["summary_json"]
            try:
                summary = json.loads(summary_raw) if isinstance(summary_raw, str) else {}
            except json.JSONDecodeError:
                summary = {}
            items.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "status": row["status"],
                    "reason": row["reason"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "duration_ms": row["duration_ms"],
                    "summary": summary,
                    "error": row["error"],
                    "created_at": row["created_at"],
                }
            )
        return items

    def list_jira_tickets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        query: Optional[str] = None,
        project: Optional[str] = None,
        sort_by: str = "last_seen_at",
        sort_dir: str = "desc",
    ) -> tuple[List[Dict[str, Any]], int]:
        """Lists jira tickets using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        base_sql = """
            FROM jira_tickets
        """
        params: List[Any] = []
        where_clauses: List[str] = []

        project_key = (project or "").strip().upper()
        if project_key in {"ODA", "CDA"}:
            where_clauses.append("ticket_key LIKE ?")
            params.append(f"{project_key}-%")

        if query:
            where_clauses.append("(ticket_key LIKE ? OR summary LIKE ?)")
            token = f"%{query}%"
            params.extend([token, token])
        if where_clauses:
            base_sql += " WHERE " + " AND ".join(where_clauses)

        total_sql = f"SELECT COUNT(*) AS total {base_sql}"
        sort_map = {
            "ticket_key": "ticket_key",
            "ticket_number": "CAST(SUBSTR(ticket_key, INSTR(ticket_key, '-') + 1) AS INTEGER)",
            "ingest_status": "ingest_status",
            "last_seen_at": "last_seen_at",
            "first_seen_at": "first_seen_at",
            "group": "group_name",
            "summary": "summary",
        }
        sort_col = sort_map.get((sort_by or "").strip(), "last_seen_at")
        direction = "ASC" if (sort_dir or "").strip().lower() == "asc" else "DESC"
        data_sql = (
            "SELECT ticket_key, summary, labels_json, group_name, context_json, ingest_status, first_seen_at, last_seen_at "
            f"{base_sql} ORDER BY {sort_col} {direction}, ticket_key ASC LIMIT ? OFFSET ?"
        )
        data_params = [*params, int(limit), max(0, int(offset))]

        conn = self._connect()
        try:
            total_row = conn.execute(total_sql, params).fetchone()
            total = int(total_row["total"]) if total_row else 0
            rows = conn.execute(data_sql, data_params).fetchall()
        finally:
            conn.close()

        items: List[Dict[str, Any]] = []
        for row in rows:
            try:
                labels = json.loads(row["labels_json"]) if isinstance(row["labels_json"], str) else []
            except json.JSONDecodeError:
                labels = []
            try:
                context = json.loads(row["context_json"]) if isinstance(row["context_json"], str) else {}
            except json.JSONDecodeError:
                context = {}
            items.append(
                {
                    "ticket_key": row["ticket_key"],
                    "summary": row["summary"],
                    "labels": labels,
                    "group": row["group_name"],
                    "context": context,
                    "ingest_status": row["ingest_status"],
                    "first_seen_at": row["first_seen_at"],
                    "last_seen_at": row["last_seen_at"],
                }
            )
        return items, total

    def list_jira_alarm_references(self, *, limit: int = 5000) -> List[Dict[str, Any]]:
        """Lists jira alarm references using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        query = """
            SELECT ticket_key, context_json, last_seen_at
            FROM jira_tickets
            ORDER BY last_seen_at DESC
            LIMIT ?
        """
        conn = self._connect()
        try:
            rows = conn.execute(query, (int(limit),)).fetchall()
        finally:
            conn.close()

        refs: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            context_raw = row["context_json"]
            try:
                context = json.loads(context_raw) if isinstance(context_raw, str) else {}
            except json.JSONDecodeError:
                continue
            enrichment = context.get("enrichment") if isinstance(context, dict) else {}
            if not isinstance(enrichment, dict):
                continue
            region = str(enrichment.get("alarm_region") or "").strip().lower()
            alarm_id = str(enrichment.get("alarm_id") or "").strip()
            if not region or not alarm_id:
                continue
            key = (region, alarm_id)
            if key in seen:
                continue
            seen.add(key)
            refs.append(
                {
                    "ticket_key": row["ticket_key"],
                    "alarm_region": region,
                    "alarm_id": alarm_id,
                    "last_seen_at": row["last_seen_at"],
                    "alarm_url": enrichment.get("alarm_url"),
                }
            )
        return refs

    def record_cluster_hygiene_report(
        self,
        *,
        source: str,
        status: str,
        reason: str,
        started_at: str,
        completed_at: str,
        duration_ms: int,
        summary: Dict[str, Any],
        findings: List[Dict[str, Any]],
        error: Optional[str] = None,
    ) -> int:
        """Records cluster hygiene report using local writes or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO cluster_hygiene_runs (
                      source, status, reason, started_at, completed_at, duration_ms, summary_json, error, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        status,
                        reason,
                        started_at,
                        completed_at,
                        int(duration_ms),
                        json.dumps(summary or {}),
                        error,
                        now,
                    ),
                )
                run_id = int(cursor.lastrowid)
                for item in findings:
                    if not isinstance(item, dict):
                        continue
                    conn.execute(
                        """
                        INSERT INTO cluster_hygiene_findings (
                          run_id, cluster_name, cluster_display_name, namespace, pod_name, status, phase, reason, node_name, restart_count, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            str(item.get("cluster_name") or ""),
                            str(item.get("cluster_display_name") or ""),
                            str(item.get("namespace") or ""),
                            str(item.get("pod_name") or ""),
                            str(item.get("status") or ""),
                            str(item.get("phase") or ""),
                            str(item.get("reason") or ""),
                            str(item.get("node_name") or ""),
                            int(item.get("restart_count") or 0),
                            now,
                        ),
                    )
                conn.commit()
                return run_id
            finally:
                conn.close()

    def list_cluster_hygiene_runs(self, *, limit: int = 25) -> List[Dict[str, Any]]:
        """Lists cluster hygiene runs using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, source, status, reason, started_at, completed_at, duration_ms, summary_json, error, created_at
                FROM cluster_hygiene_runs
                ORDER BY completed_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        finally:
            conn.close()

        items: List[Dict[str, Any]] = []
        for row in rows:
            summary_raw = row["summary_json"]
            try:
                summary = json.loads(summary_raw) if isinstance(summary_raw, str) else {}
            except json.JSONDecodeError:
                summary = {}
            items.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "status": row["status"],
                    "reason": row["reason"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "duration_ms": row["duration_ms"],
                    "summary": summary,
                    "error": row["error"],
                    "created_at": row["created_at"],
                }
            )
        return items

    def record_diagnostics_execution(
        self,
        *,
        ticket_key: str,
        runbook_id: str,
        payload: Dict[str, Any],
    ) -> int:
        """Records diagnostics execution using local writes or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        status = str(payload.get("status") or "")
        execution_mode = str(payload.get("execution_mode") or "")
        started_at = str(payload.get("started_at") or now)
        finished_at = str(payload.get("finished_at") or now)
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO diagnostics_runs (
                      ticket_key, runbook_id, status, execution_mode, started_at, finished_at, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ticket_key,
                        runbook_id,
                        status,
                        execution_mode,
                        started_at,
                        finished_at,
                        json.dumps(payload or {}),
                        now,
                    ),
                )
                run_id = int(cursor.lastrowid)

                def _insert_step(pass_name: str, idx: int, step: Dict[str, Any]) -> None:
                    """Builds insert step using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
                    conn.execute(
                        """
                        INSERT INTO diagnostics_steps (
                          diagnostics_run_id, pass_name, step_index, status, command, stdout, stderr, duration_ms, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            pass_name,
                            idx,
                            str(step.get("status") or ""),
                            str(step.get("command") or ""),
                            str(step.get("stdout") or ""),
                            str(step.get("stderr") or ""),
                            int(step.get("duration_ms") or 0),
                            now,
                        ),
                    )

                safe = payload.get("safe_pass") if isinstance(payload.get("safe_pass"), dict) else {}
                for idx, step in enumerate(safe.get("steps", []) if isinstance(safe.get("steps"), list) else [], start=1):
                    if isinstance(step, dict):
                        _insert_step("safe", idx, step)
                invasive = payload.get("invasive_pass") if isinstance(payload.get("invasive_pass"), dict) else {}
                for idx, step in enumerate(
                    invasive.get("actions", []) if isinstance(invasive.get("actions"), list) else [], start=1
                ):
                    if isinstance(step, dict):
                        _insert_step("invasive", idx, step)
                overwatch = payload.get("overwatch_pass") if isinstance(payload.get("overwatch_pass"), dict) else {}
                for idx, step in enumerate(
                    overwatch.get("observations", []) if isinstance(overwatch.get("observations"), list) else [],
                    start=1,
                ):
                    if isinstance(step, dict):
                        _insert_step("overwatch", idx, step)
                conn.commit()
                return run_id
            finally:
                conn.close()

    def list_cluster_hygiene_findings(self, *, run_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        """Lists cluster hygiene findings using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, run_id, cluster_name, cluster_display_name, namespace, pod_name, status, phase, reason, node_name, restart_count, created_at
                FROM cluster_hygiene_findings
                WHERE run_id = ?
                ORDER BY cluster_name ASC, namespace ASC, pod_name ASC
                LIMIT ?
                """,
                (int(run_id), int(limit)),
            ).fetchall()
        finally:
            conn.close()

        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "cluster_name": row["cluster_name"],
                "cluster_display_name": row["cluster_display_name"],
                "namespace": row["namespace"],
                "pod_name": row["pod_name"],
                "status": row["status"],
                "phase": row["phase"],
                "reason": row["reason"],
                "node_name": row["node_name"],
                "restart_count": row["restart_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


local_state_db = LocalStateDB()
