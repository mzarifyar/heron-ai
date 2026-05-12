"""Operations console APIs and UI pages.

"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import yaml

from ...config_control import control_plane_service
from ...core import get_settings
from ...services.cluster_access import cluster_access_service
from ...services.pullers.operator_token import operator_token_manager
from ...services.pullers.scheduler import puller_manager
from ...services.verification import verification_service
from ...services.learn import learn_service

router = APIRouter(prefix="/ops", tags=["ops"])
ui_router = APIRouter(tags=["ops-ui"])

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "ui" / "templates"
try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
except AssertionError:
    templates = None

ROOT_DIR = Path(__file__).resolve().parents[3]

CONFIG_FILES: Dict[str, Path] = {
    "policy": ROOT_DIR / "config" / "policy.yaml",
    "actions": ROOT_DIR / "config" / "actions.yaml",
    "thresholds": ROOT_DIR / "config" / "thresholds.json",
    "control_plane": ROOT_DIR / "config" / "control_plane.json",
}
DEVOPS_TARGETS_PATH = ROOT_DIR / "config" / "devops_portal_targets.json"
CLUSTER_TARGETS_PATH = ROOT_DIR / "config" / "cluster_targets.json"
JIRA_QUERIES_PATH = ROOT_DIR / "config" / "jira_queries.json"
PULLERS_CONFIG_PATH = ROOT_DIR / "config" / "pullers.yaml"


class TextConfigUpdate(BaseModel):
    """Provides TextConfigUpdate behavior using local state or integrations and exposes structured outputs for callers."""
    content: str = Field(min_length=1)


class GuardCheckRequest(BaseModel):
    """Provides GuardCheckRequest behavior using local state or integrations and exposes structured outputs for callers."""
    references: List[str] = Field(default_factory=list)


class SimulateRolloutRequest(BaseModel):
    """Provides SimulateRolloutRequest behavior using local state or integrations and exposes structured outputs for callers."""
    source_env: str
    target_env: str
    service: str


class EscalateChannelIn(BaseModel):
    """Provides EscalateChannelIn behavior using local state or integrations and exposes structured outputs for callers."""
    name: str
    target: str


class EscalateRequestIn(BaseModel):
    """Provides EscalateRequestIn behavior using local state or integrations and exposes structured outputs for callers."""
    service: str
    severity: str
    summary: str
    channels: List[EscalateChannelIn]
    decision_id: str | None = None
    policy_allows: bool = True
    recovered: bool = False
    dedupe_window_seconds: int = 900
    metadata: Dict[str, object] = Field(default_factory=dict)
    dry_run: Optional[bool] = None  # None = let escalation_channels policy decide


class DiscoveryApplyRequest(BaseModel):
    """Provides DiscoveryApplyRequest behavior using local state or integrations and exposes structured outputs for callers."""
    merge_with_existing: bool = True
    include_unknown_accounts: bool = False


class ClusterAccessDiscoverRequest(BaseModel):
    """Provides ClusterAccessDiscoverRequest behavior using local state or integrations and exposes structured outputs for callers."""
    include_government: bool = False
    max_clusters: int = 0
    persist: bool = True


class ClusterAccessValidateRequest(BaseModel):
    """Provides ClusterAccessValidateRequest behavior using local state or integrations and exposes structured outputs for callers."""
    include_government: bool = False
    max_clusters: int = 250
    command_timeout_seconds: int = 25
    clusters: List[str] = Field(default_factory=list)
    persist: bool = True


class ClusterAccessApplyRequest(BaseModel):
    """Provides ClusterAccessApplyRequest behavior using local state or integrations and exposes structured outputs for callers."""
    accessible_only: bool = True
    include_government: bool = False


def _actor_role(request: Request | None) -> str:
    """Builds actor role using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    if request is not None:
        header_role = str(request.headers.get("x-cortex-role") or "").strip().lower()
        if header_role:
            return header_role
    return str(os.getenv("CORTEX_OPERATOR_ROLE") or "viewer").strip().lower() or "viewer"


