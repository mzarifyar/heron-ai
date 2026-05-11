"""Signal ingestion routes for Cortex Sense.

"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ...core.tenancy import get_org_id
from ...schemas.signal import SignalIngestRequest, SignalIngestResponse
from ...services.sense import sense_service

router = APIRouter(prefix="/sense", tags=["sense"])
ui_router = APIRouter(tags=["sense-ui"])

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "ui" / "templates"
try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
except AssertionError:
    templates = None


def get_authorization_header(authorization: str | None = Header(default=None)) -> str | None:
    """Gets authorization header using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return authorization


@router.post(
    "/signals",
    response_model=SignalIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest signals from external collectors/pullers",
)
async def ingest_signals(
    http_request: Request,
    request: SignalIngestRequest,
    token: str | None = Depends(get_authorization_header),
) -> JSONResponse:
    """Ingests signals using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    org_id = get_org_id(http_request)
    request.context.org_id = org_id
    response = sense_service.ingest(request, token)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=response.dict())


@router.get(
    "/signals",
    summary="List recently ingested signals",
)
async def list_recent_signals(limit: int = 20) -> dict[str, object]:
    """Lists recent signals using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    recent = sense_service.list_recent(limit)
    return {"items": recent, "limit": limit, "count": len(recent)}


@ui_router.get("/sense", response_class=HTMLResponse, include_in_schema=False)
def sense_ui(request: Request) -> HTMLResponse:
    """Builds sense ui using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    base_url = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    context = {
        "request": request,
        "base_url": base_url,
        "docs_url": "/docs",
        "list_url": "/api/v1/sense/signals",
        "ingest_url": "/api/v1/sense/signals",
    }
    if templates is not None:
        return templates.TemplateResponse("sense.html", context)
    return HTMLResponse(
        content=(
            "<html><body><h3>Sense UI requires template support.</h3>"
            "<p>Use <code>/api/v1/sense/signals</code> for list/ingest.</p></body></html>"
        )
    )