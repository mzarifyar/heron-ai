"""Background job utilities inspired by the JIRA triage tool.

"""

from __future__ import annotations

import concurrent.futures
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..core import get_logger
from .verification import verification_service

logger = get_logger(__name__)


JOB_RETENTION_SECONDS = 1800  # 30 minutes


class JobManager:
    """Provides JobManager behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def _update_job(self, job_id: str, **fields: Any) -> None:
        """Updates job using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def _set_results(self, job_id: str, index: int, value: Dict[str, Any]) -> None:
        """Sets results using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            job = self._jobs[job_id]
            job["results"][index] = value
            completed = sum(1 for r in job["results"] if r)
            job["progress"] = (completed / len(job["results"])) * 100

    def start_alarm_job(self, references: List[str]) -> Dict[str, Any]:
        """Starts alarm job using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "results": [None for _ in references],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._cleanup_jobs()
        self._executor.submit(self._run_alarm_job, job_id, references)
        logger.info("Started alarm verification job", extra={"job_id": job_id, "items": len(references)})
        return job

    def _run_alarm_job(self, job_id: str, references: List[str]) -> None:
        """Runs alarm job using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._update_job(job_id, status="processing")
        for idx, reference in enumerate(references):
            try:
                result = verification_service.check_reference(reference)
            except Exception as exc:  # pragma: no cover - defensive
                result = {"reference": reference, "status": "UNKNOWN", "error": str(exc)}
            self._set_results(job_id, idx, result)
        self._update_job(job_id, status="completed", progress=100)
        self._cleanup_jobs()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Gets job using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            # Return shallow copy to avoid callers mutating state
            return dict(job)

    def _cleanup_jobs(self) -> None:
        """Builds cleanup jobs using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=JOB_RETENTION_SECONDS)
        to_delete: List[str] = []
        for job_id, data in self._jobs.items():
            created = datetime.fromisoformat(data["created_at"])
            if data.get("status") == "completed" and created < cutoff:
                to_delete.append(job_id)
        for job_id in to_delete:
            self._jobs.pop(job_id, None)


job_manager = JobManager()