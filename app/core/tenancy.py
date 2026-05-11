"""Multi-tenancy utilities.

Cortex uses a lightweight header-based org isolation model. Each inbound HTTP
request may carry an ``X-Org-ID`` header that scopes all signals, incidents,
and Chronicle data to a specific tenant.

For single-tenant deployments the header is optional; everything defaults to
``"default"``.  For multi-tenant deployments set ``CORTEX_REQUIRE_ORG_ID=true``
to reject requests that omit the header.

Usage in FastAPI route handlers::

    from app.core.tenancy import get_org_id

    @router.post("/signals")
    def ingest(request: Request, payload: SignalIngestRequest):
        org_id = get_org_id(request)
        payload.context.org_id = org_id
        ...
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, status

ORG_ID_HEADER = "X-Org-ID"
DEFAULT_ORG_ID = "default"


def _require_org_id() -> bool:
    return os.getenv("CORTEX_REQUIRE_ORG_ID", "false").strip().lower() in {"1", "true", "yes", "on"}


def get_org_id(request: Request) -> str:
    """Extract the tenant org_id from the X-Org-ID header.

    Returns "default" when the header is absent and CORTEX_REQUIRE_ORG_ID is
    false.  Raises HTTP 400 when the header is required but missing.
    """
    org_id = (request.headers.get(ORG_ID_HEADER) or "").strip()
    if not org_id:
        if _require_org_id():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required header: {ORG_ID_HEADER}",
            )
        return DEFAULT_ORG_ID
    return org_id


def validate_org_id(org_id: str) -> str:
    """Normalise and validate an org_id string.  Returns the normalised value."""
    cleaned = org_id.strip().lower()
    if not cleaned:
        return DEFAULT_ORG_ID
    if len(cleaned) > 64 or not all(c.isalnum() or c in "-_." for c in cleaned):
        raise ValueError(f"Invalid org_id '{org_id}': must be alphanumeric/dash/dot, max 64 chars")
    return cleaned
