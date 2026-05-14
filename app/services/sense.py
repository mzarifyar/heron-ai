"""Service logic for Heron Sense (signal ingestion).

"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List

from fastapi import HTTPException, status

from ..core import get_logger, get_settings
from ..schemas.signal import SignalIngestRequest, SignalIngestResponse
from ..store.in_memory import SignalBuffer
from .insight import insight_service
from .explain import explain_service
from .verification import verification_service
from ..db.base import SessionLocal
from ..db.models import Signal as DBSignal

logger = get_logger(__name__)


@dataclass
class IngestResult:
    """Provides IngestResult behavior using local state or integrations and exposes structured outputs for callers."""

    accepted: int
    buffered: int
    dropped: int = 0


class SenseService:
    """Provides SenseService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, buffer: SignalBuffer | None = None) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        settings = get_settings()
        self.buffer = buffer or SignalBuffer(settings.telemetry_buffer_size)
        self._ingest_token = settings.ingest_auth_token

    def _authorize(self, token: str | None) -> None:
        """Builds authorize using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        if self._ingest_token and token != self._ingest_token:
            logger.warning("Unauthorized ingestion attempt")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid ingestion token",
            )

    def ingest(self, request: SignalIngestRequest, token: str | None) -> SignalIngestResponse:
        """Ingests the request using local writes or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        self._authorize(token)
        accepted = 0
        dropped = 0
        for signal in request.signals:
            # Future: include dedupe, validation, normalization hooks
            outcome = verification_service.evaluate(request.context, signal)
            if not outcome.allowed:
                dropped += 1
                logger.info(
                    "Signal dropped by alarm guard",
                    extra={
                        "signal_id": signal.signal_id,
                        "alarm_status": outcome.annotations.get("alarm_status"),
                        "alarm_reference": outcome.annotations.get("alarm_reference"),
                    },
                )
                continue

            logger.debug(
                "Buffering signal",
                extra={
                    "signal_id": signal.signal_id,
                    "service": request.context.service,
                    "environment": request.context.environment,
                },
            )
            buffered_signal = self.buffer.add(request.context, signal, annotations=outcome.annotations)

            # Persist to DB so the Golden Signals baseline engine has history
            try:
                from uuid import uuid4
                with SessionLocal() as db:
                    db.add(DBSignal(
                        id=str(uuid4()),
                        source=request.source,
                        metric_name=signal.details.get("metric_name", signal.summary[:80])
                                    if isinstance(signal.details, dict) else signal.summary[:80],
                        value=signal.metric.value if signal.metric else 0.0,
                        severity=signal.details.get("severity", "info")
                                 if isinstance(signal.details, dict) else "info",
                        service=request.context.service,
                        region=request.context.region,
                        environment=request.context.environment,
                        org_id=request.context.org_id,
                        timestamp=signal.detected_at.replace(tzinfo=None)
                                  if signal.detected_at.tzinfo else signal.detected_at,
                        raw_payload=signal.details if isinstance(signal.details, dict) else {},
                    ))
                    db.commit()
            except Exception as exc:
                logger.debug("Signal DB persist failed (non-critical): %s", exc)

            # Emit to Insight — fail-open
            try:
                insight_service.evaluate(buffered_signal)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Insight evaluation failed during ingest",
                    extra={"signal_id": signal.signal_id, "error": str(exc)},
                )
            accepted += 1

        buffered = len(self.buffer)
        response = SignalIngestResponse(
            accepted=accepted,
            buffered=buffered,
            dropped=dropped,
            message="signals buffered" if accepted else "signals rejected",
        )
        logger.info(
            "Signals ingested",
            extra={
                "accepted": accepted,
                "dropped": dropped,
                "buffered": buffered,
                "source": request.source,
                "ingest_batch_id": str(uuid.uuid4()),
            },
        )
        if accepted:
            explain_service.record_event(
                component="sense",
                event_type="ingest.accepted",
                message="Signals accepted and buffered",
                metadata={
                    "accepted": accepted,
                    "buffered": buffered,
                    "source": request.source,
                    "service": request.context.service,
                    "environment": request.context.environment,
                    "region": request.context.region,
                },
                signal_id=request.signals[0].signal_id if request.signals else None,
            )
        if dropped:
            explain_service.record_event(
                component="sense",
                event_type="ingest.dropped",
                message="Signals dropped by alarm guard",
                metadata={
                    "dropped": dropped,
                    "source": request.source,
                    "service": request.context.service,
                    "environment": request.context.environment,
                    "region": request.context.region,
                },
                signal_id=request.signals[0].signal_id if request.signals else None,
            )
        return response

    def list_recent(self, limit: int = 50) -> List[dict]:
        """Lists recent using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return [signal.dict() for signal in self.buffer.get_recent(limit)]


sense_service = SenseService()