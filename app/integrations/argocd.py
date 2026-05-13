"""ArgoCD integration — rollback and sync via the ArgoCD REST API.

Used by the Reflex executor when action type is 'argocd_rollback' or
'argocd_sync'.  Heron calls this instead of raw kubectl when an ArgoCD
application manages the service's deployment.

Setup (.env):
    ARGOCD_SERVER_URL = https://argocd.example.com   (no trailing slash)
    ARGOCD_TOKEN      = eyJhbGci...                  (API token from ArgoCD UI)
    ARGOCD_INSECURE   = false                         (set true to skip TLS verify)
    ARGOCD_DRY_RUN    = true                          (flip to false to go live)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests

from ..core import get_logger

logger = get_logger(__name__)


def _base() -> str:
    return os.getenv("ARGOCD_SERVER_URL", "").strip().rstrip("/")


def _token() -> str:
    return os.getenv("ARGOCD_TOKEN", "").strip()


def _verify() -> bool:
    return os.getenv("ARGOCD_INSECURE", "false").lower() not in {"1", "true", "yes"}


def _is_dry_run() -> bool:
    raw = os.getenv("ARGOCD_DRY_RUN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _is_configured() -> bool:
    return bool(_base() and _token())


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def _timeout() -> int:
    return 30


# ── Application lookup ────────────────────────────────────────────────────────

def get_application(app_name: str) -> Optional[Dict[str, Any]]:
    """Fetch ArgoCD application status."""
    if not _is_configured():
        return None
    try:
        resp = requests.get(
            f"{_base()}/api/v1/applications/{app_name}",
            headers=_headers(), verify=_verify(), timeout=_timeout(),
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("ArgoCD get_application(%s) failed: %s", app_name, exc)
        return None


def list_applications() -> list[Dict[str, Any]]:
    """List all ArgoCD applications."""
    if not _is_configured():
        return []
    try:
        resp = requests.get(
            f"{_base()}/api/v1/applications",
            headers=_headers(), verify=_verify(), timeout=_timeout(),
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as exc:
        logger.warning("ArgoCD list_applications failed: %s", exc)
        return []


def find_app_for_service(service: str) -> Optional[str]:
    """Find the ArgoCD application name that manages a given service.

    Checks: app name == service, or metadata label 'heron-service' == service.
    """
    apps = list_applications()
    for app in apps:
        meta = app.get("metadata", {})
        if meta.get("name") == service:
            return service
        labels = meta.get("labels", {}) or {}
        if labels.get("heron-service") == service or labels.get("app") == service:
            return meta.get("name")
    return None


# ── Rollback ──────────────────────────────────────────────────────────────────

def rollback(app_name: str, revision: int = 0, dry_run: bool | None = None) -> Dict[str, Any]:
    """Roll back an ArgoCD application to a previous revision.

    Args:
        app_name: ArgoCD application name.
        revision: History ID to roll back to (0 = previous revision).
        dry_run:  None = read ARGOCD_DRY_RUN.
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run

    if effective_dry_run:
        return {
            "ok": True, "source": "argocd", "app": app_name,
            "status": "dry_run", "action": "rollback",
        }

    if not _is_configured():
        return {
            "ok": False, "source": "argocd", "app": app_name,
            "status": "error", "error": "ARGOCD_SERVER_URL or ARGOCD_TOKEN not configured",
        }

    try:
        resp = requests.post(
            f"{_base()}/api/v1/applications/{app_name}/rollback",
            headers=_headers(),
            json={"id": revision, "prune": False},
            verify=_verify(),
            timeout=_timeout(),
        )
        resp.raise_for_status()
        logger.info("ArgoCD rollback triggered: app=%s revision=%d", app_name, revision)
        return {
            "ok": True, "source": "argocd", "app": app_name,
            "status": "triggered", "action": "rollback",
            "response": resp.json(),
        }
    except Exception as exc:
        logger.error("ArgoCD rollback failed for %s: %s", app_name, exc)
        return {
            "ok": False, "source": "argocd", "app": app_name,
            "status": "error", "error": str(exc),
        }


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync(app_name: str, revision: str = "HEAD", dry_run: bool | None = None) -> Dict[str, Any]:
    """Trigger an ArgoCD sync for an application.

    Args:
        app_name: ArgoCD application name.
        revision: Git revision to sync to (default HEAD).
        dry_run:  None = read ARGOCD_DRY_RUN.
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run

    if effective_dry_run:
        return {
            "ok": True, "source": "argocd", "app": app_name,
            "status": "dry_run", "action": "sync", "revision": revision,
        }

    if not _is_configured():
        return {
            "ok": False, "source": "argocd", "app": app_name,
            "status": "error", "error": "ARGOCD_SERVER_URL or ARGOCD_TOKEN not configured",
        }

    try:
        resp = requests.post(
            f"{_base()}/api/v1/applications/{app_name}/sync",
            headers=_headers(),
            json={"revision": revision, "prune": False, "dryRun": False},
            verify=_verify(),
            timeout=_timeout(),
        )
        resp.raise_for_status()
        logger.info("ArgoCD sync triggered: app=%s revision=%s", app_name, revision)
        return {
            "ok": True, "source": "argocd", "app": app_name,
            "status": "triggered", "action": "sync", "revision": revision,
            "response": resp.json(),
        }
    except Exception as exc:
        logger.error("ArgoCD sync failed for %s: %s", app_name, exc)
        return {
            "ok": False, "source": "argocd", "app": app_name,
            "status": "error", "error": str(exc),
        }
