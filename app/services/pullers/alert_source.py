"""AlertSourceAdapter — abstract interface for pluggable alert source pullers.

Any alert source (CloudWatch, Datadog, PagerDuty, Prometheus Alertmanager,
a custom HTTP API) can be integrated with Cortex by implementing this interface.

How to add a new alert source adapter
--------------------------------------
1. Create a file in ``app/services/pullers/``, e.g. ``prometheus_puller.py``.
2. Subclass ``AlertSourceAdapter`` and implement ``source_name``, ``is_configured``,
   and ``pull``.
3. Register an instance in ``app/services/pullers/__init__.py``.
4. Add a corresponding entry under ``sources:`` in ``config/pullers.yaml``.

Example skeleton::

    from .alert_source import AlertSourceAdapter, AlertSourceResult

    class PrometheusAlertmanagerAdapter(AlertSourceAdapter):
        @property
        def source_name(self) -> str:
            return "prometheus"

        def is_configured(self) -> bool:
            return bool(os.getenv("PROMETHEUS_ALERTMANAGER_URL"))

        def pull(self, *, range_hours: int, batch_size: int, cursor: dict | None) -> AlertSourceResult:
            url = os.environ["PROMETHEUS_ALERTMANAGER_URL"]
            ...
            return AlertSourceResult(signals=signals, next_cursor={"last_run_utc": ...})
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ...schemas.signal import SignalPayload


@dataclass
class AlertSourceResult:
    """Return value from AlertSourceAdapter.pull()."""

    signals: List[SignalPayload]
    next_cursor: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AlertSourceAdapter(ABC):
    """Base class for all Cortex alert source adapters.

    Subclasses must implement ``source_name``, ``is_configured``, and ``pull``.
    The scheduler calls ``pull`` on the configured interval and hands signals
    to Sense for the full closed loop.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier used in signal metadata and pullers UI (e.g. "prometheus")."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the required environment variables / config are present.

        The scheduler skips unconfigured adapters with a warning rather than
        raising an error, so out-of-the-box deployments stay healthy.
        """

    @abstractmethod
    def pull(
        self,
        *,
        range_hours: int,
        batch_size: int,
        cursor: Dict[str, Any] | None,
    ) -> AlertSourceResult:
        """Fetch new alerts since the last run.

        Args:
            range_hours: Fallback window when no cursor exists.
            batch_size: Maximum alerts to fetch per target.
            cursor: Opaque dict from the previous run (may be None on first run).

        Returns:
            AlertSourceResult with signals to ingest and a next_cursor to
            persist for the following run.
        """
