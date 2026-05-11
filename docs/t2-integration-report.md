T2 (AWS Monitoring) Integration Report

Status: Design/Implementation Guide (no destination repos modified by this document)

Table of contents
- 1) Purpose and scope
- 2) Source repository architecture (where T2 is implemented)
- 3) Full T2 source code with explanations
- 4) Destination: customer-agent-tool (actionable checklist, code, config)
- 5) Destination: customer-agent-container (actionable checklist, code, config)
- 6) Destination: customer-agent-proxy-service (actionable checklist, code, config)
- 7) Dependency and versioning guidance
- 8) Security and privacy checklist
- 9) Best practices (modularity, toggles, docs, tests)
- 10) Additional comprehensive monitoring ideas
- 11) Consolidated implementation checklist (per repo)

1) Purpose and scope

This report extracts the complete T2 (AWS Monitoring) metrics architecture from the source repository and provides precise, actionable integration guidance for these destination repositories:
- $USER/code/customer-agent-tool
- $USER/code/customer-agent-container
- $USER/code/customer-agent-proxy-service

Core metric categories to implement where data exists:
- Throughput
- Latency
- Saturation
- Traffic
- Service health (0 for down, 1 for up)


2) Source repository architecture (cda-caim-sdk)

Key files and responsibilities
- src/cda_caim_sdk/common/monitoring/monitoring.py
  - MonitoringService: low-level AWS Monitoring client wrapper
  - Handles region-aware endpoint, authentication (local or Instance Principals), robust retry strategy
  - Asynchronous emission via ThreadPoolExecutor
- src/cda_caim_sdk/core/monitoring.py
  - High-level, dimension-validating façade with semantic helper functions (e.g., log_events_processed_metric)
  - Initializes MonitoringService using ConfigLoader (resource group, account, region)
  - Provides context-manager for latency measurement (log_duration)
- src/cda_caim_sdk/core/server.py
  - db_monitoring_task: periodically emits DB pool saturation (connection counts) via T2 metrics
- src/cda_caim_sdk/common/aws/si_mapper.py
  - Emits failure metrics when SI instance resolution fails

Metric category mapping (examples in source)
- Throughput: oeo_aes_events_processed_count, oeo_processor_task_count, oeo_scheduler_task_registration
- Latency: oeo_processor_task_duration, oeo_consumer_task_duration, oeo_scheduler_task_schedule_delay_secs, oeo_duration_metrics
- Saturation: oeo_celery_task_count, oeo_database_connection_status, oeo_redis_health, oeo_redis_error_count
- Traffic: oeo_aes_events_received_count, oeo_active_aes_subscription_count
- Service health: oeo_aes_client_health_metrics


3) Full T2 source code with explanations

3.1 MonitoringService (low-level client)

File: cda-caim-sdk/src/cda_caim_sdk/common/monitoring/monitoring.py

Explanation
- Auth: prefers local AWS config (SecurityTokenSigner), falls back to InstancePrincipalsSecurityTokenSigner for EKS/AWS
- Retry: uses AWS SDK RetryStrategyBuilder with jitter and bounded backoff for resiliency
- Submission: PostMetricDataDetails with Datapoint (UTC timestamp), executed on executor thread to avoid blocking the caller

