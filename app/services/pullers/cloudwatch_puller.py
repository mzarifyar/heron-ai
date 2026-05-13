"""CloudWatch alert puller — implements AlertSourceAdapter for AWS.

Pulls firing CloudWatch Alarms and AWS Health events, converting them into
Heron SignalPayload format for the autonomous loop.

Setup (.env):
    AWS_REGION              = us-east-1
    AWS_ACCESS_KEY_ID       = ...   (or use EC2 instance profile — no keys needed)
    AWS_SECRET_ACCESS_KEY   = ...
    CLOUDWATCH_NAMESPACES   = AWS/EC2,AWS/RDS,AWS/EKS   (optional filter)

Activate in config/pullers.yaml:
    sources:
      cloudwatch:
        enabled: true
        interval_seconds: 60
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ...core import get_logger
from ...schemas.signal import SignalContext, SignalIngestRequest, SignalMetric, SignalPayload
from .alert_source import AlertSourceAdapter, AlertSourceResult

logger = get_logger(__name__)

_SEV_MAP = {
    "CRITICAL": "sev1",
    "HIGH":     "sev2",
    "MEDIUM":   "sev2",
    "WARNING":  "sev3",
    "LOW":      "sev3",
    "INFO":     "sev4",
}

_ALARM_STATE_SEV = {
    "ALARM":            "sev2",
    "INSUFFICIENT_DATA":"sev3",
    "OK":               "info",
}


def _boto3_client(service: str):
    try:
        import boto3  # type: ignore
        region = os.getenv("AWS_REGION", "us-east-1")
        return boto3.client(service, region_name=region)
    except ImportError:
        raise RuntimeError("boto3 not installed. Run: pip install boto3")


def _normalise_metric(name: str) -> str:
    import re
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^a-z0-9_]", "_", s.lower()).strip("_")


class CloudWatchPuller(AlertSourceAdapter):
    """Pulls CloudWatch Alarms and AWS Health events."""

    @property
    def source_name(self) -> str:
        return "cloudwatch"

    def is_configured(self) -> bool:
        # boto3 auto-discovers credentials via instance profile, env vars, ~/.aws/credentials
        try:
            import boto3  # type: ignore
            return True
        except ImportError:
            return False

    def pull(
        self,
        *,
        range_hours: int,
        batch_size: int,
        cursor: Dict[str, Any] | None,
    ) -> AlertSourceResult:
        signals: List[SignalPayload] = []
        errors: List[Dict[str, Any]] = []

        # CloudWatch Alarms (ALARM state only)
        try:
            cw_signals, cw_errors = self._pull_alarms(batch_size)
            signals.extend(cw_signals)
            errors.extend(cw_errors)
        except Exception as exc:
            errors.append({"source": "cloudwatch_alarms", "error": str(exc)})
            logger.warning("CloudWatch alarms pull failed: %s", exc)

        # AWS Health events (active)
        try:
            health_signals, health_errors = self._pull_health_events()
            signals.extend(health_signals)
            errors.extend(health_errors)
        except Exception as exc:
            errors.append({"source": "aws_health", "error": str(exc)})
            logger.debug("AWS Health pull failed (may not be subscribed): %s", exc)

        return AlertSourceResult(
            signals=signals[:batch_size],
            next_cursor={"last_run_utc": datetime.now(timezone.utc).isoformat()},
            errors=errors,
            metadata={"total_signals": len(signals)},
        )

    # ── CloudWatch Alarms ─────────────────────────────────────────────────

    def _pull_alarms(self, batch_size: int):
        cw = _boto3_client("cloudwatch")
        paginator = cw.get_paginator("describe_alarms")
        signals = []
        namespaces_filter = [
            ns.strip()
            for ns in os.getenv("CLOUDWATCH_NAMESPACES", "").split(",")
            if ns.strip()
        ]

        for page in paginator.paginate(StateValue="ALARM", MaxRecords=min(batch_size, 100)):
            for alarm in page.get("MetricAlarms", []):
                ns = alarm.get("Namespace", "")
                if namespaces_filter and ns not in namespaces_filter:
                    continue
                sig = self._alarm_to_signal(alarm)
                if sig:
                    signals.append(sig)

        logger.info("CloudWatch: %d firing alarms ingested", len(signals))
        return signals, []

    def _alarm_to_signal(self, alarm: Dict[str, Any]) -> Optional[SignalPayload]:
        name       = alarm.get("AlarmName", "unknown")
        namespace  = alarm.get("Namespace", "unknown")
        metric     = alarm.get("MetricName", "unknown")
        dims       = {d["Name"]: d["Value"] for d in alarm.get("Dimensions", [])}
        state      = alarm.get("StateValue", "ALARM")
        reason     = alarm.get("StateReason", "")
        threshold  = float(alarm.get("Threshold", 0) or 0)
        statistic  = alarm.get("Statistic", "")

        # Derive service name from dimensions (InstanceId, DBInstanceIdentifier, etc.)
        service = (
            dims.get("ServiceName")
            or dims.get("service")
            or dims.get("ClusterName")
            or dims.get("DBInstanceIdentifier")
            or dims.get("FunctionName")
            or namespace.split("/")[-1].lower().replace(" ", "_")
        )
        region = os.getenv("AWS_REGION", "unknown")
        severity = _ALARM_STATE_SEV.get(state, "sev3")

        return SignalPayload(
            signal_id=f"cw-{alarm.get('AlarmArn', uuid4().hex)[-20:]}",
            type="event",
            detected_at=datetime.now(timezone.utc).replace(tzinfo=None),
            summary=f"{name}: {reason[:200]}",
            details={
                "metric_name": _normalise_metric(metric),
                "severity": severity,
                "threshold": threshold,
                "observed": 0,
                "namespace": namespace,
                "dimensions": dims,
                "state": state,
                "statistic": statistic,
                "alarm_name": name,
                "source": "cloudwatch",
            },
        )

    # ── AWS Health ────────────────────────────────────────────────────────

    def _pull_health_events(self):
        health = _boto3_client("health")
        paginator = health.get_paginator("describe_events")
        signals = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for page in paginator.paginate(
            filter={"eventStatusCodes": ["open", "upcoming"]},
            PaginationConfig={"MaxItems": 50},
        ):
            for event in page.get("events", []):
                svc    = event.get("service", "aws").lower()
                region = event.get("region", "global")
                etype  = event.get("eventTypeCode", "")
                status = event.get("statusCode", "open")
                start  = event.get("startTime")
                signals.append(SignalPayload(
                    signal_id=f"health-{event.get('arn', uuid4().hex)[-20:]}",
                    type="event",
                    detected_at=start if isinstance(start, datetime) else now,
                    summary=f"AWS Health: {etype} affecting {svc} in {region}",
                    details={
                        "metric_name": "aws_health_event",
                        "severity": "sev2" if status == "open" else "sev3",
                        "threshold": 0,
                        "observed": 1,
                        "service": svc,
                        "region": region,
                        "event_type": etype,
                        "status": status,
                        "source": "aws_health",
                    },
                ))

        logger.info("AWS Health: %d active events ingested", len(signals))
        return signals, []


cloudwatch_puller = CloudWatchPuller()
