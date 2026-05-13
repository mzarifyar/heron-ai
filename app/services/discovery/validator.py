"""Validates customer discovery.yaml before it's written or activated."""

from __future__ import annotations

from typing import Any


VALID_CLOUDS = {"oci", "aws", "gcp", "azure"}
VALID_ENVIRONMENTS = {"local", "dev", "staging", "prod", "production", "unknown"}


def validate(config: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings. Empty = valid."""
    errors: list[str] = []

    cloud = config.get("cloud", "")
    if cloud and cloud not in VALID_CLOUDS:
        errors.append(f"cloud '{cloud}' is not supported — must be one of: {', '.join(sorted(VALID_CLOUDS))}")

    environment = config.get("environment", "")
    if environment and environment not in VALID_ENVIRONMENTS:
        errors.append(f"environment '{environment}' is unrecognised — expected: {', '.join(sorted(VALID_ENVIRONMENTS))}")

    for svc_name, overrides in (config.get("overrides") or {}).items():
        if not isinstance(overrides, dict):
            errors.append(f"overrides.{svc_name} must be a mapping")

    for custom in (config.get("custom_services") or []):
        if not custom.get("name"):
            errors.append("each custom_service must have a 'name' field")
        if not custom.get("host"):
            errors.append(f"custom_service '{custom.get('name', '?')}' missing 'host'")
        if not custom.get("port"):
            errors.append(f"custom_service '{custom.get('name', '?')}' missing 'port'")

    scan = config.get("scan") or {}
    if "timeout_seconds" in scan:
        try:
            t = int(scan["timeout_seconds"])
            if t < 1 or t > 300:
                errors.append("scan.timeout_seconds must be between 1 and 300")
        except (ValueError, TypeError):
            errors.append("scan.timeout_seconds must be an integer")

    return errors