Code (verbatim)
```python
import logging
from concurrent.futures import Future
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime, timezone

import aws
from aws.auth.signers import InstancePrincipalsSecurityTokenSigner, SecurityTokenSigner
from aws.config import DEFAULT_LOCATION, DEFAULT_PROFILE
from aws.exceptions import ConfigFileNotFound
from aws.monitoring import MonitoringClient
from aws.monitoring.models import Datapoint, MetricDataDetails, PostMetricDataDetails

_logger = logging.getLogger(__name__)


class MonitoringService:
    """
    Class for sending application metrics to AWS monitoring service.
    """

    def __init__(
        self,
        namespace: str,
        resource_group: str,
        account_id: str,
        endpoint: str = "https://telemetry-ingestion.us-ashburn-1.amazoncloud.com",
        region: str = "us-ashburn-1",
        aws_config_file_loc: str = DEFAULT_LOCATION,
        aws_profile_name: str = DEFAULT_PROFILE,
        enabled: bool = True,
    ):
        self.namespace = namespace
        self.resource_group = resource_group
        self.account_id = account_id
        self.endpoint = endpoint
        self.region = region
        self.aws_config_file_loc = aws_config_file_loc
        self.aws_profile_name = aws_profile_name
        self.executor = ThreadPoolExecutor()
        self.client = self._client() if enabled else None

    @property
    def aws_config(self):
        """
        Creates default aws config
        :return:
        """
        try:
            aws_config = aws.config.from_file(
                file_location=self.aws_config_file_loc,
                profile_name=self.aws_profile_name,
            )
        except ConfigFileNotFound:
            aws_config = {"region": self.region}
        return aws_config

    @property
    def token(self):
        """
        Creates default auth Token
        :return:
        """
        token_file = self.aws_config["security_token_file"]
        with open(token_file, "r") as f:
            token = f.read()
        return token

    @property
    def signer(self):
        """
        Creates default signer by using local config of user.
        If it fails, uses Resource Principal.
        :return:
        """
        try:
            # Use local config for user
            private_key = aws.signer.load_private_key_from_file(
                self.aws_config["key_file"]
            )
            signer = SecurityTokenSigner(self.token, private_key)
        except (ConfigFileNotFound, KeyError):
            # Use Resource Principal for EKS pods
            signer = InstancePrincipalsSecurityTokenSigner()
        return signer

    def _client(self) -> MonitoringClient | None:
        """
        Creates AWS MonitoringClient
        :return:
        """
        retry_strategy = aws.retry.RetryStrategyBuilder(
            # Make up to 5 service calls
            max_attempts_check=True,
            max_attempts=5,
            # Don't exceed a total of 600 seconds for all service calls
            total_elapsed_time_check=True,
            total_elapsed_time_seconds=600,
            # Wait 45 seconds between attempts
            retry_max_wait_between_calls_seconds=45,
            # Use 2 seconds as the base number for doing sleep time calculations
            retry_base_sleep_time_seconds=2,
            # Retry on certain service errors:
            service_error_check=True,
            service_error_retry_on_any_5xx=True,
            service_error_retry_config={
                400: ["QuotaExceeded", "LimitExceeded"],
                429: [],
            },
            backoff_type=aws.retry.BACKOFF_FULL_JITTER_EQUAL_ON_THROTTLE_VALUE,
        ).get_retry_strategy()

        client: MonitoringClient = MonitoringClient(
            config=self.aws_config,
            signer=self.signer,
            endpoint=self.endpoint,
            retry_strategy=retry_strategy,
        )
        client.base_client.endpoint = self.endpoint
        return client

    def _push_metric(self, name: str, value: float, dimensions: dict[str, str]) -> None:
        """
        Push metrics to AWS monitoring service
        :return:
        """
        metric = PostMetricDataDetails(
            metric_data=[
                MetricDataDetails(
                    name=name,
                    namespace=self.namespace,
                    dimensions=dimensions,
                    resource_group=self.resource_group,
                    account_id=self.account_id,
                    datapoints=[
                        Datapoint(
                            value=value,
                            timestamp=datetime.now(timezone.utc)
                            .astimezone()
                            .isoformat(),
                        )
                    ],
                )
            ]
        )
        try:
            self.client.post_metric_data(metric)
        except Exception as e:
            _logger.exception(f"Failed to send metrics. {metric=}")
            raise e

    def log_metric(
        self,
        name: str,
        value: float,
        dimensions: dict[str, str],
    ) -> Future:
        """
        Push metrics to T2. Wrapper for _push_metrics()
        :return:
        """
        if self.client:
            try:
                return self.executor.submit(
                    self._push_metric, name=name, value=value, dimensions=dimensions
                )
            except RuntimeError as e:
                future = Future()
                future.set_exception(e)
                # Handle the known error that has appeared too many times in the logs
                if (
                    "Failed to submit cannot schedule new futures after interpreter shutdown"
                    not in str(e)
                ):
                    _logger.exception(f"Failed to submit {e}")
                return future
            except Exception as e:
                # Make sure to not raise an error on submit so this won't be a blocker.
                _logger.exception(f"Failed to submit {e}")
                future = Future()
                future.set_exception(e)
                return future
        else:
            # Log monitoring data for debugging purposes (verbose, not for production use)
            future = Future()
            future.set_result(
                f"MonitoringService is not enabled. {name=}, {value=}, {dimensions=}"
            )
            return future
```

3.2 High-level helpers and patterns

File: cda-caim-sdk/src/cda_caim_sdk/core/monitoring.py

Explanation
- Validates no empty dimension keys/values
- Initializes a cached MonitoringService based on environment/config
- Provides domain-specific helpers for throughput/latency/saturation/traffic/service health
- Provides context manager for timing arbitrary code blocks

