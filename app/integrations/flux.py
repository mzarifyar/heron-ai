"""Flux CD integration — trigger reconciliation via the Flux notification receiver.

When Heron detects post-deploy degradation and the service is managed by Flux,
this integration suspends the HelmRelease/Kustomization (stopping auto-sync)
and optionally triggers a reconcile to a known-good revision.

Setup (.env):
    FLUX_WEBHOOK_URL  = http://flux-receiver.flux-system.svc/hook/<token>
    FLUX_WEBHOOK_TOKEN= <token>           (from Flux Receiver secret)
    FLUX_NAMESPACE    = flux-system       (namespace where Flux runs)
    FLUX_DRY_RUN      = true              (flip to false to go live)

Alternative — kubectl-based (when Flux webhook not configured):
    HERON_KUBE_CLUSTER is enough; Flux objects are managed via kubectl.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict

import requests

from ..core import get_logger

logger = get_logger(__name__)


def _webhook_url() -> str:
    return os.getenv("FLUX_WEBHOOK_URL", "").strip()


def _webhook_token() -> str:
    return os.getenv("FLUX_WEBHOOK_TOKEN", "").strip()


def _namespace() -> str:
    return os.getenv("FLUX_NAMESPACE", "flux-system").strip()


def _is_dry_run() -> bool:
    raw = os.getenv("FLUX_DRY_RUN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _is_configured() -> bool:
    return bool(_webhook_url() or shutil.which("kubectl"))


# ── Webhook reconcile ─────────────────────────────────────────────────────────

def trigger_reconcile(
    resource_name: str,
    resource_kind: str = "kustomization",
    dry_run: bool | None = None,
) -> Dict[str, Any]:
    """Trigger Flux reconciliation via the notification receiver webhook.

    Args:
        resource_name: Name of the HelmRelease or Kustomization.
        resource_kind: 'kustomization' or 'helmrelease'.
        dry_run:       None = read FLUX_DRY_RUN.
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run

    if effective_dry_run:
        return {
            "ok": True, "source": "flux", "resource": resource_name,
            "status": "dry_run", "action": "reconcile",
        }

    url = _webhook_url()
    if url:
        return _reconcile_via_webhook(url, resource_name, resource_kind)
    elif shutil.which("kubectl"):
        return _reconcile_via_kubectl(resource_name, resource_kind)
    else:
        return {
            "ok": False, "source": "flux", "resource": resource_name,
            "status": "error", "error": "Neither FLUX_WEBHOOK_URL nor kubectl configured",
        }


def _reconcile_via_webhook(url: str, name: str, kind: str) -> Dict[str, Any]:
    token = _webhook_token()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["X-Flux-Token"] = token
    try:
        resp = requests.post(
            url,
            headers=headers,
            json={"involvedObject": {"kind": kind.title(), "name": name, "namespace": _namespace()}},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Flux reconcile triggered via webhook: %s/%s", kind, name)
        return {"ok": True, "source": "flux", "resource": name, "status": "triggered", "method": "webhook"}
    except Exception as exc:
        logger.error("Flux webhook reconcile failed for %s: %s", name, exc)
        return {"ok": False, "source": "flux", "resource": name, "status": "error", "error": str(exc)}


def _reconcile_via_kubectl(name: str, kind: str) -> Dict[str, Any]:
    """Fallback: trigger reconciliation using flux CLI or kubectl annotate."""
    ns = _namespace()
    # Try flux CLI first
    if shutil.which("flux"):
        cmd = ["flux", "reconcile", kind, name, "-n", ns]
    else:
        # kubectl annotate to trigger reconciliation
        crd = f"{kind}s.kustomize.toolkit.fluxcd.io" if kind == "kustomization" \
              else f"{kind}s.helm.toolkit.fluxcd.io"
        cmd = [
            "kubectl", "annotate", crd, name,
            f"reconcile.fluxcd.io/requestedAt={os.popen('date -u +%Y-%m-%dT%H:%M:%SZ').read().strip()}",
            "--overwrite", "-n", ns,
        ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = proc.returncode == 0
        logger.info("Flux reconcile via kubectl: %s/%s ok=%s", kind, name, ok)
        return {
            "ok": ok, "source": "flux", "resource": name,
            "status": "triggered" if ok else "error",
            "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip(),
            "method": "kubectl",
        }
    except Exception as exc:
        return {"ok": False, "source": "flux", "resource": name, "status": "error", "error": str(exc)}


# ── Suspend / resume ──────────────────────────────────────────────────────────

def suspend(resource_name: str, kind: str = "kustomization", dry_run: bool | None = None) -> Dict[str, Any]:
    """Suspend a Flux resource to prevent auto-sync during incident remediation."""
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run
    if effective_dry_run:
        return {"ok": True, "source": "flux", "resource": resource_name, "status": "dry_run", "action": "suspend"}

    if not shutil.which("kubectl"):
        return {"ok": False, "source": "flux", "resource": resource_name, "status": "error", "error": "kubectl not found"}

    cmd_flux = ["flux", "suspend", kind, resource_name, "-n", _namespace()]
    cmd_kubectl = ["kubectl", "patch", f"{kind}s.kustomize.toolkit.fluxcd.io" if kind == "kustomization"
                   else f"{kind}s.helm.toolkit.fluxcd.io", resource_name,
                   "--type=merge", "-p", '{"spec":{"suspend":true}}', "-n", _namespace()]

    cmd = cmd_flux if shutil.which("flux") else cmd_kubectl
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"ok": proc.returncode == 0, "source": "flux", "resource": resource_name,
                "status": "suspended" if proc.returncode == 0 else "error",
                "stderr": proc.stderr.strip()}
    except Exception as exc:
        return {"ok": False, "source": "flux", "resource": resource_name, "status": "error", "error": str(exc)}