def _require_devops_admin_write(request: Request | None = None) -> None:
    """Builds require devops admin write using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    role = _actor_role(request)
    if not control_plane_service.is_role_allowed("devops_admin_write", role, ["admin", "sre"]):
        raise HTTPException(status_code=403, detail=f"role '{role}' cannot modify devops admin configuration")


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    """Loads json using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"invalid shape in {path.name}")
    return payload


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    """Saves json using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Loads yaml using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"invalid YAML in {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"invalid shape in {path.name}")
    return payload


def _save_yaml(path: Path, payload: Dict[str, Any]) -> None:
    """Saves yaml using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _validate_json_content(content: str) -> Dict[str, Any]:
    """Validates json content using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        payload = json.loads(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")
    return payload


def _validate_yaml_content(content: str) -> Dict[str, Any]:
    """Validates yaml content using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        payload = yaml.safe_load(content) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a YAML mapping")
    return payload


def _load_pullers_config() -> Dict[str, Any]:
    """Loads pullers config using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not PULLERS_CONFIG_PATH.exists():
        return {"scheduler": {"enabled": True}, "sources": {}}
    try:
        payload = yaml.safe_load(PULLERS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid pullers.yaml: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid pullers.yaml shape")
    return payload


def _save_pullers_config(payload: Dict[str, Any]) -> None:
    """Saves pullers config using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    PULLERS_CONFIG_PATH.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _normalize_jql(jql: str) -> str:
    """Normalizes jql using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return " ".join(jql.strip().split())


@router.get("/runtime")
def get_runtime() -> Dict[str, Any]:
    """Gets runtime using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    settings = get_settings()
    status_payload = puller_manager.status()
    return {
        "app": {
            "name": settings.app_name,
            "environment": settings.environment,
            "region": settings.region,
            "host": settings.api_host,
            "port": settings.api_port,
            "log_level": settings.log_level,
        },
        "health": {"liveness_path": "/healthz", "readiness_path": "/readyz"},
        "pullers": status_payload,
    }


@router.get("/learn/summary")
def learn_summary() -> Dict[str, Any]:
    """Builds learn summary using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return learn_service.summary()


@router.get("/learn/recommendations")
def learn_recommendations(service: str | None = None, severity: str | None = None) -> Dict[str, Any]:
    """Builds learn recommendations using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return learn_service.recommendations(service=service, severity=severity)


@router.get("/operator-token/status")
def operator_token_status() -> Dict[str, Any]:
    """Builds operator token status using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return operator_token_manager.status()


@router.post("/operator-token/refresh")
def operator_token_refresh() -> Dict[str, Any]:
    """Builds operator token refresh using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    token = operator_token_manager.refresh_via_ssh()
    return {
        "refreshed": True,
        "source": token.source,
        "expires_at_utc": token.expires_at_utc,
        "store_path": operator_token_manager.status().get("store_path"),
    }


@router.get("/devops-targets")
def get_devops_targets() -> Dict[str, Any]:
    """Gets devops targets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    payload = _load_json(DEVOPS_TARGETS_PATH, {"targets": []})
    targets = payload.get("targets")
    if not isinstance(targets, list):
        payload["targets"] = []
    return payload


@router.get("/cluster-targets")
def get_cluster_targets() -> Dict[str, Any]:
    """Gets cluster targets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    payload = _load_json(CLUSTER_TARGETS_PATH, {"targets": []})
    targets = payload.get("targets")
    if not isinstance(targets, list):
        payload["targets"] = []
    return payload


@router.put("/cluster-targets")
def put_cluster_targets(update: TextConfigUpdate, request: Request) -> Dict[str, Any]:
    """Builds put cluster targets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    payload = _validate_json_content(update.content)
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise HTTPException(status_code=400, detail="cluster targets must include a 'targets' list")
    for idx, item in enumerate(targets):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"targets[{idx}] must be an object")
        cluster = str(item.get("cluster") or item.get("cluster_name") or "").strip()
        if not cluster:
            raise HTTPException(status_code=400, detail=f"targets[{idx}].cluster is required")
    _save_json(CLUSTER_TARGETS_PATH, payload)
    return {"saved": True, "path": str(CLUSTER_TARGETS_PATH), "count": len(targets)}


@router.put("/devops-targets")
def put_devops_targets(update: TextConfigUpdate, request: Request) -> Dict[str, Any]:
    """Builds put devops targets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    payload = _validate_json_content(update.content)
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise HTTPException(status_code=400, detail="devops targets must include a 'targets' list")
    for idx, item in enumerate(targets):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"targets[{idx}] must be an object")
        if not str(item.get("region") or "").strip():
            raise HTTPException(status_code=400, detail=f"targets[{idx}].region is required")
        if not str(item.get("account_id") or "").strip():
            raise HTTPException(status_code=400, detail=f"targets[{idx}].account_id is required")
    _save_json(DEVOPS_TARGETS_PATH, payload)
    return {"saved": True, "path": str(DEVOPS_TARGETS_PATH), "count": len(targets)}