Code (verbatim)
```python
import logging
import time
from contextlib import contextmanager
from threading import Lock

from cda_caim_sdk.common.monitoring.monitoring import MonitoringService
from cda_caim_sdk.core.config import ConfigLoader

LOGGER = logging.getLogger(__name__)

_service_cache: MonitoringService | None = None
_lock = Lock()


def _service() -> MonitoringService:
    global _service_cache
    if _service_cache is not None:
        return _service_cache

    with _lock:
        if _service_cache is None:
            config = ConfigLoader.load()
            enabled = (
                len(config.monitoring_resource_group) > 0
                and len(config.monitoring_account_id) > 0
            )
            LOGGER.info(f"Monitoring service enabled: {enabled}")
            _service_cache = MonitoringService(
                namespace="cda-oeo",
                endpoint=f"https://telemetry-ingestion.{config.region}.amazoncloud.com",
                resource_group=config.monitoring_resource_group,
                account_id=config.monitoring_account_id,
                enabled=enabled,
                region=config.region,
            )
        return _service_cache


def _log_metric(name: str, value: float, dimensions: dict[str, str]):
    service = _service()
    for k, v in dimensions.items():
        if k is None or k == "" or v is None or v == "":
            LOGGER.error(
                f"Cannot send empty dimension value to the metrics service: {dimensions}"
            )
            return
    service.log_metric(name, value, dimensions)


def log_subscription_attempt_metric(subscription_id: str, successful: bool):
    _log_metric(
        name="oeo_aes_subscribe_attempt_count",
        value=float(1),
        dimensions={
            "subscription_id": subscription_id,
            "successful": str(successful),
        },
    )


def log_subscription_creation_metric(subscription_id: str):
    _log_metric(
        name="oeo_aes_subscribe_creation_count",
        value=float(1),
        dimensions={"subscription_id": subscription_id},
    )


def log_active_subscription_metric(host: str, count: int):
    _log_metric(
        name="oeo_active_aes_subscription_count",
        value=float(count),
        dimensions={"host": host},
    )


def log_subscription_deletion_metric(subscription_id: str):
    _log_metric(
        name="oeo_aes_subscribe_deletion_count",
        value=float(1),
        dimensions={"subscription_id": subscription_id},
    )


def log_events_received_metric(
    si_service_instance_id: str, event_type: str, module: str
):
    _log_metric(
        name="oeo_aes_events_received_count",
        value=float(1),
        dimensions={
            "si_service_instance_id": si_service_instance_id,
            "event_type": event_type,
            "module": module,
        },
    )


def log_events_processed_metric(
    si_service_instance_id: str, event_type: str, module: str
):
    _log_metric(
        name="oeo_aes_events_processed_count",
        value=float(1),
        dimensions={
            "si_service_instance_id": si_service_instance_id,
            "event_type": event_type,
            "module": module,
        },
    )


def log_processor_task_count_metric(
    si_service_instance_id: str,
    task_count: int,
    module: str,
    status: str,
    bootstrap_key: str | None = None,
):
    dimensions = {
        "si_service_instance_id": si_service_instance_id,
        "module": module,
        "status": status,
    }
    if bootstrap_key:
        dimensions["bootstrap_key"] = bootstrap_key
    _log_metric(
        name="oeo_processor_task_count",
        value=float(task_count),
        dimensions=dimensions,
    )


def log_stale_context_missing_task_id_metric(
    si_service_instance_id: str, task_count: int, module: str
):
    """Logs a count of stale contexts that are in a RUNNING state but have no Celery task_id."""
    _log_metric(
        name="oeo_stale_context_missing_task_id_count",
        value=float(task_count),
        dimensions={
            "si_service_instance_id": si_service_instance_id,
            "module": module,
        },
    )


def log_stale_context_task_not_in_celery_metric(
    si_service_instance_id: str, task_count: int, module: str
):
    """Logs a count of stale contexts that are in a RUNNING state but their task_id is not found in Celery."""
    _log_metric(
        name="oeo_stale_context_task_not_in_celery_count",
        value=float(task_count),
        dimensions={
            "si_service_instance_id": si_service_instance_id,
            "module": module,
        },
    )


def log_processor_task_duration_metric(
    si_service_instance_id: str,
    module: str,
    time_in_sec: float,
    bootstrap_key: str | None,
):
    dimensions = {
        "si_service_instance_id": si_service_instance_id,
        "module": module,
    }
    if bootstrap_key:
        dimensions["bootstrap_key"] = bootstrap_key
    _log_metric(
        name="oeo_processor_task_duration",
        value=time_in_sec,
        dimensions=dimensions,
    )


def log_celery_task_count_metric(
    module: str, status: str, count: int, node_or_queue: str
):
    if count == 0:
        return

    _log_metric(
        name="oeo_celery_task_count",
        value=float(count),
        dimensions={
            "module": module,
            "status": status,
            "node_or_queue": node_or_queue,
        },
    )


def log_consumer_task_duration_metric(
    si_service_instance_id: str, module: str, time_in_sec: float, status: str
):
    dimensions = {
        "si_service_instance_id": si_service_instance_id,
        "module": module,
        "status": status,
    }
    _log_metric(
        name="oeo_consumer_task_duration",
        value=time_in_sec,
        dimensions=dimensions,
    )


def log_aes_client_health_metrics(is_healthy: bool, data_plane_url: str):
    _log_metric(
        name="oeo_aes_client_health_metrics",
        value=float(1 if is_healthy else 0),
        dimensions={
            "data_plane_url": data_plane_url,
        },
    )


def log_scheduler_task_registration_metrics(task_count: int, successful: bool):
    _log_metric(
        name="oeo_scheduler_task_registration",
        value=float(task_count),
        dimensions={
            "successful": str(successful),
        },
    )


def log_scheduler_schedule_delay_metrics(
    si_service_instance_id: str, module: str, delay_in_secs: float
):
    dimensions = {"si_service_instance_id": si_service_instance_id, "module": module}
    _log_metric(
        name="oeo_scheduler_task_schedule_delay_secs",
        value=delay_in_secs,
        dimensions=dimensions,
    )


def log_database_connection_status(
    connection_count: int, si_service_instance_id: str, kind: str
):
    _log_metric(
        name="oeo_database_connection_status",
        value=float(connection_count),
        dimensions={
            "si_service_instance_id": si_service_instance_id,
            "kind": kind,
        },
    )


def log_si_resolution_failure_metric(instance_id: str, instance_type: str):
    """Logs a failure to resolve a Semantic Index instance."""
    _log_metric(
        name="oeo_si_resolution_failure_count",
        value=float(1),
        dimensions={
            "instance_id": instance_id,
            "instance_type": instance_type,
        },
    )


def log_redis_health_metric(
    module: str, broker_host: str, queue: str, is_healthy: bool
):
    """Logs Redis (AWS Cache) health as a binary metric.

    Dimensions:
      - module: processor module name
      - broker_host: Redis hostname (sanitized)
      - queue: Celery queue name
    """
    _log_metric(
        name="oeo_redis_health",
        value=float(1 if is_healthy else 0),
        dimensions={
            "module": module,
            "broker_host": broker_host,
            "queue": queue,
        },
    )


def log_redis_error_metric(module: str, broker_host: str, queue: str, error: str):
    """Logs a count metric for Redis (AWS Cache) errors with error type/code.

    Dimensions:
      - module: processor module name
      - broker_host: Redis hostname (sanitized)
      - queue: Celery queue name
      - error: short error class or code (e.g., ConnectionError)
    """
    _log_metric(
        name="oeo_redis_error_count",
        value=float(1),
        dimensions={
            "module": module,
            "broker_host": broker_host,
            "queue": queue,
            "error": error,
        },
    )


@contextmanager
def log_duration(key: str, write_log: bool = False, **kwargs):
    """Context manager to measure and log the duration of a given operation.

    Args:
        key (str): Identifier for the operation being measured.
        write_log (bool, optional): Flag to indicate whether to write a log message.
                                    Defaults to False.
        kwargs: Additional information for logging.

    Example:
        with log_duration("my_operation", write_log=True):
            # Code block to be measured
            time.sleep(1)
    """
    start_time = time.perf_counter()
    yield
    end_time = time.perf_counter()
    duration = float(end_time - start_time) * 1000
    _log_metric(
        name="oeo_duration_metrics",
        value=duration,
        dimensions={"key": key},
    )
    if write_log:
        LOGGER.info(f"Elapsed {duration} ms for {key=}. extra={kwargs}")
```

