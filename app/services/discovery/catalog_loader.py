"""Config catalog loader — merges Heron built-in catalog with customer overrides.

Catalog structure:
    config/discovery/catalog/*.yaml   ← Heron built-ins, never edited by customer
    config/discovery/customer/discovery.yaml  ← Customer overrides + exclusions

The merged result tells the discovery engine what ports/paths to scan for,
what metric exporters to expect, and what to skip.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...core import get_logger

logger = get_logger(__name__)

_CATALOG_DIR = Path(__file__).parents[3] / "config" / "discovery" / "catalog"
_CUSTOMER_FILE = Path(__file__).parents[3] / "config" / "discovery" / "customer" / "discovery.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.debug("Failed to load %s: %s", path, exc)
        return {}


def load_catalog() -> dict[str, Any]:
    """Load and merge all catalog files into one dict."""
    merged: dict[str, Any] = {}
    if not _CATALOG_DIR.exists():
        return merged
    for yaml_file in sorted(_CATALOG_DIR.glob("*.yaml")):
        data = _load_yaml(yaml_file)
        for key, val in data.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
                merged[key].update(val)
            else:
                merged[key] = val
    return merged


def load_customer_config() -> dict[str, Any]:
    """Load customer override file, return empty dict if not present."""
    if not _CUSTOMER_FILE.exists():
        return {}
    return _load_yaml(_CUSTOMER_FILE)


def load_merged_config() -> dict[str, Any]:
    """Return catalog merged with customer overrides."""
    catalog = load_catalog()
    customer = load_customer_config()

    result = dict(catalog)

    # Apply customer overrides on top of catalog entries
    for svc_name, overrides in (customer.get("overrides") or {}).items():
        if svc_name in result.get("services", {}):
            result["services"][svc_name].update(overrides)

    # Add custom services not in catalog
    for custom in (customer.get("custom_services") or []):
        name = custom.get("name", "")
        if name:
            result.setdefault("services", {})[name] = custom

    result["exclusions"] = customer.get("exclusions", {})
    result["scan"] = {**result.get("scan", {}), **customer.get("scan", {})}
    result["environment"] = customer.get("environment", "unknown")
    result["cloud"] = customer.get("cloud", "unknown")

    return result


def save_customer_config(config: dict[str, Any]) -> None:
    """Write or update customer discovery.yaml."""
    try:
        import yaml  # type: ignore
        _CUSTOMER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CUSTOMER_FILE.open("w", encoding="utf-8") as fh:
            yaml.dump(config, fh, default_flow_style=False, sort_keys=False)
        logger.info("Customer discovery config saved to %s", _CUSTOMER_FILE)
    except Exception as exc:
        logger.error("Failed to save customer config: %s", exc)
        raise


def get_port_candidates(service_name: str) -> list[int]:
    """Return default port candidates for a named service from the catalog."""
    catalog = load_catalog()
    svc = (catalog.get("services") or {}).get(service_name, {})
    ports: list[int] = []
    for port_list in (svc.get("default_ports") or {}).values():
        if isinstance(port_list, list):
            ports.extend(int(p) for p in port_list if p)
    exporter = svc.get("metrics_exporter") or {}
    if exporter.get("default_port"):
        ports.append(int(exporter["default_port"]))
    return list(dict.fromkeys(ports))  # dedupe, preserve order
