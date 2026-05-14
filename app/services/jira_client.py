"""Jira search helpers ported from the legacy Heron processor.

Provides the `search_on_call_tickets` function that wraps the shared Jira
integration with project-specific JQL and pagination settings.

"""
from __future__ import annotations
from app.core.paths import config as _cfg

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import re

from app.integrations import jira as jira_api
from utils.settings import get_jira_max_results, get_search_jql_base, get_search_jql_bases

__all__ = ["search_on_call_tickets"]

ORDER_BY_RE = re.compile(r"\border\s+by\b.*$", re.IGNORECASE)


def _strip_order_by(jql: str) -> str:
    """Builds strip order by using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return ORDER_BY_RE.sub("", jql).strip()


def _dedupe_queries(queries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Builds dedupe queries using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    deduped: List[Dict[str, str]] = []
    seen: set[str] = set()
    for query in queries:
        jql = query.get("jql", "").strip()
        if not jql:
            continue
        key = " ".join(_strip_order_by(jql).lower().split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"name": query.get("name", "query"), "jql": _strip_order_by(jql)})
    return deduped


def _load_query_file(path: Path = Path(_cfg("jira_queries.json"))) -> List[Dict[str, str]]:
    """Loads query file using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("queries")
    if not isinstance(entries, list):
        return []

    results: List[Dict[str, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        if item.get("enabled") is False:
            continue
        if item.get("kind") not in (None, "inline"):
            continue
        jql = item.get("jql")
        if not isinstance(jql, str) or not jql.strip():
            continue
        name = item.get("name") if isinstance(item.get("name"), str) else "query"
        results.append({"name": name, "jql": jql.strip()})
    return results


def _resolve_queries(jql_base: Optional[str] = None) -> List[Dict[str, str]]:
    """Resolves queries using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if jql_base and jql_base.strip():
        return [{"name": "override", "jql": jql_base.strip()}]

    settings_queries = [{"name": "settings", "jql": value} for value in get_search_jql_bases() if value.strip()]
    file_queries = _load_query_file()
    if not settings_queries and not file_queries:
        fallback = get_search_jql_base().strip()
        if fallback:
            settings_queries = [{"name": "settings", "jql": fallback}]
    return _dedupe_queries([*settings_queries, *file_queries])


def _parse_checkpoint_timestamp(raw: str) -> Optional[datetime]:
    """Parses checkpoint timestamp using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        # Backward compatibility for old checkpoint format ("YYYY-MM-DD HH:MM").
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
        return parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _build_created_clause(range_hours: int, created_since: Optional[str]) -> str:
    """Builds updated-time clause for incremental polling and returns a JQL clause string."""
    if not created_since:
        return f"AND updated >= -{range_hours}h"

    parsed = _parse_checkpoint_timestamp(created_since)
    if parsed is None:
        # Preserve behavior for unexpected persisted values.
        return f'AND updated >= "{created_since}"'

    now_utc = datetime.now(timezone.utc)
    delta_seconds = (now_utc - parsed.astimezone(timezone.utc)).total_seconds()
    # Keep a small overlap to avoid edge drops around scheduler tick boundaries.
    checkpoint_minutes = max(1, int(delta_seconds // 60) + 2)
    # Keep at least the configured window to catch status-only updates on older tickets.
    lookback_minutes = max(checkpoint_minutes, max(1, int(range_hours)) * 60)
    return f"AND updated >= -{lookback_minutes}m"


def _safe_name(obj: Any) -> str:
    """Builds safe name using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    if isinstance(obj, dict):
        val = obj.get("displayName") or obj.get("name") or obj.get("key")
        return str(val) if val is not None else ""
    return ""


def _safe_list_names(values: Any) -> List[str]:
    """Builds safe list names using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
    if not isinstance(values, list):
        return []
    names: List[str] = []
    for item in values:
        name = _safe_name(item)
        if name:
            names.append(name)
    return names


def search_on_call_tickets(
    range_hours: int,
    created_since: Optional[str] = None,
    max_results: Optional[int] = None,
    jql_base: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Builds search on call tickets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    actual_max_results = max_results if max_results is not None else get_jira_max_results()
    queries = _resolve_queries(jql_base=jql_base)

    results: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    for query in queries:
        created_clause = _build_created_clause(range_hours=range_hours, created_since=created_since)
        jql = f'{query["jql"]} {created_clause} ORDER BY updated DESC'

        issues = jira_api.search_issues(
            jql=jql,
            fields=(
                "key,summary,labels,status,created,updated,description,"
                "assignee,reporter,priority,issuetype,project,components,resolution,resolutiondate"
            ),
            max_results=actual_max_results,
        )
        if issues and isinstance(issues[0], dict) and "error" in issues[0]:
            results.append(
                {
                    "error": issues[0]["error"],
                    "source": "search_issues",
                    "query_name": query["name"],
                    "jql": query["jql"],
                }
            )
            continue

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            key = issue.get("key")
            if isinstance(key, str) and key in seen_keys:
                continue
            if isinstance(key, str):
                seen_keys.add(key)
            fields = issue.get("fields") or {}
            project = fields.get("project") if isinstance(fields.get("project"), dict) else {}
            status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
            priority = fields.get("priority") if isinstance(fields.get("priority"), dict) else {}
            issue_type = fields.get("issuetype") if isinstance(fields.get("issuetype"), dict) else {}
            resolution = fields.get("resolution") if isinstance(fields.get("resolution"), dict) else {}
            results.append(
                {
                    "key": key,
                    "summary": fields.get("summary"),
                    "labels": fields.get("labels", []),
                    "status_before": status.get("name", ""),
                    "status_category": ((status.get("statusCategory") or {}).get("name") if isinstance(status.get("statusCategory"), dict) else ""),
                    "created_utc": fields.get("created"),
                    "updated_utc": fields.get("updated"),
                    "description": fields.get("description") or "",
                    "assignee": _safe_name(fields.get("assignee")),
                    "reporter": _safe_name(fields.get("reporter")),
                    "priority": priority.get("name", ""),
                    "issue_type": issue_type.get("name", ""),
                    "project_key": project.get("key", ""),
                    "project_name": project.get("name", ""),
                    "components": _safe_list_names(fields.get("components")),
                    "resolution": resolution.get("name", ""),
                    "resolution_date_utc": fields.get("resolutiondate"),
                    "query_name": query["name"],
                }
            )
    return results