@router.post("/devops-admin/discover-from-jira")
def discover_devops_from_jira(request: Request) -> Dict[str, Any]:
    """Builds discover devops from jira using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    return puller_manager._devops_puller.discover_from_jira(max_refs=8000, resolve_accounts=True)  # type: ignore[attr-defined]


@router.post("/devops-admin/apply-discovery")
def apply_discovered_targets(payload: DiscoveryApplyRequest, request: Request) -> Dict[str, Any]:
    """Builds apply discovered targets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    discovery = puller_manager._devops_puller.discover_from_jira(max_refs=8000, resolve_accounts=True)  # type: ignore[attr-defined]
    discovered_targets = discovery.get("targets") if isinstance(discovery, dict) else []
    if not isinstance(discovered_targets, list):
        discovered_targets = []
    if not payload.include_unknown_accounts:
        discovered_targets = [
            item
            for item in discovered_targets
            if isinstance(item, dict) and not str(item.get("account_id") or "").startswith("unknown:")
        ]

    existing = _load_json(DEVOPS_TARGETS_PATH, {"targets": []})
    existing_targets = existing.get("targets")
    if not isinstance(existing_targets, list):
        existing_targets = []

    if payload.merge_with_existing:
        merged: Dict[tuple[str, str], Dict[str, Any]] = {}
        for item in [*existing_targets, *discovered_targets]:
            if not isinstance(item, dict):
                continue
            region = str(item.get("region") or "").strip()
            account = str(item.get("account_id") or "").strip()
            if not region or not account:
                continue
            key = (region, account)
            current = merged.get(key)
            if current is None:
                merged[key] = dict(item)
                continue
            existing_ids = {str(v) for v in (current.get("alarm_ids") or []) if isinstance(v, str)}
            incoming_ids = {str(v) for v in (item.get("alarm_ids") or []) if isinstance(v, str)}
            current["alarm_ids"] = sorted(existing_ids | incoming_ids)
            current["labels"] = {**(current.get("labels") or {}), **(item.get("labels") or {})}
            merged[key] = current
        final_targets = list(merged.values())
    else:
        final_targets = [item for item in discovered_targets if isinstance(item, dict)]

    _save_json(DEVOPS_TARGETS_PATH, {"targets": final_targets})
    return {
        "saved": True,
        "path": str(DEVOPS_TARGETS_PATH),
        "targets_count": len(final_targets),
        "discovered_count": len(discovered_targets),
    }


@router.post("/devops-admin/enable-puller")
def enable_devops_puller(request: Request) -> Dict[str, Any]:
    """Builds enable devops puller using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    payload = _load_pullers_config()
    scheduler = payload.get("scheduler")
    if not isinstance(scheduler, dict):
        scheduler = {}
    scheduler["enabled"] = True
    payload["scheduler"] = scheduler
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    devops = sources.get("devops_portal")
    if not isinstance(devops, dict):
        devops = {}
    devops["enabled"] = True
    devops.setdefault("interval_seconds", 300)
    devops.setdefault("range_hours", 24)
    devops.setdefault("batch_size", 200)
    devops.setdefault("jitter_seconds", 5)
    sources["devops_portal"] = devops
    payload["sources"] = sources
    _save_pullers_config(payload)
    puller_manager._refresh_config()  # type: ignore[attr-defined]
    return {"saved": True, "path": str(PULLERS_CONFIG_PATH), "devops_portal": devops}


@router.get("/devops-admin/status")
def devops_admin_status() -> Dict[str, Any]:
    """Builds devops admin status using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    status_payload = puller_manager.status()
    cursors = puller_manager.cursors()
    return {
        "operator_token": operator_token_manager.status(),
        "targets": _load_json(DEVOPS_TARGETS_PATH, {"targets": []}),
        "pullers_status": status_payload,
        "pullers_cursors": cursors,
    }