3.3 Server DB saturation task (excerpt)

File: cda-caim-sdk/src/cda_caim_sdk/core/server.py

Explanation
- Periodically emits connection pool saturation per tenant/kind

Code (excerpt)
```python
    @classmethod
    async def db_monitoring_task(cls, interval: int):
        # If the interval is set to 0, this won't run
        while interval > 0:
            pool_status = SessionLocal.get_pool_status()
            for si_service_instance_id, connections in pool_status.items():
                for kind, count in connections.items():
                    monitoring.log_database_connection_status(
                        connection_count=count,
                        si_service_instance_id=si_service_instance_id,
                        kind=kind,
                    )
            await asyncio.sleep(interval)
```


4) Destination: customer-agent-tool

Key files (current)
- Messaging clients: src/customer_agent_tools/messaging/remote_message_bus_webhook.py, remote_message_bus_ws.py
- Webhook dispatcher: src/customer_agent_tools/messaging/webhook_dispatcher.py
- Config: src/customer_agent_tools/config/config_loader.py

Actionable checklist
1. Create metrics façade
   - File: src/customer_agent_tools/t2/monitoring.py
   - Purpose: Initialize MonitoringService and define helper functions per category
   - Code template (adjust namespace if preferred):
   ```python
   import logging, os
   from typing import Dict
   from cda_caim_sdk.common.monitoring.monitoring import MonitoringService

   _logger = logging.getLogger(__name__)
   _service_cache = None

   def _service():
       global _service_cache
       if _service_cache is not None:
           return _service_cache
       region = os.getenv("AWS_REGION") or os.getenv("REGION") or "us-ashburn-1"
       resource_group = os.getenv("MONITORING_RESOURCE_GROUP", "")
       account_id = os.getenv("MONITORING_account_ID", "")
       enabled = (
           os.getenv("ENABLE_T2_METRICS", "true").lower() == "true"
           and bool(resource_group) and bool(account_id)
       )
       _logger.info(f"T2 Monitoring enabled={enabled}, region={region}, rg={resource_group}")
       _service_cache = MonitoringService(
           namespace="customer-agent-tools",
           resource_group=resource_group,
           account_id=account_id,
           endpoint=f"https://telemetry-ingestion.{region}.amazoncloud.com",
           region=region,
           enabled=enabled,
       )
       return _service_cache

   def _log_metric(name: str, value: float, dimensions: Dict[str, str]):
       for k, v in dimensions.items():
           if not k or not v:
               _logger.error(f"Invalid dimension in {name}: {dimensions}")
               return
       try:
           _service().log_metric(name, float(value), dimensions)
       except Exception:
           _logger.exception(f"Failed to submit metric {name}")

   # Category helpers
   def log_service_health(is_up: bool):
       _log_metric("cat_service_health", 1.0 if is_up else 0.0, {})

   def log_traffic(kind: str, count: int = 1, subscriber_or_topic: str = ""):
       dims = {"kind": kind}
       if subscriber_or_topic:
           dims["dest"] = subscriber_or_topic
       _log_metric("cat_traffic_count", float(count), dims)

   def log_throughput(flow: str, count: int = 1, status: str = "success"):
       _log_metric("cat_throughput_count", float(count), {"flow": flow, "status": status})

   def log_latency(op: str, millis: float):
       _log_metric("cat_latency_ms", float(millis), {"op": op})

   def log_saturation(resource: str, value: float, node: str = ""):
       dims = {"resource": resource}
       if node:
           dims["node"] = node
       _log_metric("cat_saturation", float(value), dims)
   ```

