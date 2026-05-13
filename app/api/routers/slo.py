"""SLO and Runbook API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...core import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/slo", tags=["slo"])


# ── SLO models ────────────────────────────────────────────────────────────────

class SLOCreate(BaseModel):
    service: str
    name: str
    metric_name: str
    target: float                    # e.g. 0.999
    window_days: int = 30
    alert_threshold: float = 0.10
    description: str = ""


# ── SLO endpoints ─────────────────────────────────────────────────────────────

@router.get("")
def list_slos(service: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ...services.slo import list_slos
    items = list_slos(db, service=service)
    return {"items": items, "count": len(items)}


@router.post("")
def create_slo(body: SLOCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ...services.slo import create_slo
    if not 0 < body.target < 1:
        raise HTTPException(status_code=422, detail="target must be between 0 and 1 (e.g. 0.999 for 99.9%)")
    return create_slo(db, service=body.service, name=body.name,
                      metric_name=body.metric_name, target=body.target,
                      window_days=body.window_days, alert_threshold=body.alert_threshold,
                      description=body.description)


@router.delete("/{slo_id}")
def delete_slo(slo_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ...services.slo import delete_slo
    if not delete_slo(db, slo_id):
        raise HTTPException(status_code=404, detail="SLO not found")
    return {"ok": True}


@router.get("/burn")
def burn_all(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Compute burn rate for all SLOs."""
    from ...services.slo import compute_all_burns, seed_default_slos
    # Auto-seed on first call if no SLOs defined
    from ...db.models import ServiceSLO
    from sqlalchemy import select
    if not db.execute(select(ServiceSLO.id).limit(1)).scalar():
        seed_default_slos(db)
    items = compute_all_burns(db)
    alerts = [i for i in items if i.get("alert")]
    return {"items": items, "count": len(items), "alerts": len(alerts)}


@router.get("/{slo_id}/burn")
def burn_single(slo_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ...services.slo import compute_burn
    result = compute_burn(db, slo_id)
    if result is None:
        raise HTTPException(status_code=404, detail="SLO not found")
    return result


@router.get("/{slo_id}/history")
def burn_history(slo_id: str, limit: int = 30, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ...services.slo import get_burn_history
    items = get_burn_history(db, slo_id, limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/seed")
def seed_slos(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Seed default SLOs for all demo services."""
    from ...services.slo import seed_default_slos
    count = seed_default_slos(db)
    return {"seeded": count}


# ── Runbook endpoints ─────────────────────────────────────────────────────────

runbook_router = APIRouter(prefix="/runbooks", tags=["runbooks"])


@runbook_router.post("/index")
def index_runbooks(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Trigger a runbook index from all configured sources."""
    from ...services.runbook_resolver import index_local_runbooks, index_confluence
    local = index_local_runbooks(db)
    confluence = index_confluence(db)
    return {"local": local, "confluence": confluence, "total": local + confluence}


@runbook_router.get("")
def list_runbooks(service: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ...db.models import Runbook
    from sqlalchemy import select
    q = select(Runbook)
    if service:
        q = q.where(Runbook.service == service)
    rows = db.execute(q.order_by(Runbook.title).limit(100)).scalars().all()
    items = [{"id": r.id, "title": r.title, "service": r.service,
              "source": r.source, "url": r.source_url, "tags": r.tags or []}
             for r in rows]
    return {"items": items, "count": len(items)}


@runbook_router.get("/search")
def search_runbooks(
    service: str = "",
    metric: str = "",
    summary: str = "",
    severity: str = "",
    limit: int = 5,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from ...services.runbook_resolver import find_runbooks
    items = find_runbooks(db, service=service, metric_name=metric,
                          summary=summary, severity=severity, limit=limit)
    return {"items": items, "count": len(items)}