@router.post("/devops-admin/run-now")
def devops_admin_run_now(request: Request) -> Dict[str, Any]:
    """Builds devops admin run now using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    return puller_manager.run_now(source="devops_portal")


@router.get("/cluster-access/status")
def cluster_access_status() -> Dict[str, Any]:
    """Builds cluster access status using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return cluster_access_service.status()


@router.post("/cluster-access/discover")
def cluster_access_discover(payload: ClusterAccessDiscoverRequest, request: Request) -> Dict[str, Any]:
    """Builds cluster access discover using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    return cluster_access_service.discover(
        include_government=payload.include_government,
        max_clusters=max(0, int(payload.max_clusters or 0)),
        persist=bool(payload.persist),
    )


@router.post("/cluster-access/validate")
def cluster_access_validate(payload: ClusterAccessValidateRequest, request: Request) -> Dict[str, Any]:
    """Builds cluster access validate using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    clusters = [{"cluster": item} for item in payload.clusters if isinstance(item, str) and item.strip()]
    return cluster_access_service.validate(
        clusters=clusters or None,
        include_government=payload.include_government,
        max_clusters=max(1, min(5000, int(payload.max_clusters or 250))),
        command_timeout_seconds=max(5, min(120, int(payload.command_timeout_seconds or 25))),
        persist=bool(payload.persist),
    )


@router.post("/cluster-access/revalidate-auth")
def cluster_access_revalidate_auth(payload: ClusterAccessValidateRequest, request: Request) -> Dict[str, Any]:
    """Re-validates only AWS auth sessions and returns auth status counts (e.g., {"auth_ok":2}), while dependency errors may bubble."""
    _require_devops_admin_write(request)
    clusters = [{"cluster": item} for item in payload.clusters if isinstance(item, str) and item.strip()]
    return cluster_access_service.validate_auth_only(
        clusters=clusters or None,
        include_government=payload.include_government,
        max_clusters=max(1, min(5000, int(payload.max_clusters or 250))),
        persist=bool(payload.persist),
    )

@router.post("/cluster-access/refresh-realm-auth")
def cluster_access_refresh_realm_auth(request: Request) -> Dict[str, Any]:
    """Refreshes per-realm AWS auth board and returns latest realm status (e.g., {"summary":{"ready":1}}), while dependency errors may bubble."""
    _require_devops_admin_write(request)
    return cluster_access_service.refresh_realm_auth_status(auto_refresh_session=True, persist=True)


@router.post("/cluster-access/apply-targets")
def cluster_access_apply_targets(payload: ClusterAccessApplyRequest, request: Request) -> Dict[str, Any]:
    """Builds cluster access apply targets using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    return cluster_access_service.apply_validated_targets(
        accessible_only=bool(payload.accessible_only),
        include_government=bool(payload.include_government),
    )


@router.get("/jira-queries")
def get_jira_queries() -> Dict[str, Any]:
    """Gets jira queries using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    payload = _load_json(JIRA_QUERIES_PATH, {"queries": []})
    queries = payload.get("queries")
    if not isinstance(queries, list):
        payload["queries"] = []
    return payload


@router.put("/jira-queries")
def put_jira_queries(update: TextConfigUpdate, request: Request) -> Dict[str, Any]:
    """Builds put jira queries using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _require_devops_admin_write(request)
    payload = _validate_json_content(update.content)
    queries = payload.get("queries")
    if not isinstance(queries, list):
        raise HTTPException(status_code=400, detail="jira queries must include a 'queries' list")
    _save_json(JIRA_QUERIES_PATH, payload)
    return {"saved": True, "path": str(JIRA_QUERIES_PATH), "count": len(queries)}


@router.post("/jira-queries/dedupe-preview")
def jira_queries_dedupe_preview(update: TextConfigUpdate) -> Dict[str, Any]:
    """Builds jira queries dedupe preview using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    payload = _validate_json_content(update.content)
    queries = payload.get("queries")
    if not isinstance(queries, list):
        raise HTTPException(status_code=400, detail="jira queries must include a 'queries' list")

    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in queries:
        if not isinstance(item, dict):
            continue
        jql = str(item.get("jql") or "").strip()
        if not jql:
            continue
        key = _normalize_jql(jql).lower()
        if key in seen:
            dropped.append(item)
            continue
        seen.add(key)
        kept.append(item)
    return {"kept": kept, "dropped": dropped, "kept_count": len(kept), "dropped_count": len(dropped)}


