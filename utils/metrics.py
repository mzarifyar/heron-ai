"""Telemetry helpers for consistently labeled Cortex metrics."""
from __future__ import annotations

from typing import Optional

from app.integrations.telemetry import log_latency, log_saturation, log_throughput


def _label(value: Optional[str], fallback: str) -> str:
    """Builds label using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return value or fallback


def _bool(value: bool) -> str:
    """Builds bool using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return "yes" if value else "no"


def emit_alarm_processed(mode: str, path: str, matched: bool) -> None:
    """Emits alarm processed using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_alarm_processed_count",
        1,
        module="processor",
        mode=_label(mode, "unknown"),
        path=_label(path, "unspecified"),
        matched=_bool(matched),
    )


def emit_alarm_processing_latency(mode: str, stage: str, latency_ms: float) -> None:
    """Emits alarm processing latency using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_latency(
        "cortex_alarm_processing_latency_ms",
        latency_ms,
        module="processor",
        mode=_label(mode, "unknown"),
        stage=_label(stage, "general"),
    )


def emit_alarm_flow_latency(mode: str, stage: str, latency_ms: float) -> None:
    """Emits alarm flow latency using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_latency(
        "cortex_alarm_flow_latency_ms",
        latency_ms,
        module="processor",
        mode=_label(mode, "unknown"),
        stage=_label(stage, "general"),
    )


def emit_backlog_size(mode: str, size: int) -> None:
    """Emits backlog size using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_saturation(
        "cortex_alarm_backlog_size",
        float(max(size, 0)),
        module="processor",
        mode=_label(mode, "unknown"),
    )


def emit_circuit_breaker_plan(
    mode: str,
    limit: Optional[int],
    normal_count: int,
    overflow_count: int,
) -> None:
    """Emits circuit breaker plan using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    limit_str = str(limit) if limit is not None else None
    log_throughput(
        "cortex_circuit_breaker_plan_count",
        1,
        module="processor",
        mode=_label(mode, "unknown"),
        limit=_label(limit_str, "none"),
        activated=_bool(overflow_count > 0),
    )
    if overflow_count > 0:
        log_throughput(
            "cortex_circuit_breaker_activated_count",
            1,
            module="processor",
            mode=_label(mode, "unknown"),
            limit=_label(limit_str, "none"),
        )
    log_saturation(
        "cortex_circuit_breaker_overflow_size",
        float(max(overflow_count, 0)),
        module="processor",
        mode=_label(mode, "unknown"),
        limit=_label(limit_str, "none"),
    )
    log_saturation(
        "cortex_circuit_breaker_permitted_size",
        float(max(normal_count, 0)),
        module="processor",
        mode=_label(mode, "unknown"),
        limit=_label(limit_str, "none"),
    )


def emit_dvm_result(mode: str, matched: bool, group: Optional[str]) -> None:
    """Emits dvm result using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_dvm_evaluated_count",
        1,
        module="processor",
        mode=_label(mode, "unknown"),
        result="matched" if matched else "unmatched",
        group=_label(group, "none"),
    )


def emit_dvm_latency(mode: str, matched: bool, group: Optional[str], latency_ms: float) -> None:
    """Emits dvm latency using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_latency(
        "cortex_dvm_evaluation_latency_ms",
        latency_ms,
        module="processor",
        mode=_label(mode, "unknown"),
        result="matched" if matched else "unmatched",
        group=_label(group, "none"),
    )


def emit_mitigation_attempt_start(mode: str, group: Optional[str], action: Optional[str]) -> None:
    """Emits mitigation attempt start using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_mitigation_attempt_count",
        1,
        module="processor",
        mode=_label(mode, "unknown"),
        group=_label(group, "none"),
        action=_label(action, "unspecified"),
        status="started",
    )


def emit_mitigation_result(mode: str, group: Optional[str], action: Optional[str], result: str) -> None:
    """Emits mitigation result using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_mitigation_result_count",
        1,
        module="processor",
        mode=_label(mode, "unknown"),
        group=_label(group, "none"),
        action=_label(action, "unspecified"),
        result=_label(result, "unknown"),
    )


def emit_mitigation_latency(
    mode: str,
    group: Optional[str],
    action: Optional[str],
    latency_ms: float,
    result: str,
) -> None:
    """Emits mitigation latency using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_latency(
        "cortex_mitigation_latency_ms",
        latency_ms,
        module="processor",
        mode=_label(mode, "unknown"),
        group=_label(group, "none"),
        action=_label(action, "unspecified"),
        result=_label(result, "unknown"),
    )


def emit_escalation(mode: str, esc_type: str, severity: str, result: str) -> None:
    """Emits escalation using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_escalation_count",
        1,
        module="processor",
        mode=_label(mode, "unknown"),
        type=_label(esc_type, "unspecified"),
        severity=_label(severity, "unspecified"),
        result=_label(result, "unknown"),
    )


def emit_ai_request(mode: Optional[str], result: str, error_type: Optional[str] = None) -> None:
    """Emits ai request using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_ai_request_count",
        1,
        module="ai",
        mode=_label(mode, "unknown"),
        result=_label(result, "unknown"),
        error_type=_label(error_type, "none"),
    )


def emit_ai_latency(mode: Optional[str], latency_ms: float, result: str) -> None:
    """Emits ai latency using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_latency(
        "cortex_ai_request_latency_ms",
        latency_ms,
        module="ai",
        mode=_label(mode, "unknown"),
        result=_label(result, "unknown"),
    )


def emit_ai_parse_status(mode: Optional[str], status: str) -> None:
    """Emits ai parse status using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_ai_response_quality_count",
        1,
        module="ai",
        mode=_label(mode, "unknown"),
        status=_label(status, "unknown"),
    )


def emit_ai_enrichment(mode: Optional[str], status: str) -> None:
    """Emits ai enrichment using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_ai_enrichment_count",
        1,
        module="ai",
        mode=_label(mode, "unknown"),
        status=_label(status, "unknown"),
    )


def emit_kb_query(result: str, latency_ms: Optional[float] = None, error_type: Optional[str] = None) -> None:
    """Emits kb query using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_kb_query_count",
        1,
        module="ai",
        result=_label(result, "unknown"),
        error_type=_label(error_type, "none"),
    )
    if latency_ms is not None:
        log_latency(
            "cortex_kb_query_latency_ms",
            latency_ms,
            module="ai",
            result=_label(result, "unknown"),
        )


def emit_passive_action_skip(action: str) -> None:
    """Emits passive action skip using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput(
        "cortex_passive_action_skipped_count",
        1,
        module="jira",
        action=_label(action, "unspecified"),
    )
