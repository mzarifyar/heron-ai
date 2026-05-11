"""Explainability trace retrieval endpoints.

"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ...schemas.audit import audit_event_to_dict
from ...services.explain import explain_service

router = APIRouter(prefix="/explain", tags=["explain"])
ui_router = APIRouter(tags=["explain-ui"])

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "ui" / "templates"
try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
except AssertionError:
    templates = None


@router.get("/ai-decisions")
def list_ai_decisions(limit: int = Query(default=20, ge=1, le=200)) -> dict:
    """Recent LLM decision events — reasoning, actions, confidence."""
    all_events = explain_service.list_audit_events(limit=500)
    ai_events = [
        audit_event_to_dict(e) for e in all_events
        if getattr(e, "event_type", "") == "decision.llm"
        or (hasattr(e, "component") and getattr(e, "component", "") == "ai.decide")
    ]
    return {"count": len(ai_events[:limit]), "items": ai_events[:limit]}


@router.get("/events")
def list_explain_events(
    correlation_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    """Lists explain events using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    events = explain_service.list_audit_events(correlation_id=correlation_id, limit=limit)
    return {
        "count": len(events),
        "items": [audit_event_to_dict(event) for event in events],
    }


@ui_router.get("/explain", response_class=HTMLResponse, include_in_schema=False)
def explain_ui(request: Request) -> HTMLResponse:
    """Builds explain ui using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    base_url = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    context = {
        "request": request,
        "base_url": base_url,
        "docs_url": "/docs",
        "events_url": "/api/v1/explain/events",
    }
    if templates is not None:
        return templates.TemplateResponse("explain.html", context)
    return HTMLResponse(
        content=(
            "<html><body><h3>Explain UI requires template support.</h3>"
            "<p>Use <code>/api/v1/explain/events</code>.</p></body></html>"
        )
    )