@router.post("/guard/check")
def guard_check(payload: GuardCheckRequest) -> Dict[str, Any]:
    """Builds guard check using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    refs = [item.strip() for item in payload.references if item and item.strip()]
    if not refs:
        return {"count": 0, "items": []}
    return {"count": len(refs), "items": verification_service.verify_many(refs)}


@router.get("/config/{name}")
def get_config(name: str) -> Dict[str, Any]:
    """Gets config using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if name not in CONFIG_FILES:
        raise HTTPException(status_code=404, detail=f"unknown config: {name}")
    path = CONFIG_FILES[name]
    if path.suffix == ".json":
        payload = _load_json(path, {})
        content = json.dumps(payload, indent=2)
    else:
        payload = _load_yaml(path)
        content = yaml.safe_dump(payload, sort_keys=False)
    return {"name": name, "path": str(path), "content": content}


@router.put("/config/{name}")
def put_config(name: str, update: TextConfigUpdate) -> Dict[str, Any]:
    """Builds put config using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if name not in CONFIG_FILES:
        raise HTTPException(status_code=404, detail=f"unknown config: {name}")
    path = CONFIG_FILES[name]
    if path.suffix == ".json":
        payload = _validate_json_content(update.content)
        _save_json(path, payload)
    else:
        payload = _validate_yaml_content(update.content)
        _save_yaml(path, payload)
    return {"saved": True, "name": name, "path": str(path)}


@router.get("/control-plane")
def get_control_plane() -> Dict[str, Any]:
    """Gets control plane using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    control = control_plane_service.refresh()
    return {
        "version": control.version,
        "regions": [region.__dict__ for region in control.regions],
        "environments": [env.__dict__ for env in control.environments],
        "validation_errors": control_plane_service.validate(),
    }


@router.post("/control-plane/simulate")
def simulate_control_plane(payload: SimulateRolloutRequest) -> Dict[str, Any]:
    """Builds simulate control plane using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    control_plane_service.refresh()
    return control_plane_service.simulate_rollout(
        source_env=payload.source_env,
        target_env=payload.target_env,
        service=payload.service,
    )


@router.post("/escalate")
def run_escalation(payload: EscalateRequestIn) -> Dict[str, Any]:
    """Runs escalation using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    from ...schemas.escalation import EscalationChannel, EscalationRequest
    from ...services.escalate import escalate_service

    request = EscalationRequest(
        service=payload.service,
        severity=payload.severity,
        summary=payload.summary,
        channels=[EscalationChannel(name=item.name, target=item.target) for item in payload.channels],
        decision_id=payload.decision_id,
        policy_allows=payload.policy_allows,
        recovered=payload.recovered,
        dedupe_window_seconds=payload.dedupe_window_seconds,
        metadata=payload.metadata,
    )
    return escalate_service.escalate(request, dry_run=payload.dry_run)


@router.get("/escalate/events")
def list_escalation_events(limit: int = 100) -> Dict[str, Any]:
    """Lists escalation events using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    from ...services.escalate import escalate_service

    items = escalate_service.list_events(limit=limit)
    normalized = []
    for item in items:
        normalized.append(
            {
                "event_id": item.event_id,
                "created_at": item.created_at.isoformat(),
                "message": item.message,
                "severity": item.severity,
                "service": item.service,
                "incident_key": item.incident_key,
                "metadata": item.metadata,
                "channel": {"name": item.channel.name, "target": item.channel.target},
            }
        )
    return {"count": len(items), "items": normalized}


@ui_router.get("/ops/runtime", response_class=HTMLResponse, include_in_schema=False)
def health_ui(request: Request) -> HTMLResponse:
    """Builds health ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Health UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("health_runtime.html", {"request": request})


@ui_router.get("/ops/pullers/targets", response_class=HTMLResponse, include_in_schema=False)
def puller_targets_ui(request: Request) -> HTMLResponse:
    """Builds puller targets ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Puller Targets UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("puller_targets.html", {"request": request})


@ui_router.get("/ops/cluster-targets", response_class=HTMLResponse, include_in_schema=False)
def cluster_targets_ui(request: Request) -> HTMLResponse:
    """Builds cluster targets ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Cluster Targets UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("cluster_targets.html", {"request": request})