2. Instrument RemoteMessageBusWebhook (src/customer_agent_tools/messaging/remote_message_bus_webhook.py)
   - Imports (top of file):
     ```python
     from customer_agent_tools.t2 import monitoring as t2
     import time
     ```
   - In start():
     ```python
     async def start(self) -> None:
         self._running = True
         t2.log_service_health(True)
     ```
   - In stop():
     ```python
     async def stop(self) -> None:
         ...
         self._running = False
         t2.log_service_health(False)
     ```
   - In create_topic_if_needed / create_queue_if_needed (after success):
     ```python
     t2.log_traffic(kind="create_topic", subscriber_or_topic=topic_id)
     # or for queues
     t2.log_traffic(kind="create_queue", subscriber_or_topic=queue_id)
     ```
   - In publish():
     ```python
     start = time.perf_counter()
     r = await self._http.post(...)
     r.raise_for_status()
     ms = (time.perf_counter() - start) * 1000.0
     t2.log_latency("publish", ms)
     t2.log_traffic(kind="publish", count=1)
     ```
   - In deliver_incoming():
     ```python
     start = time.perf_counter()
     # build tasks ...
     n = len(tasks)
     t2.log_saturation(resource="incoming_handlers", value=n)
     t2.log_throughput(flow="deliver_incoming", count=n, status="queued")
     if tasks:
         await asyncio.gather(*tasks)
     t2.log_throughput(flow="deliver_incoming", count=n, status="processed")
     t2.log_latency("deliver_incoming_dispatch", (time.perf_counter() - start) * 1000.0)
     ```

