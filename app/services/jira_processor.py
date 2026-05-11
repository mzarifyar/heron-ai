"""Jira ingestion pipeline adopted from the legacy Cortex processor.

This service runs the classic polling loop:
  - determine the Jira query window using the checkpoint (fallback to range_hours)
  - fetch incidents via Jira REST
  - stamp processing labels, persist ticket metadata, and normalize summaries
  - record association metadata for downstream mitigations

It intentionally stops short of triggering mitigations/AI so that the port can
grow incrementally while Cortex-AI keeps its modular service boundaries.

"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re
from typing import Any, Dict
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config_control import control_plane_service
from app.domain.associations import load_association_config
from app.domain.parsers import normalize_message, parse_ticket_summary
from app.integrations import jira as jira_api
from app.services.jira_client import search_on_call_tickets
from app.services.diagnostics_planner import diagnostics_planner
from app.services.diagnostics_runner import diagnostics_runner
from app.services.cluster_access import cluster_access_service
from app.services.policy import policy_service
from app.services.runbook_resolver import runbook_resolver
from app.store import checkpoint
from app.store.local_db import local_state_db
from app.store.ticket_store import ensure_data_files, read_ticket_store, upsert_ticket, write_ticket_store
from app.services.verification import verification_service
from utils.logger import log
from utils.settings import (
    get_labels,
    get_processing_range_hours,
)

ALARM_URL_PATTERN = re.compile(
    r"https?://[^/\s]+/monitoring/alarms/(?P<region>[^/\s]+)/(?P<alarm>[0-9a-fA-F-]{36})"
)
RUNBOOK_URL_PATTERN = re.compile(r"https?://[^/\s]+/runbooks/ODA/runbooks/[^\s)\]]+")
OPS_CENTRAL_URL_PATTERN = re.compile(r"https?://[^/\s]+/ops-central/alarms/[^\s)\]]+")
ALARM_ID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
REGION_TAG_PATTERN = re.compile(r"\[([A-Z]{2,}(?:-[A-Z0-9]+)+)\]")
ALARM_STATUS_LINE_PATTERN = re.compile(r"Alarm status:\s*(?P<value>[^\n\r]+)")
MESSAGE_TYPE_LINE_PATTERN = re.compile(r"Message type:\s*(?P<value>[^\n\r]+)")
TRANSITION_TS_LINE_PATTERN = re.compile(r"Transition timestamp:\s*(?P<value>[^\n\r]+)")
TOTAL_METRICS_LINE_PATTERN = re.compile(r"Total metrics firing:\s*(?P<value>[^\n\r]+)")
QUERY_BLOCK_PATTERN = re.compile(
    r"Query:\s*(?P<query>.*?)(?:\n\s*Total metrics firing:|\n\s*Dimensions:|\Z)",
    re.DOTALL,
)
DIMENSIONS_BLOCK_PATTERN = re.compile(r"Dimensions:\s*(?P<dimensions>.*)$", re.DOTALL)


class JiraProcessor:
    """Provides JiraProcessor behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        ensure_data_files()

    @staticmethod
    def _should_update_labels() -> bool:
        """Determines update labels using local writes or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if not JiraProcessor._jira_mutations_enabled():
            return False
        raw = os.getenv("CORTEX_JIRA_INGEST_UPDATE_LABELS", "false").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _jira_mutations_enabled() -> bool:
        """Builds jira mutations enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = os.getenv("CORTEX_JIRA_MUTATIONS_ENABLED", "false").strip().lower()
        if raw not in {"1", "true", "yes", "on"}:
            return False
        return JiraProcessor._role_allowed("jira_mutations", ["admin", "sre"])

    @staticmethod
    def _should_execute_diagnostics() -> bool:
        """Determines execute diagnostics using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = os.getenv("CORTEX_DIAGNOSTICS_EXECUTE", "false").strip().lower()
        if raw not in {"1", "true", "yes", "on"}:
            return False
        return JiraProcessor._role_allowed("diagnostics_execute", ["admin", "sre", "operator"])

    @staticmethod
    def _diagnostics_dry_run() -> bool:
        """Builds diagnostics dry run using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = os.getenv("CORTEX_DIAGNOSTICS_DRY_RUN", "true").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _diagnostics_timeout_seconds() -> int:
        """Builds diagnostics timeout seconds using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        try:
            value = int((os.getenv("CORTEX_DIAGNOSTICS_TIMEOUT_SECONDS") or "45").strip())
            return max(5, min(300, value))
        except (TypeError, ValueError):
            return 45

    @staticmethod
    def _diagnostics_retries() -> int:
        """Builds diagnostics retries using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        try:
            value = int((os.getenv("CORTEX_DIAGNOSTICS_RETRIES") or "0").strip())
            return max(0, min(3, value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _ticket_lifecycle_enabled() -> bool:
        """Builds ticket lifecycle enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if not JiraProcessor._jira_mutations_enabled():
            return False
        raw = os.getenv("CORTEX_JIRA_LIFECYCLE_ENABLED", "false").strip().lower()
        if raw not in {"1", "true", "yes", "on"}:
            return False
        return JiraProcessor._role_allowed("ticket_lifecycle", ["admin", "sre"])

    @staticmethod
    def _verification_enabled() -> bool:
        """Builds verification enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = os.getenv("CORTEX_VERIFICATION_ENABLED", "true").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _sev4_escalation_enabled() -> bool:
        """Builds sev4 escalation enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if not JiraProcessor._jira_mutations_enabled():
            return False
        raw = os.getenv("CORTEX_SEV4_ESCALATION_ENABLED", "false").strip().lower()
        if raw not in {"1", "true", "yes", "on"}:
            return False
        return JiraProcessor._role_allowed("sev4_escalation", ["admin", "sre"])

    @staticmethod
    def _diagnostics_invasive_allowed() -> bool:
        """Builds diagnostics invasive allowed using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        return JiraProcessor._role_allowed("diagnostics_invasive", ["admin", "sre"])

    @staticmethod
    def _operator_role() -> str:
        """Builds operator role using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        return str(os.getenv("CORTEX_OPERATOR_ROLE") or "viewer").strip().lower() or "viewer"

    @staticmethod
    def _role_allowed(capability: str, default_roles: list[str]) -> bool:
        """Checks role allowed using local reads or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        role = JiraProcessor._operator_role()
        return control_plane_service.is_role_allowed(capability, role, default_roles)

    @staticmethod
    def _jira_worker_count() -> int:
        """Builds jira worker count using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        try:
            value = int((os.getenv("CORTEX_JIRA_WORKERS") or "1").strip())
            return max(1, min(8, value))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _ticket_time_budget_seconds() -> int:
        """Builds ticket time budget seconds using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        try:
            value = int((os.getenv("CORTEX_JIRA_TICKET_MAX_SECONDS") or "900").strip())
            return max(30, min(7200, value))
        except (TypeError, ValueError):
            return 900

    @staticmethod
    def _sev4_min_monitor_seconds() -> int:
        """Builds sev4 min monitor seconds using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        try:
            value = int((os.getenv("CORTEX_SEV4_MIN_MONITOR_SECONDS") or "900").strip())
            return max(60, min(86400, value))
        except (TypeError, ValueError):
            return 900

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        """Parses iso datetime using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        text = (value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _display_timezone() -> ZoneInfo:
        """Builds display timezone using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        tz_name = (os.getenv("CORTEX_DISPLAY_TZ") or "America/Los_Angeles").strip()
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo("America/Los_Angeles")

    @staticmethod
    def _extract_alarm_from_description(text: str) -> Dict[str, str]:
        """Extracts alarm from description using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        description = text or ""
        match = ALARM_URL_PATTERN.search(description)
        if not match:
            return {}
        region = (match.group("region") or "").strip().lower()
        alarm_id = (match.group("alarm") or "").strip()
        if not region or not alarm_id:
            return {}
        return {
            "alarm_region": region,
            "alarm_id": alarm_id,
            "alarm_url": match.group(0),
        }

    @staticmethod
    def _infer_region_from_summary(summary: str) -> str:
        """Builds infer region from summary using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        match = REGION_TAG_PATTERN.search(summary or "")
        if not match:
            return ""
        return (match.group(1) or "").strip().lower()

    @staticmethod
    def _extract_alarm_id(text: str) -> str:
        """Extracts alarm id using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        match = ALARM_ID_PATTERN.search(text or "")
        if not match:
            return ""
        return (match.group(0) or "").strip()

    @staticmethod
    def _extract_ticket_description_context(text: str) -> Dict[str, Any]:
        """Extracts ticket description context using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        description = text or ""
        out: Dict[str, Any] = {}

        runbook_match = RUNBOOK_URL_PATTERN.search(description)
        if runbook_match:
            out["runbook_url"] = runbook_match.group(0)

        ops_central_match = OPS_CENTRAL_URL_PATTERN.search(description)
        if ops_central_match:
            out["ops_central_url"] = ops_central_match.group(0)

        alarm_status_match = ALARM_STATUS_LINE_PATTERN.search(description)
        if alarm_status_match:
            out["alarm_status_from_ticket"] = alarm_status_match.group("value").strip()

        message_type_match = MESSAGE_TYPE_LINE_PATTERN.search(description)
        if message_type_match:
            out["message_type"] = message_type_match.group("value").strip()

        transition_match = TRANSITION_TS_LINE_PATTERN.search(description)
        if transition_match:
            out["transition_timestamp"] = transition_match.group("value").strip()

        total_metrics_match = TOTAL_METRICS_LINE_PATTERN.search(description)
        if total_metrics_match:
            out["total_metrics_firing"] = total_metrics_match.group("value").strip()

        query_match = QUERY_BLOCK_PATTERN.search(description)
        if query_match:
            query_text = (query_match.group("query") or "").strip()
            if query_text:
                out["query_text"] = query_text

        dimensions_match = DIMENSIONS_BLOCK_PATTERN.search(description)
        if dimensions_match:
            dims_text = (dimensions_match.group("dimensions") or "").strip()
            if dims_text:
                out["dimensions_text"] = dims_text

        return out

    @staticmethod
    def _resolve_runbook_markdown_path(runbook_ref_path: str) -> Path | None:
        """Resolves runbook markdown path and returns a local file path when it exists."""
        ref = (runbook_ref_path or "").strip().strip("/")
        if not ref:
            return None
        root = Path(__file__).resolve().parents[2]
        candidates = [
            root / "mitigations" / "runbooks" / "oda" / f"{ref}.md",
            root / "mitigations" / "runbooks" / f"{ref}.md",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _clean_markdown_line(text: str) -> str:
        """Normalizes markdown-heavy lines to concise plain text."""
        value = (text or "").strip()
        if not value:
            return ""
        value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
        value = re.sub(r"`([^`]+)`", r"\1", value)
        value = value.replace("&lt;", "<").replace("&gt;", ">")
        value = re.sub(r"\s+", " ", value).strip()
        return value

    @classmethod
    def _extract_runbook_mitigation_steps(cls, runbook_ref_path: str, *, max_steps: int = 6) -> list[str]:
        """Extracts mitigation-oriented numbered steps from runbook markdown."""
        path = cls._resolve_runbook_markdown_path(runbook_ref_path)
        if path is None:
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return []

        steps: list[str] = []
        in_steps_section = False
        numbered_started = False
        heading_re = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
        steps_marker_re = re.compile(r"^\s*(steps?|mitigation|mitigation steps?)\s*:?\s*$", re.IGNORECASE)
        numbered_re = re.compile(r"^\s*\d+\.\s+(.+?)\s*$")

        for raw in lines:
            line = raw.rstrip()
            heading_match = heading_re.match(line)
            if heading_match:
                heading = (heading_match.group(1) or "").strip().lower()
                if "step" in heading or "mitigation" in heading:
                    in_steps_section = True
                    continue
                if in_steps_section:
                    break
                continue

            if steps_marker_re.match(line):
                in_steps_section = True
                continue

            number_match = numbered_re.match(line)
            if number_match and (in_steps_section or not numbered_started):
                cleaned = cls._clean_markdown_line(number_match.group(1))
                if cleaned:
                    steps.append(cleaned)
                    numbered_started = True
                    if len(steps) >= max_steps:
                        break
                continue

            if numbered_started and line.strip() == "":
                continue
            if numbered_started and not number_match and heading_match:
                break

        return steps[:max(1, max_steps)]

    @classmethod
    def _format_created_local(cls, created_utc: str) -> str:
        """Formats created local using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        raw = (created_utc or "").strip()
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
        local = parsed.astimezone(cls._display_timezone())
        return local.strftime("%Y-%m-%d %I:%M:%S %p %Z")

    @staticmethod
    def _should_enrich_alarm_status() -> bool:
        """Determines enrich alarm status using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = os.getenv("CORTEX_JIRA_ENRICH_ALARM_STATUS", "true").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _has_operator_token() -> bool:
        """Checks operator token using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        return bool(
            (os.getenv("OPERATOR_ACCESS_TOKEN") or "").strip()
            or (os.getenv("CORTEX_OPERATOR_ACCESS_TOKEN") or "").strip()
        )

    def _build_enrichment(
        self,
        *,
        item: Dict[str, Any],
        summary_text: str,
        normalized_message: str,
        group: str,
    ) -> Dict[str, Any]:
        """Builds enrichment using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        created_utc = str(item.get("created_utc") or "")
        status_before = str(item.get("status_before") or "")
        description = str(item.get("description") or "")
        query_name = str(item.get("query_name") or "")

        now_local = datetime.now(self._display_timezone())
        enrichment: Dict[str, Any] = {
            "operation": "puller_ingest",
            "query": query_name,
            "status_before": status_before,
            "status_after": status_before,
            "target_status": status_before,
            "created_utc": created_utc,
            "created_local": self._format_created_local(created_utc),
            "shift_date": now_local.date().isoformat(),
            "window_start_local": now_local.replace(minute=0, second=0, microsecond=0).isoformat(),
            "jira": {
                "updated_utc": item.get("updated_utc"),
                "status": item.get("status_before"),
                "status_category": item.get("status_category"),
                "assignee": item.get("assignee"),
                "reporter": item.get("reporter"),
                "priority": item.get("priority"),
                "issue_type": item.get("issue_type"),
                "project_key": item.get("project_key"),
                "project_name": item.get("project_name"),
                "components": item.get("components") or [],
                "resolution": item.get("resolution"),
                "resolution_date_utc": item.get("resolution_date_utc"),
            },
        }

        alarm_info = self._extract_alarm_from_description(description)
        if not alarm_info:
            alarm_id = self._extract_alarm_id(description)
            if alarm_id:
                inferred_region = self._infer_region_from_summary(summary_text)
                if inferred_region:
                    alarm_info = {
                        "alarm_region": inferred_region,
                        "alarm_id": alarm_id,
                        "alarm_url": f"{os.getenv('CORTEX_ALERT_SOURCE_HOST', '')}/monitoring/alarms/{inferred_region}/{alarm_id}",
                    }
        if alarm_info:
            enrichment.update(alarm_info)

            if self._should_enrich_alarm_status():
                reference = alarm_info.get("alarm_url") or alarm_info.get("alarm_id")
                if reference:
                    if self._has_operator_token():
                        status_payload = verification_service.check_reference(reference)
                        enrichment["alarm_status"] = status_payload.get("status")
                        enrichment["alarm_status_since"] = status_payload.get("timestamp")
                        if status_payload.get("error"):
                            enrichment["alarm_status_error"] = status_payload.get("error")
                    else:
                        enrichment["alarm_status"] = "Unknown"
                        enrichment["alarm_status_since"] = None
                        enrichment["alarm_status_error"] = "operator_token_missing"

        description_context = self._extract_ticket_description_context(description)
        if description_context:
            enrichment["ticket_description"] = description_context

        resolution = runbook_resolver.resolve(
            normalized_message=normalized_message,
            runbook_url=str(description_context.get("runbook_url") or ""),
            query_name=query_name,
            group_name=group,
        )
        enrichment["runbook_resolution"] = resolution
        runbook_ref_path = str(resolution.get("runbook_ref_path") or "")
        if resolution.get("runbook_id"):
            runbook_id = str(resolution["runbook_id"])
            enrichment["runbook_id"] = runbook_id
            enrichment["diagnostics_preview"] = diagnostics_planner.resolve_preview(runbook_id=runbook_id)
        else:
            enrichment["diagnostics_preview"] = diagnostics_planner.resolve_preview(runbook_id="")

        diagnostics_preview = enrichment.get("diagnostics_preview") if isinstance(enrichment.get("diagnostics_preview"), dict) else {}
        specific_steps = self._extract_runbook_mitigation_steps(runbook_ref_path)
        if specific_steps:
            enrichment["alert_specific_mitigation"] = {
                "title": "Alert-Specific Mitigation",
                "intent": "Use runbook mitigation steps tailored to this alert.",
                "steps": specific_steps,
                "steps_count": len(specific_steps),
                "source": "runbook_ref_markdown",
            }
        elif diagnostics_preview and str(diagnostics_preview.get("source") or "") == "plan":
            preview_steps = diagnostics_preview.get("steps") if isinstance(diagnostics_preview.get("steps"), list) else []
            preview_steps = [str(item).strip() for item in preview_steps if str(item).strip()]
            if preview_steps:
                enrichment["alert_specific_mitigation"] = {
                    "title": "Alert-Specific Mitigation",
                    "intent": "Use mapped mitigation guidance for this alert family.",
                    "steps": preview_steps,
                    "steps_count": len(preview_steps),
                    "source": "diagnostics_plan",
                }

        return enrichment

    def _verify_enrichment(self, enrichment: Dict[str, Any]) -> Dict[str, Any]:
        """Builds verify enrichment using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        execution = enrichment.get("diagnostics_execution") if isinstance(enrichment, dict) else {}
        execution_status = str((execution or {}).get("status") or "not_executed")
        alarm_status = str(enrichment.get("alarm_status") or "")
        alarm_reference = str(enrichment.get("alarm_url") or enrichment.get("alarm_id") or "").strip()
        checked_alarm = False
        alarm_check_error = ""

        if alarm_reference and self._has_operator_token():
            checked_alarm = True
            payload = verification_service.check_reference(alarm_reference)
            if payload.get("status"):
                alarm_status = str(payload.get("status"))
                enrichment["alarm_status"] = alarm_status
                enrichment["alarm_status_since"] = payload.get("timestamp")
            if payload.get("error"):
                alarm_check_error = str(payload.get("error"))

        workload_state = "unknown"
        if execution_status == "succeeded":
            workload_state = "healthy_candidate"
        elif execution_status == "partial":
            workload_state = "degraded"
        elif execution_status in {"failed", "blocked"}:
            workload_state = "unhealthy"
        elif execution_status in {"planned", "not_executed", "no_steps"}:
            workload_state = "not_executed"

        normalized_alarm = alarm_status.upper()
        resolution_status = "unresolved"
        if normalized_alarm == "OK":
            resolution_status = "resolved"
        elif not normalized_alarm and execution_status in {"succeeded", "partial"}:
            resolution_status = "partially_resolved"
        elif normalized_alarm in {"UNKNOWN", "UNAVAILABLE"} and execution_status in {"succeeded", "partial"}:
            resolution_status = "partially_resolved"

        return {
            "checked_alarm": checked_alarm,
            "alarm_status_after": alarm_status or "unknown",
            "alarm_check_error": alarm_check_error or None,
            "execution_status": execution_status,
            "workload_state": workload_state,
            "resolution_status": resolution_status,
            "checked_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }

    def _escalate_if_needed(
        self,
        *,
        ticket_key: str,
        summary_text: str,
        enrichment: Dict[str, Any],
        existing_escalation_ticket: str | None = None,
        policy_escalation_allowed: bool = True,
    ) -> Dict[str, Any]:
        """Builds escalate if needed using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if existing_escalation_ticket:
            return {"status": "already_created", "ticket_key": existing_escalation_ticket}
        verification = enrichment.get("verification") if isinstance(enrichment, dict) else {}
        if not isinstance(verification, dict) or not verification:
            return {"status": "skipped", "reason": "verification_unavailable"}
        resolution = str((verification or {}).get("resolution_status") or "unresolved")
        if resolution != "unresolved":
            return {"status": "not_needed", "reason": resolution}
        if not policy_escalation_allowed:
            return {"status": "policy_blocked", "reason": "escalation_action_blocked"}
        if not self._sev4_escalation_enabled():
            return {"status": "disabled"}

        window_started_raw = str(enrichment.get("escalation_window_started_at") or "")
        window_started = self._parse_iso_datetime(window_started_raw)
        if window_started is None:
            return {"status": "waiting_window", "reason": "window_start_missing"}
        elapsed = int((datetime.now(timezone.utc) - window_started).total_seconds())
        min_required = self._sev4_min_monitor_seconds()
        if elapsed < min_required:
            return {
                "status": "waiting_window",
                "reason": "min_monitor_window_not_reached",
                "elapsed_seconds": elapsed,
                "min_required_seconds": min_required,
            }

        jira_meta = enrichment.get("jira") if isinstance(enrichment.get("jira"), dict) else {}
        project_key = str(jira_meta.get("project_key") or "ODA").strip() or "ODA"
        runbook_id = str(enrichment.get("runbook_id") or "unresolved")
        execution = enrichment.get("diagnostics_execution") if isinstance(enrichment.get("diagnostics_execution"), dict) else {}
        verification_state = verification if isinstance(verification, dict) else {}
        alarm_url = str(enrichment.get("alarm_url") or "")
        alarm_id = str(enrichment.get("alarm_id") or "")
        ops_central_url = str(((enrichment.get("ticket_description") or {}).get("ops_central_url")) or "")
        escalation_summary = f"[SEV4][CORTEX] Unresolved auto-mitigation for {ticket_key}"
        escalation_body = "\n".join(
            [
                "Cortex-AI automated escalation (SEV-4).",
                "",
                f"Original Ticket: {ticket_key}",
                f"Original Summary: {summary_text}",
                f"Runbook ID: {runbook_id}",
                f"Diagnostics Execution Status: {execution.get('status') or 'not_executed'}",
                f"Verification Status: {verification_state.get('resolution_status') or 'unresolved'}",
                f"Alarm Status After: {verification_state.get('alarm_status_after') or 'unknown'}",
                f"Alarm URL: {alarm_url or 'n/a'}",
                f"Alarm ID: {alarm_id or 'n/a'}",
                f"Ops Central URL: {ops_central_url or 'n/a'}",
                "",
                "Suggested Next Actions:",
                "1. Validate workload health on impacted cluster/namespace.",
                "2. Validate alarm dimensions and recent events.",
                "3. Apply manual mitigation per runbook and monitor alarm reset.",
            ]
        )
        created = jira_api.create_issue(
            project_key=project_key,
            summary=escalation_summary,
            description=escalation_body,
            issue_type_name="Incident",
            labels=["cortex-ai-escalation", "sev4"],
        )
        if created.get("error"):
            return {"status": "failed", "error": created.get("error")}

        escalated_key = str(created.get("key") or "")
        if ticket_key:
            jira_api.add_comment(
                ticket_key,
                (
                    "[cortex-ai] Escalated unresolved incident to SEV-4.\n"
                    f"Escalation Ticket: {escalated_key}\n"
                    f"Runbook: {runbook_id}"
                ),
            )
        if escalated_key:
            jira_api.link_issues(ticket_key, escalated_key, link_type_name="Relates")
            jira_api.add_comment(
                escalated_key,
                (
                    "[cortex-ai] Linked source incident.\n"
                    f"Source Ticket: {ticket_key}\n"
                    f"Source Summary: {summary_text}"
                ),
            )
        return {"status": "created", "ticket_key": escalated_key, "project_key": project_key}

    @staticmethod
    def _existing_escalation_map(store: list[Dict[str, Any]]) -> Dict[str, str]:
        """Builds existing escalation map using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        out: Dict[str, str] = {}
        for item in store:
            if not isinstance(item, dict):
                continue
            source_ticket = str(item.get("key") or "").strip()
            if not source_ticket:
                continue
            context = item.get("context") if isinstance(item.get("context"), dict) else {}
            enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
            escalation = enrichment.get("escalation") if isinstance(enrichment.get("escalation"), dict) else {}
            if str(escalation.get("status") or "").strip() != "created":
                continue
            escalation_ticket = str(escalation.get("ticket_key") or "").strip()
            if escalation_ticket:
                out[source_ticket] = escalation_ticket
        return out

    def process_tickets(self, range_hours: int | None = None) -> Dict[str, Any]:
        """Processes tickets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        range_hours = range_hours if range_hours is not None else get_processing_range_hours()
        log("info", "[jira_processor] Starting run (range_hours=%s)", range_hours)

        assoc_cfg = load_association_config()
        try:
            policy_service.refresh()
        except Exception:
            pass
        msg_to_group = assoc_cfg.get("msg_to_group", {})
        labels_cfg = get_labels()
        during_label = (labels_cfg.get("during_processing") or "processing").lower()
        after_label = (labels_cfg.get("after_processing") or "processed").lower()

        created_since = checkpoint.read_last_run_iso()
        tickets = search_on_call_tickets(range_hours=range_hours, created_since=created_since)

        store = read_ticket_store()
        existing_escalations = self._existing_escalation_map(store)
        fetched_count = len([item for item in tickets if not (isinstance(item, dict) and "error" in item)])
        summary: Dict[str, Any] = {
            "fetched": fetched_count,
            "processing_added": [],
            "processing_skipped": [],
            "already_processed": [],
            "upserted": 0,
            "errors": [],
            "label_updates_enabled": self._should_update_labels(),
            "jira_mutations_enabled": self._jira_mutations_enabled(),
            "diagnostics_execute_enabled": self._should_execute_diagnostics(),
            "diagnostics_dry_run": self._diagnostics_dry_run(),
            "ticket_lifecycle_enabled": self._ticket_lifecycle_enabled(),
            "enriched": 0,
            "alarm_enriched": 0,
            "diagnostics_planned": 0,
            "diagnostics_executed": 0,
            "diagnostics_execute_failures": 0,
            "diagnostics_queued_realm_auth": 0,
            "lifecycle_comments_added": 0,
            "lifecycle_transition_attempted": 0,
            "lifecycle_transition_succeeded": 0,
            "lifecycle_errors": [],
            "verification_enabled": self._verification_enabled(),
            "verification_resolved": 0,
            "verification_partially_resolved": 0,
            "verification_unresolved": 0,
            "sev4_escalation_enabled": self._sev4_escalation_enabled(),
            "sev4_escalations_created": 0,
            "sev4_escalation_failed": 0,
            "sev4_escalation_already_created": 0,
            "sev4_escalation_waiting_window": 0,
            "sev4_escalation_policy_blocked": 0,
            "checkpoint_updated": False,
            "checkpoint_last_run_utc": checkpoint.read_last_run_iso(),
        }

        summary_lock = threading.Lock()
        ticket_budget = self._ticket_time_budget_seconds()
        workers = self._jira_worker_count()

        def _process_one_ticket(item: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
            started = datetime.now(timezone.utc)
            local_summary: Dict[str, Any] = {
                "errors": [],
                "processing_added": [],
                "processing_skipped": [],
                "already_processed": [],
                "upserted": 0,
                "enriched": 0,
                "alarm_enriched": 0,
                "diagnostics_planned": 0,
                "diagnostics_executed": 0,
                "diagnostics_execute_failures": 0,
                "diagnostics_queued_realm_auth": 0,
                "lifecycle_comments_added": 0,
                "lifecycle_transition_attempted": 0,
                "lifecycle_transition_succeeded": 0,
                "lifecycle_errors": [],
                "verification_resolved": 0,
                "verification_partially_resolved": 0,
                "verification_unresolved": 0,
                "sev4_escalations_created": 0,
                "sev4_escalation_failed": 0,
                "sev4_escalation_already_created": 0,
                "sev4_escalation_waiting_window": 0,
                "sev4_escalation_policy_blocked": 0,
            }

            if "error" in item:
                local_summary["errors"].append(item)
                return local_summary, None

            key = item.get("key")
            summary_text = item.get("summary") or ""
            labels = [label.lower() for label in item.get("labels", []) if isinstance(label, str)]
            ingest_status = "ingested"
            if after_label in labels:
                local_summary["already_processed"].append(key)
                ingest_status = "already_processed"

            if ingest_status != "already_processed" and during_label not in labels:
                if summary["label_updates_enabled"]:
                    jira_api.add_label(key, during_label)
                    local_summary["processing_added"].append(key)
                else:
                    local_summary["processing_skipped"].append(key)

            if ingest_status != "already_processed" and self._ticket_lifecycle_enabled() and key:
                start_comment = (
                    "[cortex-ai] Ticket claimed for automated diagnostics.\n"
                    f"Ticket: {key}\n"
                    "Lifecycle: processing_started\n"
                    f"Diagnostics execute enabled: {self._should_execute_diagnostics()}\n"
                    f"Diagnostics dry-run: {self._diagnostics_dry_run()}"
                )
                start_result = jira_api.add_comment(str(key), start_comment)
                if not start_result.get("error"):
                    local_summary["lifecycle_comments_added"] += 1
                else:
                    local_summary["lifecycle_errors"].append(
                        {"ticket": key, "step": "start_comment", "error": start_result.get("error")}
                    )
                transition_result = jira_api.transition_issue_by_name(str(key), "In Progress")
                local_summary["lifecycle_transition_attempted"] += 1
                if not transition_result.get("error"):
                    local_summary["lifecycle_transition_succeeded"] += 1
                else:
                    local_summary["lifecycle_errors"].append(
                        {"ticket": key, "step": "transition_in_progress", "error": transition_result.get("error")}
                    )

            parsed = parse_ticket_summary(summary_text)
            normalized_message = normalize_message(parsed["message"])
            group = msg_to_group.get(normalized_message)
            previous_entry = next((x for x in store if isinstance(x, dict) and x.get("key") == key), None)
            previous_enrichment = {}
            if isinstance(previous_entry, dict):
                prev_context = previous_entry.get("context") if isinstance(previous_entry.get("context"), dict) else {}
                previous_enrichment = prev_context.get("enrichment") if isinstance(prev_context.get("enrichment"), dict) else {}
            enrichment = self._build_enrichment(
                item=item,
                summary_text=summary_text,
                normalized_message=normalized_message,
                group=group or "",
            )
            policy_decision = policy_service.evaluate(
                service=(group or parsed.get("cluster") or "unknown"),
                tier="platform",
                environment=str(parsed.get("environment") or "unknown").lower(),
                severity="sev4",
                metric_name=None,
                candidate_actions=["restart_component", "escalate_incident"],
            )
            enrichment["policy_decision"] = {
                "policy_version": policy_decision.policy_version,
                "auto_mitigate": policy_decision.auto_mitigate,
                "escalation_required": policy_decision.escalation_required,
                "require_human_approval": policy_decision.require_human_approval,
                "allowed_actions": policy_decision.allowed_actions,
                "blocked_actions": policy_decision.blocked_actions,
            }
            can_run_mitigation = bool(policy_decision.auto_mitigate and "restart_component" in set(policy_decision.allowed_actions))
            if self._should_execute_diagnostics():
                if can_run_mitigation:
                    route = cluster_access_service.route_mitigation_by_realm(
                        realm=str(parsed.get("realm") or ""),
                        ticket_key=str(key or ""),
                        cluster=str(parsed.get("cluster") or ""),
                        summary=summary_text,
                    )
                    enrichment["mitigation_route"] = route
                    if str(route.get("decision") or "") == "queue":
                        enrichment["diagnostics_execution"] = {
                            "status": "queued_realm_auth_pending",
                            "reason": str(route.get("reason") or "realm_auth_not_ready"),
                            "realm": str(route.get("realm") or ""),
                            "queue_id": str(route.get("queue_id") or ""),
                            "execution_mode": "queued",
                        }
                        local_summary["diagnostics_queued_realm_auth"] += 1
                    else:
                        preview = enrichment.get("diagnostics_preview") if isinstance(enrichment, dict) else {}
                        execution = diagnostics_runner.execute_workflow(
                            preview=preview if isinstance(preview, dict) else {},
                            dry_run=self._diagnostics_dry_run(),
                            timeout_seconds=self._diagnostics_timeout_seconds(),
                            retries=self._diagnostics_retries(),
                            context={
                                "cluster": parsed.get("cluster"),
                                "region": parsed.get("airport_code"),
                                "environment": parsed.get("environment"),
                            },
                            allow_invasive=self._diagnostics_invasive_allowed(),
                        )
                        enrichment["diagnostics_execution"] = execution
                        local_summary["diagnostics_executed"] += 1
                        if execution.get("status") in {"failed", "blocked"}:
                            local_summary["diagnostics_execute_failures"] += 1
                        if key:
                            try:
                                runbook_id = str(enrichment.get("runbook_id") or "")
                                run_id = local_state_db.record_diagnostics_execution(
                                    ticket_key=str(key),
                                    runbook_id=runbook_id,
                                    payload=execution,
                                )
                                enrichment["diagnostics_run_id"] = run_id
                            except Exception as exc:
                                local_summary["errors"].append(
                                    {"source": "diagnostics_persistence", "ticket": key, "error": str(exc)}
                                )
                else:
                    enrichment["diagnostics_execution"] = {
                        "status": "policy_blocked",
                        "reason": "restart_component_blocked",
                        "execution_mode": "blocked",
                    }
                    local_summary["diagnostics_execute_failures"] += 1
            if self._verification_enabled():
                verification = self._verify_enrichment(enrichment)
                enrichment["verification"] = verification
                state = str(verification.get("resolution_status") or "unresolved")
                if state == "resolved":
                    local_summary["verification_resolved"] += 1
                elif state == "partially_resolved":
                    local_summary["verification_partially_resolved"] += 1
                else:
                    local_summary["verification_unresolved"] += 1
            verification_payload = enrichment.get("verification") if isinstance(enrichment.get("verification"), dict) else {}
            resolution_state = str(verification_payload.get("resolution_status") or "")
            if resolution_state == "unresolved":
                prior_window_start = str(previous_enrichment.get("escalation_window_started_at") or "").strip()
                if prior_window_start:
                    enrichment["escalation_window_started_at"] = prior_window_start
                else:
                    enrichment["escalation_window_started_at"] = (
                        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    )
            escalation = self._escalate_if_needed(
                ticket_key=str(key or ""),
                summary_text=summary_text,
                enrichment=enrichment,
                existing_escalation_ticket=existing_escalations.get(str(key or "")),
                policy_escalation_allowed=("escalate_incident" in set(policy_decision.allowed_actions)),
            )
            enrichment["escalation"] = escalation
            if escalation.get("status") == "created":
                local_summary["sev4_escalations_created"] += 1
                if key:
                    existing_escalations[str(key)] = str(escalation.get("ticket_key") or "")
            elif escalation.get("status") == "failed":
                local_summary["sev4_escalation_failed"] += 1
            elif escalation.get("status") == "already_created":
                local_summary["sev4_escalation_already_created"] += 1
            elif escalation.get("status") == "waiting_window":
                local_summary["sev4_escalation_waiting_window"] += 1
            elif escalation.get("status") == "policy_blocked":
                local_summary["sev4_escalation_policy_blocked"] += 1
            if ingest_status != "already_processed" and self._ticket_lifecycle_enabled() and key:
                execution_state = (enrichment.get("diagnostics_execution") or {}).get("status", "not_executed")
                completion_comment = (
                    "[cortex-ai] Diagnostics stage complete.\n"
                    f"Ticket: {key}\n"
                    f"Runbook: {enrichment.get('runbook_id') or 'unresolved'}\n"
                    f"Execution: {execution_state}\n"
                    "Lifecycle: processing_complete"
                )
                done_result = jira_api.add_comment(str(key), completion_comment)
                if not done_result.get("error"):
                    local_summary["lifecycle_comments_added"] += 1
                else:
                    local_summary["lifecycle_errors"].append(
                        {"ticket": key, "step": "completion_comment", "error": done_result.get("error")}
                    )
            parsed_with_enrichment = {**parsed, "normalized_message": normalized_message, "enrichment": enrichment}
            local_summary["enriched"] += 1
            if enrichment.get("alarm_id") or enrichment.get("alarm_status"):
                local_summary["alarm_enriched"] += 1
            if (enrichment.get("diagnostics_preview") or {}).get("steps_count"):
                local_summary["diagnostics_planned"] += 1

            entry = {
                "key": key,
                "summary": summary_text,
                "labels": labels,
                "context": parsed_with_enrichment,
                "group": group,
            }
            if ingest_status != "already_processed":
                local_summary["upserted"] += 1

            if key:
                local_state_db.upsert_jira_ticket(
                    ticket_key=str(key),
                    summary=summary_text,
                    labels=labels,
                    group_name=group,
                    context=parsed_with_enrichment,
                    ingest_status=ingest_status,
                )
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            if elapsed > ticket_budget:
                local_summary["errors"].append(
                    {
                        "source": "ticket_time_budget",
                        "ticket": key,
                        "elapsed_seconds": int(elapsed),
                        "max_seconds": ticket_budget,
                    }
                )
            return local_summary, {"entry": entry, "ingest_status": ingest_status}

        valid_items = [item for item in tickets if isinstance(item, dict)]
        if workers <= 1:
            for item in valid_items:
                local_summary, result = _process_one_ticket(item)
                for k, v in local_summary.items():
                    if isinstance(v, list):
                        summary[k].extend(v)
                    elif isinstance(v, int):
                        summary[k] += v
                if result and result.get("ingest_status") != "already_processed":
                    upsert_ticket(store, result["entry"])
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="jira-ticket") as pool:
                futures = [pool.submit(_process_one_ticket, item) for item in valid_items]
                for fut in as_completed(futures):
                    local_summary, result = fut.result()
                    with summary_lock:
                        for k, v in local_summary.items():
                            if isinstance(v, list):
                                summary[k].extend(v)
                            elif isinstance(v, int):
                                summary[k] += v
                    if result and result.get("ingest_status") != "already_processed":
                        with summary_lock:
                            upsert_ticket(store, result["entry"])
        write_ticket_store(store)
        if not summary["errors"]:
            summary["checkpoint_last_run_utc"] = checkpoint.write_checkpoint_now()
            summary["checkpoint_updated"] = True
        log("info", "[jira_processor] Run complete: %s", json.dumps(summary))
        return summary


jira_processor = JiraProcessor()