@ui_router.get("/ops/jira/queries", response_class=HTMLResponse, include_in_schema=False)
def jira_queries_ui(request: Request) -> HTMLResponse:
    """Builds jira queries ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Jira Queries UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("jira_queries.html", {"request": request})


@ui_router.get("/ops/guard", response_class=HTMLResponse, include_in_schema=False)
def guard_console_ui(request: Request) -> HTMLResponse:
    """Builds guard console ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Guard Console UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("guard_console.html", {"request": request})


@ui_router.get("/ops/config", response_class=HTMLResponse, include_in_schema=False)
def config_studio_ui(request: Request) -> HTMLResponse:
    """Builds config studio ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Config Studio UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("config_studio.html", {"request": request})


@ui_router.get("/ops/control-plane", response_class=HTMLResponse, include_in_schema=False)
def control_plane_ui(request: Request) -> HTMLResponse:
    """Builds control plane ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Control Plane UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("control_plane.html", {"request": request})


@ui_router.get("/ops/escalation", response_class=HTMLResponse, include_in_schema=False)
def escalation_console_ui(request: Request) -> HTMLResponse:
    """Builds escalation console ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Escalation Console UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("escalation_console.html", {"request": request})


@ui_router.get("/ops/learn", response_class=HTMLResponse, include_in_schema=False)
def learn_console_ui(request: Request) -> HTMLResponse:
    """Builds learn console ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Learn Console UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("learn_console.html", {"request": request})


@ui_router.get("/ops/devops", response_class=HTMLResponse, include_in_schema=False)
def devops_admin_ui(request: Request) -> HTMLResponse:
    """Builds devops admin ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>DevOps Admin UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("devops_admin.html", {"request": request})


@ui_router.get("/ops/cluster-access", response_class=HTMLResponse, include_in_schema=False)
def cluster_access_ui(request: Request) -> HTMLResponse:
    """Builds cluster access ui using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if templates is None:
        return HTMLResponse("<html><body><h3>Cluster Access UI requires template support.</h3></body></html>")
    return templates.TemplateResponse("cluster_access.html", {"request": request})


# Legacy UI paths (kept for compatibility/bookmarks)
@ui_router.get("/health", include_in_schema=False)
def health_ui_legacy() -> RedirectResponse:
    """Builds health ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/runtime", status_code=307)


@ui_router.get("/puller-targets", include_in_schema=False)
def puller_targets_ui_legacy() -> RedirectResponse:
    """Builds puller targets ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/pullers/targets", status_code=307)


@ui_router.get("/cluster-targets", include_in_schema=False)
def cluster_targets_ui_legacy() -> RedirectResponse:
    """Builds cluster targets ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/cluster-targets", status_code=307)


@ui_router.get("/jira-queries", include_in_schema=False)
def jira_queries_ui_legacy() -> RedirectResponse:
    """Builds jira queries ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/jira/queries", status_code=307)


@ui_router.get("/guard-console", include_in_schema=False)
def guard_console_ui_legacy() -> RedirectResponse:
    """Builds guard console ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/guard", status_code=307)


@ui_router.get("/config-studio", include_in_schema=False)
def config_studio_ui_legacy() -> RedirectResponse:
    """Builds config studio ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/config", status_code=307)


@ui_router.get("/control-plane", include_in_schema=False)
def control_plane_ui_legacy() -> RedirectResponse:
    """Builds control plane ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/control-plane", status_code=307)


@ui_router.get("/escalation-console", include_in_schema=False)
def escalation_console_ui_legacy() -> RedirectResponse:
    """Builds escalation console ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/escalation", status_code=307)


@ui_router.get("/learn-console", include_in_schema=False)
def learn_console_ui_legacy() -> RedirectResponse:
    """Builds learn console ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/learn", status_code=307)


@ui_router.get("/devops-admin", include_in_schema=False)
def devops_admin_ui_legacy() -> RedirectResponse:
    """Builds devops admin ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/devops", status_code=307)


@ui_router.get("/cluster-access", include_in_schema=False)
def cluster_access_ui_legacy() -> RedirectResponse:
    """Builds cluster access ui legacy using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return RedirectResponse(url="/ops/cluster-access", status_code=307)
