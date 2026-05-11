"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe")
def healthcheck() -> dict:
    """Liveness probe — returns db status alongside ok."""
    db_ok = True
    try:
        from ...db.base import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok", "db": "ok" if db_ok else "error"}


@router.get("/readyz", summary="Readiness probe")
def readiness() -> dict[str, str]:
    """Readiness probe."""
    return {"status": "ready"}
