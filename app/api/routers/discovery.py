"""Discovery API — cloud infrastructure inventory, coverage map, and activation.

Endpoints:
  POST /api/v1/discovery/connect     — start a scan (async via background task)
  GET  /api/v1/discovery/status      — latest scan status + progress
  GET  /api/v1/discovery/report      — full resource coverage map
  POST /api/v1/discovery/activate    — write customer config, enable monitoring
  GET  /api/v1/discovery/catalog     — merged catalog + customer overrides
  POST /api/v1/discovery/config      — save customer discovery.yaml overrides
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import DiscoveryScan
from ...services.discovery.catalog_loader import (
    load_merged_config, load_customer_config, save_customer_config,
)
from ...services.discovery.validator import validate
from ...core import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/discovery", tags=["discovery"])

# In-process lock so only one scan runs at a time
_scan_lock = threading.Lock()


# ── Request / response models ──────────────────────────────────────────────

class ConnectRequest(BaseModel):
    cloud: str = "oci"          # oci | aws | gcp | azure
    region: str = ""
    compartment_id: str = ""    # OCI only
    demo: bool = False           # force demo scan regardless of credentials


class ConfigRequest(BaseModel):
    config: dict[str, Any]


class ActivateRequest(BaseModel):
    scan_id: str
    resource_ids: list[str] = []   # empty = activate all monitored/partial


# ── Background scan ────────────────────────────────────────────────────────

def _run_scan(scan_id: str, cloud: str, region: str, compartment_id: str, demo: bool) -> None:
    from ...db.base import SessionLocal
    if cloud == "aws":
        from ...services.discovery.aws.inventory import run_scan
    else:
        from ...services.discovery.oci.inventory import run_scan

    with SessionLocal() as db:
        scan = db.get(DiscoveryScan, scan_id)
        if not scan:
            return
        scan.status = "scanning"
        db.commit()

    try:
        result = run_scan(region=region, compartment_id=compartment_id, demo=demo)
        resources = [r.to_dict() for r in result.resources]

        with SessionLocal() as db:
            scan = db.get(DiscoveryScan, scan_id)
            if scan:
                scan.status = "done"
                scan.finished_at = datetime.utcnow()
                scan.resource_count = len(result.resources)
                scan.monitored_count = len(result.monitored)
                scan.unmonitored_count = len(result.unmonitored)
                scan.resources = resources
                db.commit()
    except Exception as exc:
        logger.error("Discovery scan %s failed: %s", scan_id, exc)
        with SessionLocal() as db:
            scan = db.get(DiscoveryScan, scan_id)
            if scan:
                scan.status = "error"
                scan.error = str(exc)
                scan.finished_at = datetime.utcnow()
                db.commit()
    finally:
        _scan_lock.release()


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/connect")
def start_scan(
    req: ConnectRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start a cloud infrastructure discovery scan.

    Returns immediately with a scan_id.  Poll GET /status for progress.
    """
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A scan is already running. Try again shortly.")

    scan = DiscoveryScan(
        id=str(uuid4()),
        cloud=req.cloud,
        status="pending",
        started_at=datetime.utcnow(),
        config_used={"cloud": req.cloud, "region": req.region, "demo": req.demo},
    )
    db.add(scan)
    db.commit()

    background_tasks.add_task(
        _run_scan, scan.id, req.cloud, req.region, req.compartment_id, req.demo
    )
    return {"ok": True, "scan_id": scan.id, "status": "pending"}


@router.get("/status")
def scan_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the latest scan status."""
    scan = (
        db.query(DiscoveryScan)
        .order_by(DiscoveryScan.started_at.desc())
        .first()
    )
    if not scan:
        return {"status": "no_scan", "scan_id": None}
    return {
        "scan_id": scan.id,
        "cloud": scan.cloud,
        "status": scan.status,
        "started_at": scan.started_at.isoformat(),
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        "resource_count": scan.resource_count,
        "monitored_count": scan.monitored_count,
        "unmonitored_count": scan.unmonitored_count,
        "error": scan.error,
    }


@router.get("/report")
def coverage_report(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the full resource coverage map from the latest completed scan."""
    scan = (
        db.query(DiscoveryScan)
        .filter(DiscoveryScan.status == "done")
        .order_by(DiscoveryScan.started_at.desc())
        .first()
    )
    if not scan:
        return {"scan_id": None, "resources": [], "summary": {}}

    resources = scan.resources or []
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in resources:
        by_type[r.get("resource_type", "?")] = by_type.get(r.get("resource_type", "?"), 0) + 1
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1

    return {
        "scan_id": scan.id,
        "cloud": scan.cloud,
        "scanned_at": scan.started_at.isoformat(),
        "resources": resources,
        "summary": {
            "total": len(resources),
            "by_status": by_status,
            "by_type": by_type,
        },
    }


@router.post("/activate")
def activate(req: ActivateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Confirm the discovered resources and enable monitoring.

    Writes/updates the customer discovery.yaml and marks the scan as activated.
    """
    scan = db.get(DiscoveryScan, req.scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status != "done":
        raise HTTPException(status_code=400, detail=f"Scan is not complete (status={scan.status})")

    resources = scan.resources or []
    activated = (
        [r for r in resources if r["id"] in req.resource_ids]
        if req.resource_ids
        else [r for r in resources if r["status"] in ("monitored", "partial")]
    )

    # Update customer config to record which resources are activated
    cfg = load_customer_config()
    cfg["cloud"] = scan.cloud
    cfg["_activated_scan_id"] = req.scan_id
    cfg["_activated_at"] = datetime.utcnow().isoformat()
    cfg["_activated_resource_count"] = len(activated)
    save_customer_config(cfg)

    scan.status = "activated"
    db.commit()

    logger.info("Discovery scan %s activated: %d resources enabled", req.scan_id, len(activated))
    return {
        "ok": True,
        "activated": len(activated),
        "cloud": scan.cloud,
        "message": f"Monitoring enabled for {len(activated)} resources.",
    }


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    """Return the merged catalog + customer overrides."""
    return load_merged_config()


@router.post("/config")
def update_config(req: ConfigRequest) -> dict[str, Any]:
    """Validate and save customer discovery.yaml overrides."""
    errors = validate(req.config)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    save_customer_config(req.config)
    return {"ok": True, "message": "Customer config saved."}
