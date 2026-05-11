"""Control-plane configuration loader and helpers.

"""

from __future__ import annotations
from app.core.paths import config as _cfg

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import json


@dataclass
class ControlRegion:
    """Provides ControlRegion behavior using local state or integrations and exposes structured outputs for callers."""
    name: str
    provider: str
    description: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class ControlEnvironment:
    """Provides ControlEnvironment behavior using local state or integrations and exposes structured outputs for callers."""
    name: str
    region: str
    tier: str
    status: str
    services: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    policy_version: Optional[str] = None


@dataclass
class ControlPlane:
    """Provides ControlPlane behavior using local state or integrations and exposes structured outputs for callers."""
    version: str
    regions: List[ControlRegion] = field(default_factory=list)
    environments: List[ControlEnvironment] = field(default_factory=list)
    authority: Dict[str, List[str]] = field(default_factory=dict)


class ControlPlaneService:
    """Provides ControlPlaneService behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self, config_path: str = _cfg("control_plane.json")) -> None:
        """Initializes instance state using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.config_path = Path(config_path)
        self.control_plane = self._load()

    def _load(self) -> ControlPlane:
        """Loads the request using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not self.config_path.exists():
            return ControlPlane(version="local-default")
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        regions = [
            ControlRegion(
                name=item.get("name", ""),
                provider=item.get("provider", ""),
                description=item.get("description", ""),
                metadata=item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
            )
            for item in payload.get("regions", [])
            if isinstance(item, dict)
        ]
        envs = [
            ControlEnvironment(
                name=item.get("name", ""),
                region=item.get("region", ""),
                tier=item.get("tier", ""),
                status=item.get("status", "unknown"),
                services=item.get("services", []) if isinstance(item.get("services"), list) else [],
                metadata=item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
                policy_version=item.get("policy_version"),
            )
            for item in payload.get("environments", [])
            if isinstance(item, dict)
        ]
        return ControlPlane(
            version=str(payload.get("version", "v1")),
            regions=regions,
            environments=envs,
            authority={
                str(capability): [str(role) for role in (roles or []) if str(role).strip()]
                for capability, roles in (payload.get("authority") or {}).items()
                if isinstance(capability, str) and isinstance(roles, list)
            },
        )

    def refresh(self) -> ControlPlane:
        """Builds refresh using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        self.control_plane = self._load()
        return self.control_plane

    def validate(self) -> List[str]:
        """Validates the request using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        errors: List[str] = []
        region_names = {region.name for region in self.control_plane.regions if region.name}
        if not region_names:
            errors.append("No regions defined")
        for env in self.control_plane.environments:
            if not env.name:
                errors.append("Environment with missing name")
            if env.region not in region_names:
                errors.append(f"Environment '{env.name}' references unknown region '{env.region}'")
            if not env.services:
                errors.append(f"Environment '{env.name}' has no services configured")
        return errors

    def get_environment(self, name: str) -> Optional[ControlEnvironment]:
        """Gets environment using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        for env in self.control_plane.environments:
            if env.name == name:
                return env
        return None

    def is_service_enabled(self, environment: str, service: str) -> bool:
        """Checks service enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        env = self.get_environment(environment)
        if not env:
            return False
        return service in env.services and env.status in {"active", "maintenance"}

    def enabled_services(self, environment: str) -> List[str]:
        """Builds enabled services using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        env = self.get_environment(environment)
        return list(env.services) if env else []

    def simulate_rollout(self, *, source_env: str, target_env: str, service: str) -> Dict[str, object]:
        """Builds simulate rollout using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        src = self.get_environment(source_env)
        dst = self.get_environment(target_env)
        if not src or not dst:
            return {"ok": False, "reason": "unknown_environment"}
        if service not in src.services:
            return {"ok": False, "reason": "service_not_enabled_in_source"}
        already_enabled = service in dst.services
        return {
            "ok": True,
            "source": source_env,
            "target": target_env,
            "service": service,
            "already_enabled": already_enabled,
            "source_status": src.status,
            "target_status": dst.status,
            "recommendation": "no-op" if already_enabled else "enable_after_validation",
        }

    def is_role_allowed(self, capability: str, role: str, default_roles: List[str]) -> bool:
        """Checks role allowed using local reads or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        cap = str(capability or "").strip()
        actor = str(role or "").strip().lower()
        if not cap:
            return False
        allowed = self.control_plane.authority.get(cap)
        if not isinstance(allowed, list) or not allowed:
            allowed = default_roles
        return actor in {str(item).strip().lower() for item in allowed if str(item).strip()}


control_plane_service = ControlPlaneService()