3. Instrument Webhook dispatcher (src/customer_agent_tools/messaging/webhook_dispatcher.py)
   - Imports:
     ```python
     from customer_agent_tools.t2 import monitoring as t2
     import time
     ```
   - In GET /health and /ready: optionally emit low-rate health (or just on startup)
   - In POST /agent/webhook before/after bus.on_webhook_frame(frame):
     ```python
     start = time.perf_counter()
     ack_payload = await bus.on_webhook_frame(frame)
     t2.log_latency("on_webhook_frame", (time.perf_counter() - start) * 1000.0)
     t2.log_traffic(kind="webhook_frame", count=1)
     ```
   - On exceptions:
     ```python
     t2.log_throughput(flow="on_webhook_frame", count=1, status="failed")
     ```

4. Configuration (environment)
- ENABLE_T2_METRICS=true
- MONITORING_RESOURCE_GROUP=<your-resource-group>
- MONITORING_account_ID=<your-account-awsid>
- AWS_REGION=us-ashburn-1 (or your region)

5. Dependency notes
- Upgrade cda-caim-sdk to a version that includes the shown helpers: e.g., >=3.17.2 (or align to 3.29.0 used by proxy service).

6. Security & privacy for this repo
- Do not place PII (patient IDs, tokens, emails) in any dimension.
- Use generic dimensions like kind/flow/status/op/resource/node/dest.


5) Destination: customer-agent-container

Key files (current)
- Processor example: src/customer_agent_container/app/sample_agent_processor.py

Actionable checklist
1. Reuse the façade from customer-agent-tool (preferred) or add a local one
   - Preferred: import the façade you added to customer-agent-tools
     ```python
     from customer_agent_tools.t2 import monitoring as t2
     ```
   - Alternative: add src/customer_agent_container/t2/monitoring.py (copy from section 4.1; set namespace to "customer-agent-container")

2. Instrument processor work
   - File: src/customer_agent_container/app/sample_agent_processor.py
   - Example wrapper for process method:
   ```python
   from customer_agent_tools.processor import BaseAgentProcessor
   import time
   try:
       from customer_agent_tools.t2 import monitoring as t2
   except Exception:
       t2 = None

   class SampleAgentProcessor(BaseAgentProcessor):
       async def process(self, *args, **kwargs):
           start = time.perf_counter()
           status = "success"
           try:
               result = await super().process(*args, **kwargs)
               return result
           except Exception:
               status = "failed"
               raise
           finally:
               if t2:
                   ms = (time.perf_counter() - start) * 1000.0
                   t2.log_latency("processor_process", ms)
                   t2.log_throughput(flow="processor_process", count=1, status=status)
   ```

3. (Optional) Additional signals if available
- Work/batch sizes: log_throughput with count=batch_size and status
- Backlog size (if known): log_saturation(resource="processor_backlog", value=N)
- External call timings (SI/LLM/etc): log_latency("<dep>_call", ms); log_throughput(flow="<dep>_call", status="success|failed")

4. Configuration
- Same env as customer-agent-tool (ENABLE_T2_METRICS, MONITORING_RESOURCE_GROUP, MONITORING_account_ID, AWS_REGION)

5. Dependency notes
- Align cda-caim-sdk to >=3.17.2 (or match proxy service’s 3.29.0)

6. Security & privacy
- As above: avoid PII in dimensions; sanitize identifiers where necessary.


6) Destination: customer-agent-proxy-service

