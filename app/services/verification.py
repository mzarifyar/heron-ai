"""Alarm verification helpers borrowed from the JIRA triage tool.

"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import get_logger, get_settings
from ..schemas.signal import SignalContext, SignalPayload

logger = get_logger(__name__)


@dataclass
class VerificationOutcome:
    """Provides VerificationOutcome behavior using local state or integrations and exposes structured outputs for callers."""

    allowed: bool
    annotations: Dict[str, Any]


class AlarmVerificationService:
    """Provides AlarmVerificationService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        settings = get_settings()
        self.enabled = settings.alarm_guard_enabled
        self.drop_when_ok = settings.alarm_guard_drop_ok
        self.script_path = Path(settings.alarm_guard_script).resolve()
        self.timeout = settings.alarm_guard_timeout

    def _resolve_reference(self, context: SignalContext, signal: SignalPayload) -> Optional[str]:
        """Resolves reference using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        for candidate in (
            context.labels.get("alarm_url"),
            signal.details.get("alarm_url"),
            signal.details.get("alarm_id"),
        ):
            if candidate:
                return candidate
        return None

    def _format_relative(self, timestamp: Optional[str]) -> Optional[str]:
        """Formats relative using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        if not timestamp:
            return None
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            diff = datetime.now(timezone.utc) - dt
            days = diff.days
            hours, remainder = divmod(diff.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            parts: List[str] = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            return " ".join(parts) or "Just now"
        except Exception:  # pragma: no cover - defensive
            return timestamp

    def _mock_status(self, reference: str) -> Optional[Dict[str, Any]]:
        """Builds mock status using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if reference.startswith("mock://status/"):
            status = reference.split("/", maxsplit=2)[-1].upper()
            return {"status": status, "timestampTriggered": None}
        return None

    def _run_script(self, reference: str) -> Dict[str, Any]:
        """Runs script using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        mocked = self._mock_status(reference)
        if mocked:
            return mocked

        if not self.script_path.exists():
            logger.warning("Alarm guard script missing at %s", self.script_path)
            return {"status": "Unknown", "timestampTriggered": None, "error": "script_missing"}

        cmd = [sys.executable, str(self.script_path), reference]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Alarm guard timed out for %s", reference)
            return {"status": "Unknown", "timestampTriggered": None, "error": "timeout"}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Alarm guard failed for %s: %s", reference, exc)
            return {"status": "Unknown", "timestampTriggered": None, "error": str(exc)}

        if proc.returncode != 0:
            logger.warning("Alarm guard script returned %s for %s", proc.returncode, reference)
            return {"status": "Unknown", "timestampTriggered": None, "error": proc.stderr.strip() or "non_zero_exit"}

        try:
            return json.loads(proc.stdout.strip())
        except json.JSONDecodeError:
            logger.warning("Alarm guard script produced invalid JSON for %s", reference)
            return {"status": "Unknown", "timestampTriggered": None, "error": "invalid_json"}

    def evaluate(self, context: SignalContext, signal: SignalPayload) -> VerificationOutcome:
        """Builds evaluate using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not self.enabled:
            return VerificationOutcome(True, {})

        reference = self._resolve_reference(context, signal)
        if not reference:
            return VerificationOutcome(
                True,
                {
                    "alarm_reference": None,
                    "alarm_status": "Unknown",
                    "alarm_status_reason": "missing_reference",
                },
            )

        result = self._run_script(reference)
        status = (result.get("status") or "Unknown").upper()
        timestamp = result.get("timestampTriggered")
        annotations = {
            "alarm_reference": reference,
            "alarm_status": status,
            "alarm_status_timestamp": timestamp,
            "alarm_status_age": self._format_relative(timestamp),
        }
        if error := result.get("error"):
            annotations["alarm_status_error"] = error

        allowed = True
        if self.drop_when_ok and status == "OK":
            allowed = False
            annotations["alarm_guard_action"] = "dropped_on_ok"

        return VerificationOutcome(allowed, annotations)

    def check_reference(self, reference: str) -> Dict[str, Any]:
        """Checks reference using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        result = self._run_script(reference)
        status = (result.get("status") or "Unknown").upper()
        return {
            "reference": reference,
            "status": status,
            "timestamp": result.get("timestampTriggered"),
            "age": self._format_relative(result.get("timestampTriggered")),
            "error": result.get("error"),
        }

    def verify_many(self, references: List[str]) -> List[Dict[str, Any]]:
        """Builds verify many using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return [self.check_reference(ref) for ref in references]


verification_service = AlarmVerificationService()