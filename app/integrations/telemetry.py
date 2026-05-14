"""Lightweight T2/AWS Monitoring integration for Heron.

This mirrors the pattern used in other Python apps:
- A MonitoringService client that posts metrics to AWS Monitoring (T2)
- Thin helper functions to emit key signals (throughput, latency, saturation, traffic)

If telemetry.enabled is False or dependencies are unavailable, all functions
are no-ops to keep runtime safe.

"""
from __future__ import annotations

import warnings
from typing import Dict, Any, Optional
import threading
from datetime import datetime, timezone
import os
import json
import base64


# Silence noisy aws.base_client DeprecationWarning (datetime.utcnow) that surfaces in stdout.
warnings.filterwarnings(
    "ignore",
    message=r".*datetime\.datetime\.utcnow\(\) is deprecated.*",
    category=DeprecationWarning,
)

import requests

from utils.settings import get_telemetry_settings, get_max_telemetry_threads
from utils.logger import log

try:
    import aws
    from aws.exceptions import ConfigFileNotFound
    from aws.monitoring import MonitoringClient
    from aws.monitoring.models import Datapoint, MetricDataDetails, PostMetricDataDetails
    AWS_AVAILABLE = True
except Exception:
    # aws is optional; gracefully degrade to no-op
    AWS_AVAILABLE = False
    MonitoringClient = object  # type: ignore


