"""Alert source puller — polls a configurable HTTP alert API and ingests signals into Sense."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import re

import requests

from ...core import get_logger
from ...schemas.signal import SignalContext, SignalIngestRequest, SignalMetric, SignalPayload
from ...store.local_db import local_state_db
from .operator_token import operator_token_manager
from ..sense import sense_service

logger = get_logger(__name__)

DEFAULT_ALERT_SOURCE_HOST = ""
from app.core.paths import config as _cfg, data as _dat
DEFAULT_TARGETS_PATH = _cfg("devops_portal_targets.json")
DEFAULT_CA_BUNDLE_CANDIDATES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
)
ALARM_URL_PATTERN = re.compile(r"/alarms/(?P<region>[^/]+)/(?P<alarm>[0-9a-fA-F-]{36})")


@dataclass(frozen=True)
class DevOpsTarget:
    """Provides DevOpsTarget behavior using local state or integrations and exposes structured outputs for callers."""
    name: str
    region: str
    account_id: str
    environment: str = "prod"
    service: str = "devops-portal"
    tier: str = "platform"
    enabled: bool = True
    labels: Dict[str, str] | None = None
    alarm_ids: List[str] | None = None


class DevOpsPortalPuller:
    """Provides DevOpsPortalPuller behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._session = requests.Session()

    def _operator_token(self) -> str:
        """Builds operator token using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        return operator_token_manager.get_token(auto_refresh=True).token

    def _verify_value(self) -> Any:
        """Builds verify value using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        bundle = (os.getenv("REQUESTS_CA_BUNDLE") or "").strip()
        if bundle:
            if Path(bundle).exists():
                return bundle
            logger.warning("REQUESTS_CA_BUNDLE path not found (%s); falling back to system CA", bundle)
        for candidate in DEFAULT_CA_BUNDLE_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return True

    def _base_host(self) -> str:
        """Builds base host using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        host = (os.getenv("HERON_ALERT_SOURCE_HOST") or os.getenv("HERON_DEVOPS_PORTAL_HOST") or DEFAULT_ALERT_SOURCE_HOST).strip().rstrip("/")
        return host or DEFAULT_ALERT_SOURCE_HOST

    def _request_timeout(self) -> int:
        """Builds request timeout using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        raw = os.getenv("HERON_DEVOPS_PORTAL_TIMEOUT_SECONDS", "20").strip()
        try:
            timeout = int(raw)
        except ValueError:
            timeout = 20
        return max(5, timeout)

    def _discover_from_jira_enabled(self) -> bool:
        """Builds discover from jira enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = (os.getenv("HERON_DEVOPS_PORTAL_DISCOVER_FROM_JIRA") or "true").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_iso(value: str | None) -> Optional[datetime]:
        """Parses iso using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _detected_at(status_item: Dict[str, Any]) -> datetime:
        """Builds detected at using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        candidates = (
            status_item.get("timestampTriggered"),
            status_item.get("timeUpdated"),
            status_item.get("timeCreated"),
        )
        for candidate in candidates:
            parsed = DevOpsPortalPuller._parse_iso(str(candidate) if candidate is not None else None)
            if parsed is not None:
                return parsed
        return datetime.now(timezone.utc)

    def _load_targets(self) -> List[DevOpsTarget]:
        """Loads targets using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        env_targets = (os.getenv("HERON_DEVOPS_PORTAL_TARGETS") or "").strip()
        if env_targets:
            payload = json.loads(env_targets)
        else:
            path = Path((os.getenv("HERON_DEVOPS_PORTAL_TARGETS_PATH") or DEFAULT_TARGETS_PATH).strip())
            if not path.exists():
                return []
            payload = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            return []
        targets_raw = payload.get("targets")
        if not isinstance(targets_raw, list):
            return []

        targets: List[DevOpsTarget] = []
        for item in targets_raw:
            if not isinstance(item, dict):
                continue
            region = str(item.get("region") or "").strip()
            account_id = str(item.get("account_id") or "").strip()
            if not region or not account_id:
                continue
            name = str(item.get("name") or f"{region}:{account_id[:12]}").strip()
            labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
            targets.append(
                DevOpsTarget(
                    name=name,
                    region=region,
                    account_id=account_id,
                    environment=str(item.get("environment") or "prod").strip() or "prod",
                    service=str(item.get("service") or "devops-portal").strip() or "devops-portal",
                    tier=str(item.get("tier") or "platform").strip() or "platform",
                    enabled=bool(item.get("enabled", True)),
                    labels={str(k): str(v) for k, v in labels.items()},
                    alarm_ids=[
                        str(value).strip()
                        for value in (item.get("alarm_ids") or [])
                        if isinstance(value, str) and str(value).strip()
                    ] or None,
                )
            )
        return [target for target in targets if target.enabled]

    def _alarm_detail_path(self, region: str, alarm_id: str) -> str:
        tpl = os.getenv("HERON_ALERT_SOURCE_ALARM_DETAIL_PATH", "/api/v1/{region}/alarms/{alarm_id}")
        return tpl.format(region=region, alarm_id=alarm_id)

    def _fetch_alarm_details(self, *, region: str, alarm_id: str, token: str) -> Dict[str, Any]:
        """Fetches alarm details using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        url = f"{self._base_host()}{self._alarm_detail_path(region, alarm_id)}"
        response = self._session.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=self._request_timeout(),
            verify=self._verify_value(),
        )
        response.raise_for_status()
        payload = response.json() if response.text else {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _extract_alarm_ref_from_url(url: str) -> Tuple[str, str]:
        """Extracts alarm ref from url using local state or integration calls and returns a tuple result (e.g., ()), may raise ValueError for bad input while dependency errors may bubble."""
        match = ALARM_URL_PATTERN.search(url or "")
        if not match:
            return "", ""
        return (match.group("region") or "").strip().lower(), (match.group("alarm") or "").strip()

    def discover_from_jira(self, *, max_refs: int = 5000, resolve_accounts: bool = True) -> Dict[str, Any]:
        """Builds discover from jira using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        refs = local_state_db.list_jira_alarm_references(limit=max_refs)
        if not refs:
            return {
                "references_total": 0,
                "references_with_alarm": 0,
                "targets_total": 0,
                "targets": [],
                "errors": [],
            }

        normalized_refs: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for ref in refs:
            region = str(ref.get("alarm_region") or "").strip().lower()
            alarm_id = str(ref.get("alarm_id") or "").strip()
            if not region or not alarm_id:
                from_url_region, from_url_alarm = self._extract_alarm_ref_from_url(str(ref.get("alarm_url") or ""))
                region = region or from_url_region
                alarm_id = alarm_id or from_url_alarm
            if not region or not alarm_id:
                continue
            key = (region, alarm_id)
            if key in seen:
                continue
            seen.add(key)
            normalized_refs.append({**ref, "alarm_region": region, "alarm_id": alarm_id})

        token = self._operator_token() if resolve_accounts else ""
        target_map: Dict[tuple[str, str], DevOpsTarget] = {}
        errors: List[Dict[str, Any]] = []

        for ref in normalized_refs:
            region = str(ref.get("alarm_region"))
            alarm_id = str(ref.get("alarm_id"))
            account = ""
            if resolve_accounts:
                try:
                    details = self._fetch_alarm_details(region=region, alarm_id=alarm_id, token=token)
                    account = str(details.get("accountId") or "").strip()
                except Exception as exc:
                    errors.append({"region": region, "alarm_id": alarm_id, "error": str(exc), "source": "alarm_details"})
            if not account:
                # keep discovery usable even when detail lookups fail
                account = f"unknown:{region}"
            key = (region, account)
            existing = target_map.get(key)
            if existing is None:
                target_map[key] = DevOpsTarget(
                    name=f"jira-{region}-{len(target_map)+1}",
                    region=region,
                    account_id=account,
                    environment="prod",
                    service="devops-portal",
                    tier="platform",
                    enabled=True,
                    labels={"source": "jira_discovery"},
                    alarm_ids=[alarm_id],
                )
            else:
                ids = list(existing.alarm_ids or [])
                if alarm_id not in ids:
                    ids.append(alarm_id)
                target_map[key] = DevOpsTarget(
                    name=existing.name,
                    region=existing.region,
                    account_id=existing.account_id,
                    environment=existing.environment,
                    service=existing.service,
                    tier=existing.tier,
                    enabled=existing.enabled,
                    labels=existing.labels,
                    alarm_ids=ids,
                )

        targets = list(target_map.values())
        return {
            "references_total": len(refs),
            "references_with_alarm": len(normalized_refs),
            "targets_total": len(targets),
            "targets": [
                {
                    "name": target.name,
                    "region": target.region,
                    "account_id": target.account_id,
                    "enabled": target.enabled,
                    "service": target.service,
                    "tier": target.tier,
                    "environment": target.environment,
                    "labels": target.labels or {},
                    "alarm_ids": target.alarm_ids or [],
                }
                for target in targets
            ],
            "errors": errors,
        }

    def _fetch_status_page(
        self,
        *,
        region: str,
        account_id: str,
        page: str | None,
        batch_size: int,
        token: str,
    ) -> Tuple[List[Dict[str, Any]], str | None]:
        """Fetches status page using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        params: Dict[str, str] = {"accountId": account_id}
        if page:
            params["page"] = page
        params["limit"] = str(max(1, batch_size))

        status_path_tpl = os.getenv("HERON_ALERT_SOURCE_STATUS_PATH", "/api/v1/{region}/alarms/status")
        url = f"{self._base_host()}{status_path_tpl.format(region=region)}"
        response = self._session.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=self._request_timeout(),
            verify=self._verify_value(),
        )
        response.raise_for_status()
        payload = response.json() if response.text else []
        items = payload if isinstance(payload, list) else []
        normalized = [item for item in items if isinstance(item, dict)]
        return normalized, response.headers.get("opc-next-page")

    @staticmethod
    def _build_signal(
        *,
        target: DevOpsTarget,
        status_item: Dict[str, Any],
        alarm_details: Dict[str, Any] | None = None,
    ) -> SignalPayload:
        """Builds signal using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        alarm_id = str(status_item.get("id") or "").strip()
        detected_at = DevOpsPortalPuller._detected_at(status_item)
        status_text = str(status_item.get("status") or "UNKNOWN").strip().upper()
        display_name = str(status_item.get("displayName") or status_item.get("name") or "").strip()
        summary = display_name or f"DevOps alarm {alarm_id or 'unknown'} status={status_text}"
        signal_id = f"devops-{alarm_id or 'unknown'}-{int(detected_at.timestamp())}"
        metric_value = 1.0 if status_text == "FIRING" else 0.0
        details = {
            "source": "devops_portal",
            "target": {
                "name": target.name,
                "region": target.region,
                "account_id": target.account_id,
            },
            "alarm": {
                "id": alarm_id,
                "name": display_name,
                "status": status_text,
                "severity": status_item.get("severity"),
                "namespace": status_item.get("namespace"),
                "resourceId": status_item.get("resourceId"),
                "timestampTriggered": status_item.get("timestampTriggered"),
            },
            "alarm_details": alarm_details or {},
            "raw": status_item,
        }
        return SignalPayload(
            signal_id=signal_id,
            type="metric",
            detected_at=detected_at,
            metric=SignalMetric(value=metric_value, unit="state", window_seconds=60),
            summary=summary,
            details=details,
        )

    def run(
        self,
        *,
        range_hours: int,
        batch_size: int,
        cursor: Dict[str, Any] | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Runs the request using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        targets = self._load_targets()
        discovery = {"references_with_alarm": 0, "targets_total": 0}
        if self._discover_from_jira_enabled():
            try:
                discovery = self.discover_from_jira(max_refs=max(1000, batch_size * 20), resolve_accounts=True)
                discovered_targets: List[DevOpsTarget] = []
                for item in discovery.get("targets", []):
                    if not isinstance(item, dict):
                        continue
                    account_id = str(item.get("account_id") or "")
                    if account_id.startswith("unknown:"):
                        continue
                    discovered_targets.append(
                        DevOpsTarget(
                            name=str(item.get("name") or "jira-discovered"),
                            region=str(item.get("region") or ""),
                            account_id=account_id,
                            environment=str(item.get("environment") or "prod"),
                            service=str(item.get("service") or "devops-portal"),
                            tier=str(item.get("tier") or "platform"),
                            enabled=bool(item.get("enabled", True)),
                            labels={str(k): str(v) for k, v in (item.get("labels") or {}).items()} if isinstance(item.get("labels"), dict) else {},
                            alarm_ids=[str(v) for v in (item.get("alarm_ids") or []) if isinstance(v, str)] or None,
                        )
                    )
                # Merge configured + discovered by region/account
                merged: Dict[tuple[str, str], DevOpsTarget] = {}
                for target in [*targets, *discovered_targets]:
                    key = (target.region, target.account_id)
                    existing = merged.get(key)
                    if existing is None:
                        merged[key] = target
                        continue
                    existing_ids = set(existing.alarm_ids or [])
                    next_ids = set(target.alarm_ids or [])
                    merged[key] = DevOpsTarget(
                        name=existing.name,
                        region=existing.region,
                        account_id=existing.account_id,
                        environment=existing.environment,
                        service=existing.service,
                        tier=existing.tier,
                        enabled=existing.enabled or target.enabled,
                        labels={**(existing.labels or {}), **(target.labels or {})},
                        alarm_ids=sorted(existing_ids | next_ids) or None,
                    )
                targets = list(merged.values())
            except Exception as exc:
                logger.warning("DevOps Jira discovery failed: %s", exc)

        if not targets:
            summary = {
                "targets_total": 0,
                "targets_polled": 0,
                "fetched": 0,
                "considered_new": 0,
                "submitted": 0,
                "accepted": 0,
                "dropped": 0,
                "errors": [],
                "status": "no_targets_configured",
                "jira_discovery": discovery,
            }
            next_cursor = {
                "last_run_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            }
            return summary, next_cursor

        now_utc = datetime.now(timezone.utc)
        fallback_since = now_utc - timedelta(hours=max(1, int(range_hours)))
        cursor_last_run = self._parse_iso((cursor or {}).get("last_run_utc"))
        since = cursor_last_run or fallback_since

        summary: Dict[str, Any] = {
            "targets_total": len(targets),
            "targets_polled": 0,
            "fetched": 0,
            "considered_new": 0,
            "submitted": 0,
            "accepted": 0,
            "dropped": 0,
            "errors": [],
            "since_utc": since.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "jira_discovery": discovery,
        }

        token_obj = operator_token_manager.get_token(auto_refresh=True)
        token = token_obj.token
        summary["operator_token_source"] = token_obj.source
        summary["operator_token_expires_at_utc"] = token_obj.expires_at_utc
        latest_seen = since
        alarm_details_cache: Dict[tuple[str, str], Dict[str, Any]] = {}
        alarm_details_errors: Dict[tuple[str, str], str] = {}

        for target in targets:
            summary["targets_polled"] += 1
            page: str | None = None
            target_signals: List[SignalPayload] = []
            target_alarm_filter = set(target.alarm_ids or [])
            try:
                while True:
                    rows, page = self._fetch_status_page(
                        region=target.region,
                        account_id=target.account_id,
                        page=page,
                        batch_size=batch_size,
                        token=token,
                    )
                    summary["fetched"] += len(rows)
                    for row in rows:
                        alarm_id = str(row.get("id") or "").strip()
                        if target_alarm_filter and alarm_id and alarm_id not in target_alarm_filter:
                            continue
                        detected_at = self._detected_at(row)
                        if detected_at <= since:
                            continue
                        summary["considered_new"] += 1
                        if detected_at > latest_seen:
                            latest_seen = detected_at
                        alarm_details: Dict[str, Any] = {}
                        if alarm_id:
                            cache_key = (target.region, alarm_id)
                            if cache_key in alarm_details_cache:
                                alarm_details = alarm_details_cache[cache_key]
                            elif cache_key not in alarm_details_errors:
                                try:
                                    alarm_details = self._fetch_alarm_details(
                                        region=target.region,
                                        alarm_id=alarm_id,
                                        token=token,
                                    )
                                    alarm_details_cache[cache_key] = alarm_details
                                except Exception as exc:
                                    alarm_details_errors[cache_key] = str(exc)
                                    summary["errors"].append(
                                        {
                                            "source": "alarm_details",
                                            "target": target.name,
                                            "region": target.region,
                                            "alarm_id": alarm_id,
                                            "error": str(exc),
                                        }
                                    )
                        target_signals.append(self._build_signal(target=target, status_item=row, alarm_details=alarm_details))
                    if not page:
                        break
            except Exception as exc:
                summary["errors"].append(
                    {
                        "source": "devops_portal",
                        "target": target.name,
                        "region": target.region,
                        "error": str(exc),
                    }
                )
                continue

            if not target_signals:
                continue

            try:
                context = SignalContext(
                    service=target.service,
                    tier=target.tier,  # type: ignore[arg-type]
                    environment=target.environment,  # type: ignore[arg-type]
                    region=target.region,
                    component=target.name,
                    labels=target.labels or {},
                )
                request = SignalIngestRequest(
                    source="devops-portal",
                    context=context,
                    signals=target_signals,
                )
                result = sense_service.ingest(request, token=None)
                summary["submitted"] += len(target_signals)
                summary["accepted"] += int(result.accepted)
                summary["dropped"] += int(result.dropped)
            except Exception as exc:
                summary["errors"].append(
                    {
                        "source": "sense_ingest",
                        "target": target.name,
                        "region": target.region,
                        "error": str(exc),
                    }
                )

        checkpoint = now_utc if latest_seen <= since else latest_seen
        cursor_out = {
            "last_run_utc": checkpoint.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        summary["checkpoint_updated"] = True
        summary["checkpoint_last_run_utc"] = cursor_out["last_run_utc"]
        return summary, cursor_out