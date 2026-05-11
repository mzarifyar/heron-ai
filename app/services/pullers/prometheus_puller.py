"""Prometheus / Alertmanager puller — implements AlertSourceAdapter.

Pulls firing alerts from Alertmanager and optionally scrapes metric values
from Prometheus, converting both into Heron SignalPayload format for the
full autonomous loop: Sense → Insight → Decide → Act → Verify → Learn.

Setup (.env):
    PROMETHEUS_ALERTMANAGER_URL = http://alertmanager:9093
    PROMETHEUS_URL              = http://prometheus:9090   (optional — for metric scraping)
    PROMETHEUS_AUTH_TOKEN       = Bearer token             (optional)
    PROMETHEUS_BASIC_USER       = username                 (optional, alternative to token)
    PROMETHEUS_BASIC_PASS       = password                 (optional)
    PROMETHEUS_INSECURE_TLS     = false                    (set true to skip cert verify)
    PROMETHEUS_TIMEOUT_SECONDS  = 20

Activate in config/pullers.yaml:
    sources:
      prometheus:
        enabled: true
        interval_seconds: 30
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import requests

from ...core import get_logger
from ...schemas.signal import SignalContext, SignalIngestRequest, SignalMetric, SignalPayload
from ..sense import sense_service
from .alert_source import AlertSourceAdapter, AlertSourceResult

logger = get_logger(__name__)

# ── Severity mapping ────────────────────────────────────────────────────────
# Prometheus/Alertmanager severity labels → Heron severity
_SEV_MAP: Dict[str, str] = {
    "critical": "sev1",
    "page":     "sev1",
    "high":     "sev2",
    "error":    "sev2",
    "warning":  "sev3",
    "warn":     "sev3",
    "info":     "sev4",
    "none":     "sev4",
}

# Labels that map to Heron context fields
_SERVICE_LABELS  = ("service", "app", "application", "job", "container", "deployment")
_REGION_LABELS   = ("region", "zone", "availability_zone", "cluster_region")
_ENV_LABELS      = ("environment", "env", "stage", "namespace")

# Metrics to scrape from Prometheus (when PROMETHEUS_URL is set)
# Format: (heron_metric_name, promql_expression, extract_label_for_service)
_DEFAULT_METRIC_QUERIES: List[Tuple[str, str, str]] = [
    (
        "error_rate",
        'sum(rate(http_requests_total{status=~"5.."}[5m])) by (service, job) '
        '/ sum(rate(http_requests_total[5m])) by (service, job)',
        "service",
    ),
    (
        "latency_p99_ms",
        'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service, job)) * 1000',
        "service",
    ),
    (
        "cpu_utilization",
        '1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance, job)',
        "job",
    ),
    (
        "memory_utilization",
        '1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)',
        "job",
    ),
]


class PrometheusAlertmanagerPuller(AlertSourceAdapter):
    """Pulls alerts from Alertmanager + metrics from Prometheus."""

    # ── AlertSourceAdapter interface ────────────────────────────────────────

    @property
    def source_name(self) -> str:
        return "prometheus"

    def is_configured(self) -> bool:
        return bool(
            os.getenv("PROMETHEUS_ALERTMANAGER_URL", "").strip()
            or os.getenv("PROMETHEUS_URL", "").strip()
        )

    def pull(
        self,
        *,
        range_hours: int,
        batch_size: int,
        cursor: Dict[str, Any] | None,
    ) -> AlertSourceResult:
        """Fetch alerts and metrics, return as SignalPayload list."""
        signals: List[SignalPayload] = []
        errors: List[Dict[str, Any]] = []

        # Pull Alertmanager firing alerts
        am_url = os.getenv("PROMETHEUS_ALERTMANAGER_URL", "").strip().rstrip("/")
        if am_url:
            try:
                new_signals, am_errors = self._pull_alertmanager(am_url)
                signals.extend(new_signals)
                errors.extend(am_errors)
            except Exception as exc:
                errors.append({"source": "alertmanager", "error": str(exc)})
                logger.warning("Alertmanager pull failed: %s", exc)

        # Scrape Prometheus metric values
        prom_url = os.getenv("PROMETHEUS_URL", "").strip().rstrip("/")
        if prom_url:
            try:
                new_signals, prom_errors = self._scrape_prometheus(prom_url)
                signals.extend(new_signals)
                errors.extend(prom_errors)
            except Exception as exc:
                errors.append({"source": "prometheus", "error": str(exc)})
                logger.warning("Prometheus scrape failed: %s", exc)

        return AlertSourceResult(
            signals=signals[:batch_size],
            next_cursor={"last_run_utc": datetime.now(timezone.utc).isoformat()},
            errors=errors,
            metadata={"total_signals": len(signals)},
        )

    # ── Alertmanager ────────────────────────────────────────────────────────

    def _pull_alertmanager(self, base_url: str) -> Tuple[List[SignalPayload], List[Dict]]:
        """GET /api/v2/alerts and convert firing alerts to signals."""
        url = f"{base_url}/api/v2/alerts"
        resp = self._session().get(
            url,
            params={"active": "true", "inhibited": "false", "silenced": "false"},
            timeout=self._timeout(),
        )
        resp.raise_for_status()
        alerts: List[Dict[str, Any]] = resp.json() if resp.text else []

        signals = []
        for alert in alerts:
            try:
                sig = self._alert_to_signal(alert)
                if sig:
                    signals.append(sig)
            except Exception as exc:
                logger.debug("Alertmanager alert parse error: %s — %s", exc, alert)

        logger.info("Alertmanager: %d firing alerts → %d signals", len(alerts), len(signals))
        return signals, []

    def _alert_to_signal(self, alert: Dict[str, Any]) -> Optional[SignalPayload]:
        """Convert one Alertmanager alert into a SignalPayload."""
        labels      = alert.get("labels", {}) or {}
        annotations = alert.get("annotations", {}) or {}
        status      = alert.get("status", {}) or {}
        fingerprint = alert.get("fingerprint", str(uuid4()))

        if status.get("state") != "active":
            return None

        alert_name = labels.get("alertname", "unknown_alert")
        service    = self._extract_label(labels, _SERVICE_LABELS) or alert_name
        region     = self._extract_label(labels, _REGION_LABELS)  or "unknown"
        env        = self._extract_label(labels, _ENV_LABELS)     or "prod"
        prom_sev   = labels.get("severity", labels.get("level", "warning")).lower()
        heron_sev  = _SEV_MAP.get(prom_sev, "sev3")

        summary = (
            annotations.get("summary")
            or annotations.get("message")
            or annotations.get("description", "")[:200]
            or f"{alert_name} firing on {service}"
        )

        starts_at = self._parse_ts(alert.get("startsAt"))
        signal_id = f"prom-{fingerprint}"

        return SignalPayload(
            signal_id=signal_id,
            type="event",
            detected_at=starts_at,
            summary=summary,
            details={
                "metric_name": _normalise_metric_name(alert_name),
                "severity": heron_sev,
                "threshold": 0,
                "observed": 1,
                "alertname": alert_name,
                "labels": labels,
                "annotations": {k: v[:500] for k, v in annotations.items()},
                "fingerprint": fingerprint,
                "source": "alertmanager",
            },
        )

    # ── Prometheus metric scraping ──────────────────────────────────────────

    def _scrape_prometheus(self, base_url: str) -> Tuple[List[SignalPayload], List[Dict]]:
        """Query Prometheus for Golden Signal metrics."""
        signals = []
        errors  = []
        custom_queries = self._custom_metric_queries()
        all_queries    = _DEFAULT_METRIC_QUERIES + custom_queries

        for metric_name, promql, service_label in all_queries:
            try:
                results = self._instant_query(base_url, promql)
                for r in results:
                    sig = self._metric_result_to_signal(
                        r, metric_name=metric_name, service_label=service_label
                    )
                    if sig:
                        signals.append(sig)
            except Exception as exc:
                errors.append({"metric": metric_name, "error": str(exc)})
                logger.debug("Prometheus query failed for %s: %s", metric_name, exc)

        logger.info("Prometheus: scraped %d metric signals", len(signals))
        return signals, errors

    def _instant_query(self, base_url: str, promql: str) -> List[Dict]:
        url = f"{base_url}/api/v1/query"
        resp = self._session().get(url, params={"query": promql}, timeout=self._timeout())
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"Prometheus query error: {body.get('error', 'unknown')}")
        return body.get("data", {}).get("result", [])

    def _metric_result_to_signal(
        self,
        result: Dict[str, Any],
        *,
        metric_name: str,
        service_label: str,
    ) -> Optional[SignalPayload]:
        metric  = result.get("metric", {})
        value_v = result.get("value")      # [timestamp, "value_string"]

        if not value_v or len(value_v) < 2:
            return None

        try:
            value = float(value_v[1])
        except (ValueError, TypeError):
            return None

        if value != value:  # NaN check
            return None

        service = (
            metric.get(service_label)
            or self._extract_label(metric, _SERVICE_LABELS)
            or "unknown"
        )
        region = self._extract_label(metric, _REGION_LABELS) or "unknown"
        env    = self._extract_label(metric, _ENV_LABELS)    or "prod"
        ts_raw = value_v[0]
        ts     = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc) if ts_raw else datetime.now(timezone.utc)

        return SignalPayload(
            signal_id=f"prom-{metric_name}-{service}-{int(ts.timestamp())}",
            type="metric",
            detected_at=ts,
            summary=f"{metric_name}={value:.4f} on {service}",
            metric=SignalMetric(
                value=value,
                unit=_metric_unit(metric_name),
                window_seconds=300,
            ),
            details={
                "metric_name": metric_name,
                "severity": "info",
                "threshold": 0,
                "observed": value,
                "labels": metric,
                "source": "prometheus",
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _session(self) -> requests.Session:
        s = requests.Session()
        token = os.getenv("PROMETHEUS_AUTH_TOKEN", "").strip()
        user  = os.getenv("PROMETHEUS_BASIC_USER", "").strip()
        pw    = os.getenv("PROMETHEUS_BASIC_PASS", "").strip()
        if token:
            s.headers["Authorization"] = f"Bearer {token}"
        elif user:
            s.auth = (user, pw)
        insecure = os.getenv("PROMETHEUS_INSECURE_TLS", "false").lower() in {"1", "true", "yes"}
        s.verify = not insecure
        return s

    def _timeout(self) -> int:
        try:
            return max(5, int(os.getenv("PROMETHEUS_TIMEOUT_SECONDS", "20")))
        except ValueError:
            return 20

    def _custom_metric_queries(self) -> List[Tuple[str, str, str]]:
        """Load additional PromQL queries from PROMETHEUS_EXTRA_QUERIES env var.

        Format: comma-separated "metric_name:promql:service_label" triples.
        Example:
          PROMETHEUS_EXTRA_QUERIES=kafka_lag:kafka_consumer_group_lag:job,redis_hit:redis_keyspace_hits_total:job
        """
        raw = os.getenv("PROMETHEUS_EXTRA_QUERIES", "").strip()
        if not raw:
            return []
        result = []
        for triple in raw.split(","):
            parts = triple.strip().split(":", 2)
            if len(parts) == 3:
                result.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
        return result

    @staticmethod
    def _extract_label(labels: Dict[str, str], keys: tuple) -> Optional[str]:
        for key in keys:
            val = labels.get(key, "").strip()
            if val:
                return val
        return None

    @staticmethod
    def _parse_ts(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            text = value.replace("Z", "+00:00")
            return datetime.fromisoformat(text).astimezone(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)


# ── Module-level helpers ────────────────────────────────────────────────────

def _normalise_metric_name(alert_name: str) -> str:
    """Convert AlertName → metric_name format (e.g. HighErrorRate → error_rate)."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", alert_name)
    s = re.sub(r"[^a-z0-9_]", "_", s.lower())
    return re.sub(r"_+", "_", s).strip("_")


def _metric_unit(metric_name: str) -> str:
    if "latency" in metric_name or "_ms" in metric_name:
        return "ms"
    if "rate" in metric_name or "utilization" in metric_name:
        return "ratio"
    if "rps" in metric_name or "rate_rps" in metric_name:
        return "rps"
    return "count"


prometheus_puller = PrometheusAlertmanagerPuller()