class _MonitoringService:
    """Provides MonitoringService behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self, cfg: Dict[str, Any]):
        """Initializes instance state using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        self.enabled = bool(cfg.get("enabled")) and AWS_AVAILABLE
        self.namespace = cfg.get("namespace", "heron")
        self.resource_group = cfg.get("resource_group", "")
        self.account_id = cfg.get("account_id", "")
        self.endpoint = cfg.get("endpoint", "")
        self.region = cfg.get("region", "us-ashburn-1")
        self.active_threads = []
        self.max_concurrent_threads = get_max_telemetry_threads()
        self._count_lock = threading.Lock()
        self._active_thread_count = 0

        self.client = self._client() if self.enabled else None

        # Log telemetry status and client initialization
        if self.enabled:
            if self.client:
                log("info", "Telemetry enabled: client initialized successfully (namespace={}, resource_group={}, region={}, account_id={})",
                    self.namespace, self.resource_group, self.region, self.account_id)
            else:
                log("error", "Telemetry enabled but client initialization failed (namespace={}, resource_group={}, region={}, account_id={})",
                    self.namespace, self.resource_group, self.region, self.account_id)
        else:
            log("info", "Telemetry disabled (config disabled or AWS SDK unavailable)")

    def shutdown(self) -> None:
        """Builds shutdown using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        for t in self.active_threads[:]:  # Copy to avoid mutation during iteration
            if t.is_alive():
                t.join(timeout=5.0)  # Wait up to 5 seconds for each thread
        self.active_threads.clear()

    @property
    def _aws_config(self) -> Dict[str, Any]:
        """Builds aws config using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not AWS_AVAILABLE:
            return {"region": self.region}
        try:
            return aws.config.from_file()
        except ConfigFileNotFound:
            return {"region": self.region}

    @property
    def _signer(self):
        """Builds signer using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not AWS_AVAILABLE:
            return None
        try:
            # Prefer local user config; fall back to instance/resource principals
            token_file = self._aws_config.get("security_token_file")
            key_file = self._aws_config.get("key_file")
            if token_file and key_file:
                token = open(token_file, "r").read()
                private_key = aws.signer.load_private_key_from_file(key_file)
                return aws.auth.signers.SecurityTokenSigner(token, private_key)
        except Exception:
            pass
        try:
            return aws.auth.signers.InstancePrincipalsSecurityTokenSigner()
        except Exception:
            return None

    def _client(self):
        """Builds client using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not AWS_AVAILABLE:
            return None
        retry_strategy = aws.retry.RetryStrategyBuilder(
            max_attempts_check=True,
            max_attempts=5,
            total_elapsed_time_check=True,
            total_elapsed_time_seconds=600,
            retry_max_wait_between_calls_seconds=45,
            retry_base_sleep_time_seconds=2,
            service_error_check=True,
            service_error_retry_on_any_5xx=True,
            service_error_retry_config={400: ["QuotaExceeded", "LimitExceeded"], 429: []},
            backoff_type=aws.retry.BACKOFF_FULL_JITTER_EQUAL_ON_THROTTLE_VALUE,
        ).get_retry_strategy()
        client = MonitoringClient(
            config=self._aws_config,
            signer=self._signer,
            endpoint=self.endpoint,
            retry_strategy=retry_strategy,
        )
        client.base_client.endpoint = self.endpoint
        return client

    def _push_metric(self, name: str, value: float, dimensions: Dict[str, str]) -> None:
        # Guard against empty dimension keys/values to avoid ingestion errors
        """Builds push metric using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        for k, v in dimensions.items():
            if not k or not v:
                log("error", "Cannot send empty dimension value: {}", dimensions)
                return

        # Use provided dimensions as-is (no implicit defaults to mirror non-CLI behavior)
        dims = dimensions

        metric = PostMetricDataDetails(
            metric_data=[
                MetricDataDetails(
                    name=name,
                    namespace=self.namespace,
                    dimensions=dims,
                    resource_group=self.resource_group,
                    account_id=self.account_id,
                    datapoints=[
                        Datapoint(
                            value=value,
                            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                        )
                    ],
                )
            ]
        )
        try:
            assert self.client is not None
            self.client.post_metric_data(metric)
        except Exception as e:
            log("error", "Failed to send metrics. name={} dims={} error={}", name, dimensions, e)
            raise e

    def log_metric(self, name: str, value: float, dimensions: Dict[str, str]) -> None:
        """Builds log metric using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        if not self.enabled or not self.client:
            return

        # Attempt to reserve a slot for asynchronous submission; fallback to sync if at limit
        if not self._try_reserve_thread_slot():
            log("debug", "At telemetry thread limit ({}) sending metric synchronously: {}", self.max_concurrent_threads, name)
            try:
                self._push_metric(name=name, value=value, dimensions=dimensions)
            except Exception as sync_e:
                log("error", "Failed to send metric synchronously: {}: {}", name, sync_e)
            return

        try:
            def _push_metric_with_cleanup(name: str, value: float, dimensions: Dict[str, str]) -> None:
                """Builds push metric with cleanup using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
                try:
                    self._push_metric(name, value, dimensions)
                finally:
                    # Decrement counter when thread finishes
                    self._decrement_active_threads()

            t = threading.Thread(
                target=_push_metric_with_cleanup,
                args=(name, value, dimensions),
                name=f"telemetry-{name}"
            )
            t.daemon = True
            t.start()
            self.active_threads.append(t)
            # Clean up completed threads to prevent memory leaks
            self.active_threads[:] = [thr for thr in self.active_threads if thr.is_alive()]
        except RuntimeError as e:
            # Decrement counter on failure
            self._decrement_active_threads()

            # Thread creation failed (e.g., in constrained Docker environments)
            # Fall back to synchronous execution
            if "can't start new thread" in str(e) or "can't start new process" in str(e):
                log("info", "Thread creation failed, sending metric synchronously: {}", name)
                try:
                    self._push_metric(name=name, value=value, dimensions=dimensions)
                except Exception as sync_e:
                    log("error", "Failed to send metric synchronously: {}: {}", name, sync_e)
            else:
                log("error", "Failed to submit metric: {}: {}", name, e)
        except Exception as e:
            # Decrement counter on failure
            self._decrement_active_threads()
            log("error", "Failed to submit metric: {}: {}", name, e)

    def _try_reserve_thread_slot(self) -> bool:
        """Builds try reserve thread slot using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        with self._count_lock:
            if self._active_thread_count >= self.max_concurrent_threads:
                return False
            self._active_thread_count += 1
            return True

    def _decrement_active_threads(self) -> None:
        """Builds decrement active threads using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._count_lock:
            if self._active_thread_count > 0:
                self._active_thread_count -= 1


_SERVICE: _MonitoringService | None = None


def _service() -> _MonitoringService:
    """Builds service using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    global _SERVICE
    if _SERVICE is None:
        cfg = get_telemetry_settings()
        _SERVICE = _MonitoringService(cfg)
        if not _SERVICE.enabled:
            log("info", "Telemetry disabled or AWS SDK unavailable; metrics will be no-ops")
    return _SERVICE


def log_metric(name: str, value: float, module: str, **extra_dims: str) -> None:
    """Builds log metric using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    svc = _service()
    dims = {"module": module}
    dims.update({k: v for k, v in extra_dims.items() if isinstance(v, str) and v})
    svc.log_metric(name, float(value), dims)


# Convenience wrappers for common signals
def log_throughput(name: str, count: int, module: str, **dims: str) -> None:
    """Builds log throughput using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_metric(name, float(count), module, **dims)


def log_latency(name: str, duration_ms: float, module: str, **dims: str) -> None:
    """Builds log latency using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_metric(name, float(duration_ms), module, **dims)


def log_saturation(name: str, value: float, module: str, **dims: str) -> None:
    """Builds log saturation using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_metric(name, float(value), module, **dims)


def log_traffic(name: str, count: int, module: str, **dims: str) -> None:
    """Builds log traffic using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_metric(name, float(count), module, **dims)


def log_health(name: str, is_up: bool, module: str, **dims: str) -> None:
    """Builds log health using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_metric(name, float(1 if is_up else 0), module, **dims)


def log_jira_api_call(operation: str, module: str = "jira", **dims: str) -> None:
    """Builds log jira api call using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    log_throughput("heron_jira_api_calls_count", 1, module, operation=operation, **dims)