Key files (current)
- App bootstrap: src/agent_proxy_service/runner.py (FastAPI lifespan)
- Routers: src/agent_proxy_service/resources/*.py (kafka_message_bus_router, webhook_bridge_router, health_router, etc.)

Actionable checklist
1. Create façade
   - File: src/agent_proxy_service/t2/monitoring.py (copy template from section 4.1; set namespace to "agent-proxy-service")

2. Instrument lifecycle (src/agent_proxy_service/runner.py)
   - Imports:
     ```python
     from agent_proxy_service.t2 import monitoring as t2
     import time
     ```
   - On startup (inside lifespan): after successful Kafka start & memcache client init:
     ```python
     t0 = time.perf_counter()
     await app.state.bus.start()
     t2.log_latency("bus_start", (time.perf_counter() - t0) * 1000.0)
     t2.log_service_health(True)
     t2.log_throughput(flow="startup", count=1, status="success")
     ```
   - On shutdown:
     ```python
     t2.log_service_health(False)
     t2.log_throughput(flow="shutdown", count=1, status="success")
     ```
   - (Optional) Memcache ping:
     ```python
     try:
         await app.state.memcache.version()
         t2.log_saturation(resource="memcache_alive", value=1.0)
     except Exception:
         t2.log_saturation(resource="memcache_alive", value=0.0)
     ```

3. Instrument routers
- kafka_message_bus_router: after publish → t2.log_traffic(kind="publish", count=1)
- webhook_bridge_router: bridge create/delete → t2.log_throughput("bridge_create|delete", 1, status)
- webhook deliveries: measure latency and increment traffic
- health_router: keep HTTP status only; rely on t2.log_service_health for T2

4. Configuration
- ENABLE_T2_METRICS=true
- MONITORING_RESOURCE_GROUP=<your-resource-group>
- MONITORING_account_ID=<your-account-awsid>
- AWS_REGION=us-ashburn-1

5. Dependency notes
- Already on cda-caim-sdk==3.29.0 (OK)

6. Security & privacy
- Avoid embedding sensitive Kafka details or secrets in dimensions. Normalize identifiers if needed.


7) Dependency and versioning guidance

- Unify on a cda-caim-sdk version that includes MonitoringService + helpers used above.
  - Recommendation: cda-caim-sdk >= 3.17.2, < 4.0 (or align to 3.29.0 if validated across all repos)

Example pyproject.toml fragments
```toml
[project]
dependencies = [
  # ...
  "cda-caim-sdk>=3.17.2,<4.0",
]
```

AWS SDK dependency
- If you only use MonitoringService via cda-caim-sdk, you do not need to add aws explicitly.
- If you implement a local client, add: "aws>=2.37.0".


8) Security and privacy checklist

- Never include PII or secrets in metric dimensions or names.
- Sanitize or coarsen fields (e.g., kind/status/node) rather than IDs/tokens.
- Keep metric cardinality bounded (avoid high-cardinality fields such as request IDs).
- Ensure ENABLE_T2_METRICS toggle can be disabled quickly.
- Validate dimension keys/values are non-empty (see source pattern).


9) Best practices (modularity, toggles, docs, tests)

- Modular façade per service (t2/monitoring.py) that initializes MonitoringService once and exposes typed helpers.
- Feature flag: ENABLE_T2_METRICS + presence of resource group/account enables metrics.
- Document metrics in README/wiki and annotate code with docstrings for future maintainers.
- Unit-test helpers using mocks to assert expected calls and dimension validation.


10) Additional comprehensive monitoring ideas

Applicable to all three services (adopt where relevant):

- HTTP-level metrics (FastAPI)
  - Request count by route and status class (2xx/4xx/5xx): traffic and throughput
  - Request latency per route (p50/p90/p99): latency
  - In-flight request gauge per route: saturation

- Messaging (Kafka/webhook)
  - Publish latency and error rates per topic: latency/throughput
  - Delivery attempts, retries, DLQ counts: throughput/error rate
  - Backpressure signals: subscriber backlog length, handler concurrency permits: saturation

- Cache (Memcache/Redis)
  - Health (0/1), error counts by type
  - Hit/miss ratio (if accessible), average get/set latency

- Database/ORM
  - Connection pool checked_in/checked_out (already present in source)
  - Query latency for common operations, retry counts, deadlock/timeout counts

- External dependencies (SI, SAB, SKG, LLM, OAuth/STS)
  - Per-dependency health (0/1)
  - Call latency and error rate (by error class)
  - Circuit breaker open/half-open/closed state as a gauge if used

- Scheduler/Worker (Celery or equivalents)
  - Queue depth per queue, worker active/reserved (already modeled in source for Celery)
  - Task execution time histograms, failure counts by exception class

- Business KPIs (non-sensitive)
  - Processed events per tenant/module
  - Successful vs failed operations by flow (e.g., bridge lifecycle, event processing)

Naming examples for the above
- <service>_http_request_count{route, status_class}
- <service>_http_request_latency_ms{route}
- <service>_cache_health{backend}
- <service>_dep_call_latency_ms{dep}
- <service>_dep_call_error_count{dep, error}
- <service>_queue_depth{queue}
- <service>_kafka_publish_latency_ms{topic}
- <service>_webhook_delivery_count{status}


11) Consolidated implementation checklist

customer-agent-tool
- [ ] Add src/customer_agent_tools/t2/monitoring.py façade
- [ ] Instrument remote_message_bus_webhook.py (start/stop/publish/deliver_incoming)
- [ ] Instrument webhook_dispatcher.py (POST /agent/webhook)
- [ ] Ensure env vars set: ENABLE_T2_METRICS, MONITORING_RESOURCE_GROUP, MONITORING_account_ID, AWS_REGION
- [ ] Align cda-caim-sdk version to >=3.17.2 (or 3.29.0)
- [ ] Validate no PII in dimensions

customer-agent-container
- [ ] Reuse façade from customer-agent-tools or add local one
- [ ] Instrument processor methods (latency/throughput, optional backlog)
- [ ] Ensure env vars set as above
- [ ] Align cda-caim-sdk version
- [ ] Validate no PII in dimensions

customer-agent-proxy-service
- [ ] Add src/agent_proxy_service/t2/monitoring.py façade
- [ ] Instrument runner.lifespan for health, startup/shutdown, bus_start latency
- [ ] Instrument routers for publish/webhook/bridge lifecycle
- [ ] Ensure env vars set as above
- [ ] Already aligned on cda-caim-sdk==3.29.0 (OK)
- [ ] Validate no PII in dimensions


End of report

-------------------------------------
Cline prompt to implement the metrics
-------------------------------------
Prompt to implement these changes. Its best if you run this prompt once for every repository for which you want to implement metrics to keep the implementation clean and the avoid confusions.

the metrics should be implemented for the following list:
customer-agent-tool
customer-agent-container
customer-agent-proxy-service
	
Please find the source code here:
https://confluence.amazoncorp.com/confluence/pages/viewpage.action?pageId=17839674579#Pythonapplication%2FserviceintegrationwithT2-Repo

find the destination repos here:
https://confluence.amazoncorp.com/confluence/display/IBS/Customer+Agent+Container+-+Architecture+Design+Document#CustomerAgentContainerArchitectureDesignDocument-DeploymentandCI%2FCD

Act as a Developer.

You will be provided with the following:
- A source repository that implements complete T2 metrics emission and collection logic.
- A destination repository where T2 metrics emission is not yet present but must be integrated.

**Objectives:**

0. The following metrics are the most crucial and need to be implemented if available from the service side:

- Throughput
- Latency
- Saturation
- Traffic
- Service health - 0 for down and 1 for up.
- Any other metrics that is important to implement but not present.

1. Scan the source repository to:
   - Catalog all modules, classes, configuration sections, and helper utilities specifically used for T2 metrics emission.
   - Document the purpose of code segments involved (e.g., initialization, metric recording, batching, error fallback).
   - Note any 3rd-party dependencies and their respective versions.

2. Analyze the destination repository and perform the following:
   - Insert, update, or refactor code to instantiate the T2 metrics client in the recommended scope (application entry point or other service initialization logic).
   - Add all necessary code snippets for metric recording and emission, using the pattern established in the source repository. This may include:
     - Instrumentation code for key business logic or operational events.
     - Utility modules for metric formatting and emission.
     - Test utilities/mocks, where appropriate.
   - Create or update all required configuration files/blocks (e.g., credentials, T2 collector endpoints, sampling/interpolation settings).
   - Add inline code comments to clarify why and where metrics emission occurs, especially for new contributors.

3. Generate a comprehensive change report, including for every file affected:
   - **File path**
   - **Type of change** (created, updated, deleted)
   - **Purpose** (describe why this file was affected)
   - **Summary of changes:** Show the relevant code diff or the specific code/content added or modified.
   - **monitoring.md** create a how to guide at the root of the repository called monitoring.md and add the how to for the metrics.

4. Validation and Alerting:
   - Clearly mark any areas where automatic translation cannot be confidently done (e.g., highly contextual business logic, custom metrics requiring service-specific values). Use distinct TODO, FIXME, or similar comments to highlight for manual review.
   - List any assumptions made during code migration.
   - Warn if potentially breaking changes are introduced, or if there are features in the source that the destination service architecturally cannot support.

5. Security and Compliance:
   - Do NOT include any sensitive data (passwords, tokens, customer data) in default configs.
   - Adhere to Amazon’s secure development lifecycle, flagging any authentication/authorization requirements for metric emission.
   - Mention any additional steps needed for the developer to complete the integration safely and compliantly.

**IMPORTANT:** Report all changes in human-readable format for developer auditing. Confirm with the developer before pushing substantial modifications or refactors, and always recommend a code review.

source repository = <LOCAL_PATH_SOURCE_REPO_HERE>

destination repository = <LOCAL_PATH_DESTINATION_REPO_HERE>
