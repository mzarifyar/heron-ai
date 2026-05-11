"""Expose background job endpoints for alarm verification.

"""

from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from fastapi.templating import Jinja2Templates

from ...services.jobs import job_manager

router = APIRouter(prefix="/sense/jobs", tags=["sense-jobs"])
ui_router = APIRouter(tags=["sense-jobs-ui"])

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "ui" / "templates"
try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
except AssertionError:
    templates = None


class AlarmJobRequest(BaseModel):
    """Provides AlarmJobRequest behavior using local state or integrations and exposes structured outputs for callers."""
    alarms: List[str] = Field(..., min_length=1, max_length=100)


@router.post("/alarm-status", status_code=status.HTTP_202_ACCEPTED)
def start_alarm_status_job(payload: AlarmJobRequest) -> dict:
    """Starts alarm status job using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    job = job_manager.start_alarm_job(payload.alarms)
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "created_at": job["created_at"],
    }


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    """Gets job using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@ui_router.get("/jobs", response_class=HTMLResponse, include_in_schema=False)
def jobs_ui(request: Request) -> HTMLResponse:
    """Builds jobs ui using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    base_url = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    context = {
        "request": request,
        "base_url": base_url,
        "docs_url": "/docs",
        "start_job_url": "/api/v1/sense/jobs/alarm-status",
        "job_url_prefix": "/api/v1/sense/jobs",
    }
    if templates is not None:
        return templates.TemplateResponse("jobs.html", context)
    return HTMLResponse(
        content=(
            "<html><body><h3>Jobs UI requires template support.</h3>"
            "<p>Use <code>/api/v1/sense/jobs/alarm-status</code> and <code>/api/v1/sense/jobs/{job_id}</code>.</p></body></html>"
        )
    )