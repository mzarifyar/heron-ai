"""Server-rendered Chronicle UI routes.

"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ...schemas.chronicle import chronicle_to_dict
from ...services.analytics import chronicle_analytics_service
from ...services.chronicle import chronicle_service
from ...services.simulation import what_if_simulation_service

router = APIRouter(tags=["chronicle-ui", "chronicle"])

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "ui" / "templates"
try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
except AssertionError:
    templates = None


def _base_url(request: Request) -> str:
    """Builds base url using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    host = request.headers.get("host", request.url.netloc)
    return f"{request.url.scheme}://{host}"


def _parse_datetime_query(value: str, *, field_name: str) -> datetime:
    """Parses datetime query using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid {field_name} datetime") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@router.get("/chronicle", response_class=HTMLResponse, include_in_schema=False)
def chronicle_ui(request: Request) -> HTMLResponse:
    """Builds chronicle ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    context = {
        "request": request,
        "base_url": _base_url(request),
        "api_base": _base_url(request),
        "docs_url": "/docs",
        "signals_url": "/api/v1/sense/signals",
        "health_url": "/healthz",
        "readiness_url": "/readyz",
        "incidents_url": "/api/v1/chronicle/incidents",
        "timeline_url_prefix": "/api/v1/chronicle/incidents",
        "annotations_url_prefix": "/api/v1/chronicle/incidents",
        "postmortem_url_prefix": "/api/v1/chronicle/incidents",
        "report_summary_url": "/api/v1/chronicle/reports/summary",
        "report_url_prefix": "/api/v1/chronicle/reports",
        "near_miss_url": "/api/v1/chronicle/insights/near-misses",
        "tag_trends_url": "/api/v1/chronicle/insights/tags",
        "pullers_ui_url": "/pullers",
        "sense_ui_url": "/sense",
        "explain_ui_url": "/explain",
        "jobs_ui_url": "/jobs",
    }
    if templates is not None:
        return templates.TemplateResponse("chronicle.html", context)

    # Fallback for environments where Jinja2 is unavailable.
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Cortex Chronicle UI</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      --bg: #ffffff;
      --panel: #f8f9fa;
      --muted: #6c757d;
      --text: #000000;
      --link: #007bff;
      --border: #dee2e6;
      --ok-bg: #d4edda;
      --ok-border: #c3e6cb;
      --ok-text: #155724;
    }}
    html, body {{
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
    .row {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
    .grow {{ flex: 1 1 auto; }}
    .small {{ font-size: 12px; }}
    .muted {{ color: var(--muted); }}
    .code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; background: #eef2f7; border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--ok-border); background: var(--ok-bg); color: var(--ok-text); font-size: 12px; }}
    .stack {{ display: grid; gap: 12px; }}
    .grid {{ width: 100%; border-collapse: collapse; }}
    .grid th, .grid td {{ border-bottom: 1px solid var(--border); text-align: left; padding: 8px 10px; font-size: 13px; vertical-align: top; }}
    .grid th {{ color: var(--muted); font-weight: 600; }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="row">
      <div class="grow">
        <h2 style="margin: 0;">Cortex Chronicle</h2>
      </div>
    </div>
    <div class="panel stack" style="margin-top: 12px;">
      <div><span class="badge">Placeholder</span></div>
      <p style="margin: 0;">
        The production Chronicle experience will render incident timelines, decisions,
        actions, and explainability artifacts surfaced by the Cortex platform.
        For now, this page keeps a lightweight placeholder while the real UI is developed.
      </p>
      <p style="margin: 0;">Refer to <span class="code">docs/chronicle-spec.md</span> for Chronicle design details.</p>
      <table class="grid">
        <thead>
          <tr><th>Surface</th><th>Path</th><th>Purpose</th></tr>
        </thead>
        <tbody>
          <tr><td>Chronicle UI</td><td><span class="code">/chronicle</span></td><td>Server-rendered placeholder page.</td></tr>
          <tr><td>FastAPI Docs</td><td><a href="{context["docs_url"]}">{context["docs_url"]}</a></td><td>Inspect and exercise API routes.</td></tr>
          <tr><td>Signals Endpoint</td><td><a href="{context["signals_url"]}">{context["signals_url"]}</a></td><td>View recent buffered telemetry records.</td></tr>
          <tr><td>Health</td><td><a href="{context["health_url"]}">{context["health_url"]}</a> / <a href="{context["readiness_url"]}">{context["readiness_url"]}</a></td><td>Liveness and readiness probes.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/", include_in_schema=False)
def root_ui_redirect() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@router.get("/camc", response_class=HTMLResponse, include_in_schema=False)
def mission_control_ui(request: Request) -> HTMLResponse:
    """Builds mission control ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    context = {
        "request": request,
        "base_url": _base_url(request),
        "docs_url": "/docs",
        "chronicle_ui_url": "/chronicle",
        "pullers_ui_url": "/pullers",
        "sense_ui_url": "/sense",
        "explain_ui_url": "/explain",
        "jobs_ui_url": "/jobs",
        "health_url": "/healthz",
        "readiness_url": "/readyz",
        "pullers_status_url": "/api/v1/pullers/status",
        "pullers_runs_url": "/api/v1/pullers/runs?limit=8",
        "signals_url": "/api/v1/sense/signals?limit=8",
        "explain_events_url": "/api/v1/explain/events?limit=8",
        "report_summary_url": "/api/v1/chronicle/reports/summary",
        "near_miss_url": "/api/v1/chronicle/insights/near-misses?limit=5",
        "run_jira_url": "/api/v1/pullers/run-now?source=jira",
    }
    if templates is not None:
        return templates.TemplateResponse("mission_control.html", context)
    return HTMLResponse(
        content=(
            "<html><body><h3>Cortex Mission Control requires template support.</h3>"
            "<p>Open <a href='/camc'>/camc</a>, <a href='/chronicle'>/chronicle</a>, or <a href='/pullers'>/pullers</a>.</p></body></html>"
        )
    )


@router.get("/docs-ui", response_class=HTMLResponse, include_in_schema=False)
def docs_ui(request: Request) -> HTMLResponse:
    """Builds docs ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    context = {
        "request": request,
        "base_url": _base_url(request),
        "docs_path": "/docs",
    }
    if templates is not None:
        return templates.TemplateResponse("docs_ui.html", context)
    return HTMLResponse(content="<html><body><a href='/docs'>Open API Docs</a></body></html>")


class AnnotationRequest(BaseModel):
    """Provides AnnotationRequest behavior using local state or integrations and exposes structured outputs for callers."""
    author: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=4000)
    actor_role: str = Field(default="operator")
    tags: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)


class PostmortemUpsertRequest(BaseModel):
    """Provides PostmortemUpsertRequest behavior using local state or integrations and exposes structured outputs for callers."""
    actor_role: str = Field(default="sre")
    template_version: str = Field(default="v1")
    summary: str | None = None
    impact: str | None = None
    root_cause: str | None = None
    timeline_summary: str | None = None
    lessons_learned: list[str] | None = None
    follow_up_actions: list[str] | None = None


class IncidentLinkRequest(BaseModel):
    """Provides IncidentLinkRequest behavior using local state or integrations and exposes structured outputs for callers."""
    linked_incident_id: str = Field(min_length=1)


class SimulationRequest(BaseModel):
    """Provides SimulationRequest behavior using local state or integrations and exposes structured outputs for callers."""
    assumptions: dict[str, object] = Field(default_factory=dict)
    alternate_actions: list[str] = Field(default_factory=list)


@router.get("/api/v1/chronicle/incidents")
def list_chronicle_incidents(
    limit: int = Query(default=100, ge=1, le=1000),
    service: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    region: str | None = Query(default=None),
    started_after: str | None = Query(default=None),
    ended_before: str | None = Query(default=None),
    actor_role: str = Query(default="viewer"),
) -> dict:
    """Lists chronicle incidents using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    parsed_start = _parse_datetime_query(started_after, field_name="started_after") if started_after else None
    parsed_end = _parse_datetime_query(ended_before, field_name="ended_before") if ended_before else None
    try:
        incidents = chronicle_service.list_incidents(
            limit=limit,
            service=service,
            severity=severity,
            region=region,
            started_after=parsed_start,
            ended_before=parsed_end,
            actor_role=actor_role,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"count": len(incidents), "items": [chronicle_to_dict(item) for item in incidents]}


@router.get("/api/v1/chronicle/incidents/{incident_id}")
def get_chronicle_incident(incident_id: str) -> dict:
    """Gets chronicle incident using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    incident = chronicle_service.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    annotations = chronicle_service.list_annotations(incident_id, limit=100)
    postmortem = chronicle_service.get_postmortem(incident_id)
    return {
        "incident": chronicle_to_dict(incident),
        "annotations": [chronicle_to_dict(item) for item in annotations],
        "postmortem": chronicle_to_dict(postmortem) if postmortem else None,
    }


@router.get("/api/v1/chronicle/incidents/{incident_id}/timeline")
def get_chronicle_timeline(
    incident_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    severity: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    started_after: str | None = Query(default=None),
    ended_before: str | None = Query(default=None),
    actor_role: str = Query(default="viewer"),
) -> dict:
    """Gets chronicle timeline using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    incident = chronicle_service.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    parsed_start = _parse_datetime_query(started_after, field_name="started_after") if started_after else None
    parsed_end = _parse_datetime_query(ended_before, field_name="ended_before") if ended_before else None
    try:
        events = chronicle_service.list_timeline(
            incident_id,
            limit=limit,
            actor_role=actor_role,
            severity=severity,
            event_type=event_type,
            started_after=parsed_start,
            ended_before=parsed_end,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"count": len(events), "items": [chronicle_to_dict(item) for item in events]}


@router.post("/api/v1/chronicle/incidents/{incident_id}/annotations")
def add_chronicle_annotation(incident_id: str, payload: AnnotationRequest) -> dict:
    """Builds add chronicle annotation using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        annotation = chronicle_service.add_annotation(
            incident_id,
            author=payload.author,
            note=payload.note,
            actor_role=payload.actor_role,
            tags=payload.tags,
            attachments=payload.attachments,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"item": chronicle_to_dict(annotation)}


@router.put("/api/v1/chronicle/incidents/{incident_id}/postmortem")
def upsert_chronicle_postmortem(incident_id: str, payload: PostmortemUpsertRequest) -> dict:
    """Upserts chronicle postmortem using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        postmortem = chronicle_service.upsert_postmortem(
            incident_id,
            actor_role=payload.actor_role,
            template_version=payload.template_version,
            summary=payload.summary,
            impact=payload.impact,
            root_cause=payload.root_cause,
            timeline_summary=payload.timeline_summary,
            lessons_learned=payload.lessons_learned,
            follow_up_actions=payload.follow_up_actions,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"item": chronicle_to_dict(postmortem)}


@router.get("/api/v1/chronicle/incidents/{incident_id}/postmortem")
def get_chronicle_postmortem(incident_id: str) -> dict:
    """Gets chronicle postmortem using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    item = chronicle_service.get_postmortem(incident_id)
    if item is None:
        raise HTTPException(status_code=404, detail="postmortem not found")
    return {"item": chronicle_to_dict(item)}


@router.post("/api/v1/chronicle/incidents/{incident_id}/links")
def link_chronicle_incidents(incident_id: str, payload: IncidentLinkRequest) -> dict:
    """Builds link chronicle incidents using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        incident = chronicle_service.link_incidents(incident_id, payload.linked_incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": chronicle_to_dict(incident)}


@router.get("/api/v1/chronicle/reports/summary")
def chronicle_reports_summary() -> dict:
    """Builds chronicle reports summary using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return chronicle_service.report_summary()


@router.get("/api/v1/chronicle/reports/{incident_id}")
def get_chronicle_report(incident_id: str) -> dict:
    """Gets chronicle report using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        report = chronicle_service.create_report(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": chronicle_to_dict(report)}


@router.post("/api/v1/chronicle/incidents/{incident_id}/simulations/what-if")
def run_what_if_simulation(incident_id: str, payload: SimulationRequest) -> dict:
    """Runs what if simulation using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        result = what_if_simulation_service.simulate_incident(
            incident_id,
            assumptions=payload.assumptions,
            alternate_actions=payload.alternate_actions,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": chronicle_to_dict(result)}


@router.get("/api/v1/chronicle/insights/near-misses")
def list_near_miss_insights(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    """Lists near miss insights using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return chronicle_analytics_service.near_miss_report(limit=limit)


@router.get("/api/v1/chronicle/insights/tags")
def list_tag_insights(limit: int = Query(default=500, ge=1, le=2000)) -> dict:
    """Lists tag insights using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return chronicle_analytics_service.tag_trends(limit=limit)

# ── Semantic Search ────────────────────────────────────────────────────────────

@router.get("/api/v1/chronicle/search")
def search_chronicle(
    q: str = "",
    limit: int = Query(default=10, ge=1, le=50),
    semantic: bool = True,
    service: str = "",
    severity: str = "",
    status: str = "",
) -> dict:
    """Search Chronicle incident history using BM25 + optional semantic reranking.

    q: natural language query (e.g. "connection pool payment processor")
    semantic: set false to use BM25 only (faster, no AI required)
    service / severity / status: optional exact-match filters
    """
    from ...services.chronicle_search import chronicle_search
    filters = {k: v for k, v in {"service": service, "severity": severity, "status": status}.items() if v}
    results = chronicle_search.search(q, limit=limit, semantic=semantic, filters=filters or None)
    return {"query": q, "results": results, "count": len(results)}


@router.post("/api/v1/chronicle/search/rebuild")
def rebuild_search_index() -> dict:
    """Force a full rebuild of the Chronicle search index."""
    from ...services.chronicle_search import chronicle_search
    count = chronicle_search.rebuild()
    return {"ok": True, "doc_count": count}


@router.get("/api/v1/chronicle/search/status")
def search_index_status() -> dict:
    """Return Chronicle search index status."""
    from ...services.chronicle_search import chronicle_search
    return chronicle_search.status()
