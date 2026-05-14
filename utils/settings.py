"""Centralized configuration helpers for Heron runtime.

The heron mode helpers raise ``ValueError`` when the config is malformed and
``FileNotFoundError`` when the file is missing and automatic creation is
disabled. Callers such as :func:`ensure_valid_heron_mode` must be prepared to
surface or handle these exceptions during service bootstrap.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Tuple
import copy
import json
import logging
import os

import threading
from utils.logger import log


def _ensure_section(settings: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Ensures section using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    section = settings.get(name)
    if not isinstance(section, dict):
        section = {}
        settings[name] = section
    return section
def get_processing_mode() -> str:
    """Gets processing mode using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    processing = s.get("processing", {})
    mode = processing.get("mode", _DEFAULTS["processing"]["mode"])
    # Normalize to lowercase and validate
    mode = mode.lower()
    return mode if mode in ("validation", "mitigation") else "validation"



def get_sys_path() -> str:
    """Gets sys path using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    explicit = os.getenv("SYS_PATH", "").strip()
    if explicit:
        return explicit
    # Default to project root derived from this file's location
    return str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SETTINGS_PATH = os.path.join(get_sys_path(), "config", "settings.json")
MODE_CONFIG_ENV_VAR = "HERON_MODE_CONFIG_PATH"
MODE_CONFIG_NAME = "heron_mode.json"
_MODE_DEFAULT: Dict[str, Any] = {"mode": {"active": True, "passive": False}}
_MODE_CACHE: Optional[Dict[str, bool]] = None
_MODE_LOCK = threading.Lock()
MODE_AUTO_CREATE_ENV = "HERON_MODE_AUTO_CREATE"
DEFAULT_INTERVAL_MINUTES = 5
DEFAULT_LABELS = {"during_processing": "processing", "after_processing": "processed"}
DEFAULT_LOG_LEVEL = "info"

_LOGGER = logging.getLogger(__name__)

MAX_CIRCUIT_BREAKER_LIMIT = 500

DEFAULT_JIRA_BASE_URL = "https://your-jira-instance.atlassian.net/rest/api/2"
DEFAULT_MAX_GROUP_MITIGATIONS_PER_HOUR = 0
DEFAULT_MAX_ASSOCIATION_RUNTIME_SECONDS = 0

_DEFAULTS: Dict[str, Any] = {
    "labels": {
        "during_processing": "processing",
        "after_processing": "processed",
    },
    "search": {
        "jql_base": (
            'project = OPS AND issuetype = Incident '
            'AND status not in (Resolved, Closed, Canceled)'
        ),
        "jql_bases": [],
    },
    "scheduler": {
        "interval_minutes": 5
    },
    # Processing configuration
    "processing": {
        "mode": "validation",  # "validation" or "mitigation"
        "max_concurrent_groups": 3
    },
    # Logging configuration
    "logging": {
        "level": "info"
    },
    # Jira configuration
    "jira": {
        "base_url": "https://your-jira-instance.atlassian.net/rest/api/2"
    },
    # Telemetry defaults: disabled by default
 "telemetry": {
        "enabled": False,
        "namespace": "heron",
        "region": "us-ashburn-1",
        "account_id": "",
        "resource_group": "",
        "endpoint": "",
        "max_concurrent_threads": 2,
    },
    "jira_ticketing": {
        "circuit_breaker": {
            "enabled": False,
            "max_tickets_per_run": None,
            "rollup_label": "heron_rollup",
        }
    },
    "processing": {
        "max_concurrent_groups": 3,
        "mode": "active",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Builds deep merge using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    result: Dict[str, Any] = copy.deepcopy(base)
    for key, value in override.items():
        base_value = result.get(key)
        if isinstance(value, dict) and isinstance(base_value, dict):
            result[key] = _deep_merge(base_value, value)
        elif isinstance(value, dict):
            result[key] = copy.deepcopy(value)
        else:
            result[key] = value
    return result


def _load_settings_from_file() -> Dict[str, Any]:
    """Loads settings from file using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    defaults = copy.deepcopy(_DEFAULTS)
    if not os.path.exists(SETTINGS_PATH):
        log("debug", "Settings file not found at {}, using defaults", SETTINGS_PATH)
        return defaults
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh) or {}
        if not isinstance(payload, dict):
            log("warning", "Settings file at {} has unexpected shape; using defaults", SETTINGS_PATH)
            return defaults
        return _deep_merge(defaults, payload)
    except Exception as exc:
        log("error", "Failed to load settings from {}: {}", SETTINGS_PATH, exc)
        return defaults


def _sanitize_circuit_breaker_limit(value: Any, source: str) -> Optional[int]:
    """Builds sanitize circuit breaker limit using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if value in (None, "", False):
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Ignoring circuit breaker limit from %s: expected integer, got %r",
            source,
            value,
        )
        return None
    if coerced <= 0:
        _LOGGER.warning(
            "Circuit breaker limit from %s must be positive; treating as disabled (value=%r)",
            source,
            value,
        )
        return None
    if coerced > MAX_CIRCUIT_BREAKER_LIMIT:
        _LOGGER.warning(
            "Circuit breaker limit from %s (%d) exceeds maximum %d; clamping to %d",
            source,
            coerced,
            MAX_CIRCUIT_BREAKER_LIMIT,
            MAX_CIRCUIT_BREAKER_LIMIT,
        )
        return MAX_CIRCUIT_BREAKER_LIMIT
    return coerced


def _normalize_rollup_label(value: Any, source: str, breaker_enabled: bool) -> str:
    """Normalizes rollup label using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    default_label = _DEFAULTS["jira_ticketing"]["circuit_breaker"]["rollup_label"]
    if not isinstance(value, str):
        message = (
            "Circuit breaker enabled but rollup label from %s is not a string; using default '%s'"
            if breaker_enabled
            else "Rollup label from %s is not a string; using default '%s'"
        )
        _LOGGER.log(logging.ERROR if breaker_enabled else logging.WARNING, message, source, default_label)
        return default_label
    cleaned = value.strip()
    if not cleaned:
        message = (
            "Circuit breaker enabled but rollup label from %s is empty; using default '%s'"
            if breaker_enabled
            else "Rollup label from %s is empty; using default '%s'"
        )
        _LOGGER.log(logging.ERROR if breaker_enabled else logging.WARNING, message, source, default_label)
        return default_label
    return cleaned


def _mode_config_path() -> str:
    """Builds mode config path using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    override = os.getenv(MODE_CONFIG_ENV_VAR)
    if override:
        return override
    root = get_sys_path() or "."
    return os.path.join(root, "config", MODE_CONFIG_NAME)


def _load_mode_config(refresh: bool = False) -> Dict[str, bool]:
    """Loads mode config using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    global _MODE_CACHE
    with _MODE_LOCK:
        if not refresh and _MODE_CACHE is not None:
            return _MODE_CACHE.copy()

        path = _mode_config_path()
        data: Dict[str, Any] = {}

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
            except Exception as exc:
                raise ValueError(f"Failed to load heron mode config at {path}: {exc}") from exc
        else:
            allow_create = os.getenv(MODE_AUTO_CREATE_ENV, "true").lower() in ("1", "true", "yes", "on")
            if not allow_create:
                raise FileNotFoundError(
                    f"Heron mode config missing at {path}. Set {MODE_AUTO_CREATE_ENV}=true to auto-create defaults"
                )

            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(_MODE_DEFAULT, fh, indent=2)
            data = _MODE_DEFAULT

        mode_section = data.get("mode") if isinstance(data, dict) else None
        if not isinstance(mode_section, dict):
            raise ValueError(f"Invalid heron mode config structure in {path}; expected 'mode' object")

        active = bool(mode_section.get("active"))
        passive = bool(mode_section.get("passive"))
        if active == passive:
            raise ValueError(
                f"Invalid heron mode config at {path}: exactly one of mode.active/mode.passive must be true"
            )

        _MODE_CACHE = {"active": active, "passive": passive}
        return _MODE_CACHE.copy()


def get_heron_mode(refresh: bool = False) -> Dict[str, bool]:
    """Gets heron mode using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return _load_mode_config(refresh).copy()


def get_heron_mode_flags(refresh: bool = False) -> Tuple[bool, bool]:
    """Gets heron mode flags using local state or integration calls and returns a tuple result (e.g., ()), may raise ValueError for bad input while dependency errors may bubble."""
    mode = _load_mode_config(refresh)
    return mode["active"], mode["passive"]


def refresh_heron_mode_config() -> Dict[str, bool]:
    """Builds refresh heron mode config using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return get_heron_mode(refresh=True)


def is_active_mode() -> bool:
    """Checks active mode using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
    active, _ = get_heron_mode_flags()
    return active


def is_passive_mode() -> bool:
    """Checks passive mode using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
    _, passive = get_heron_mode_flags()
    return passive


def ensure_valid_heron_mode() -> None:
    """Ensures valid heron mode using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    get_heron_mode()


def _load_settings() -> Dict[str, Any]:
    """Loads settings using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not os.path.exists(SETTINGS_PATH):
        log("debug", "Settings file not found at {}, using defaults", SETTINGS_PATH)
        settings = _DEFAULTS.copy()
    else:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            settings = _deep_merge(_DEFAULTS, data or {})
        except Exception as e:
            log("error", "Failed to load settings from {}: {}", SETTINGS_PATH, e)
            settings = _DEFAULTS.copy()

    return _apply_env_overrides(settings)


def _apply_env_overrides(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Builds apply env overrides using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    merged = copy.deepcopy(settings)

    # Scheduler settings
    if "INTERVAL_MINUTES" in os.environ:
        try:
            merged["scheduler"]["interval_minutes"] = int(os.environ["INTERVAL_MINUTES"])
        except ValueError:
            pass

    labels = _ensure_section(settings, "labels")
    if "PROCESSING_LABEL" in os.environ:
        merged["labels"]["during_processing"] = os.environ["PROCESSING_LABEL"]
    if "PROCESSED_LABEL" in os.environ:
        merged["labels"]["after_processing"] = os.environ["PROCESSED_LABEL"]

    search = _ensure_section(settings, "search")
    if "JQL_BASE" in os.environ:
        merged["search"]["jql_base"] = os.environ["JQL_BASE"]
    if "JQL_BASES" in os.environ:
        raw = os.environ["JQL_BASES"].strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    merged["search"]["jql_bases"] = [str(item).strip() for item in parsed if str(item).strip()]
                else:
                    merged["search"]["jql_bases"] = [item.strip() for item in raw.split("||") if item.strip()]
            except Exception:
                merged["search"]["jql_bases"] = [item.strip() for item in raw.split("||") if item.strip()]

    jira = _ensure_section(settings, "jira")
    if "JIRA_BASE_URL" in os.environ:
        merged["jira"]["base_url"] = os.environ["JIRA_BASE_URL"]

    # Storage settings
    storage_cfg = merged.setdefault("storage", {})
    if "TICKET_CLEANUP_HOURS" in os.environ:
        try:
            storage_cfg["ticket_cleanup_hours"] = int(os.environ["TICKET_CLEANUP_HOURS"])
        except ValueError:
            pass

    processing = _ensure_section(settings, "processing")
    if "PROCESSING_MODE" in os.environ:
        processing["mode"] = os.environ["PROCESSING_MODE"]
    if "PROCESS_RANGE_HOURS" in os.environ:
        try:
            processing["range_hours"] = int(os.environ["PROCESS_RANGE_HOURS"])
        except ValueError:
            pass
    if "MAX_CONCURRENT_GROUPS" in os.environ:
        try:
            processing["max_concurrent_groups"] = int(os.environ["MAX_CONCURRENT_GROUPS"])
        except ValueError:
            pass
    if "MAX_GROUP_MITIGATIONS_PER_HOUR" in os.environ:
        try:
            processing["max_group_mitigations_per_hour"] = int(os.environ["MAX_GROUP_MITIGATIONS_PER_HOUR"])
        except ValueError:
            pass
    if "MAX_ASSOCIATION_RUNTIME_SECONDS" in os.environ:
        try:
            processing["max_association_runtime_seconds"] = int(os.environ["MAX_ASSOCIATION_RUNTIME_SECONDS"])
        except ValueError:
            pass

    logging_cfg = _ensure_section(settings, "logging")
    if "LOG_LEVEL" in os.environ:
        merged["logging"]["level"] = os.environ["LOG_LEVEL"].lower()

    # Telemetry settings
    telemetry_cfg = merged.setdefault("telemetry", {})
    if "TELEMETRY_ENABLED" in os.environ:
        telemetry_cfg["enabled"] = os.environ["TELEMETRY_ENABLED"].lower() in ("true", "1", "yes", "on")
    if "TELEMETRY_NAMESPACE" in os.environ:
        telemetry_cfg["namespace"] = os.environ["TELEMETRY_NAMESPACE"]
    if "TELEMETRY_REGION" in os.environ:
        telemetry_cfg["region"] = os.environ["TELEMETRY_REGION"]
    if "TELEMETRY_account_ID" in os.environ:
        telemetry_cfg["account_id"] = os.environ["TELEMETRY_account_ID"]
    if "TELEMETRY_RESOURCE_GROUP" in os.environ:
        telemetry_cfg["resource_group"] = os.environ["TELEMETRY_RESOURCE_GROUP"]
    if "TELEMETRY_ENDPOINT" in os.environ:
        telemetry_cfg["endpoint"] = os.environ["TELEMETRY_ENDPOINT"]
    if "TELEMETRY_MAX_CONCURRENT_THREADS" in os.environ:
        try:
            telemetry_cfg["max_concurrent_threads"] = int(os.environ["TELEMETRY_MAX_CONCURRENT_THREADS"])
        except ValueError:
            pass
    elif "TELEMETRY_MAX_CONCURRENT_PROCESSES" in os.environ:
        try:
            telemetry_cfg["max_concurrent_threads"] = int(os.environ["TELEMETRY_MAX_CONCURRENT_PROCESSES"])
        except ValueError:
            pass

    api = _ensure_section(settings, "api")
    if "JIRA_TIMEOUT_SECONDS" in os.environ:
        try:
            api["jira_timeout_seconds"] = int(os.environ["JIRA_TIMEOUT_SECONDS"])
        except ValueError:
            pass
    if "JIRA_MAX_RESULTS" in os.environ:
        try:
            api["jira_max_results"] = int(os.environ["JIRA_MAX_RESULTS"])
        except ValueError:
            pass
    if "ACTION_TIMEOUT_SECONDS" in os.environ:
        try:
            api["action_timeout_seconds"] = int(os.environ["ACTION_TIMEOUT_SECONDS"])
        except ValueError:
            pass

    circuit_cfg = merged.setdefault("jira_ticketing", {}).setdefault("circuit_breaker", {})
    if "JIRA_CB_ENABLED" in os.environ:
        circuit_cfg["enabled"] = os.environ["JIRA_CB_ENABLED"].lower() in ("true", "1", "yes", "on")
    if "JIRA_CB_MAX_TICKETS" in os.environ:
        circuit_cfg["max_tickets_per_run"] = _sanitize_circuit_breaker_limit(
            os.environ["JIRA_CB_MAX_TICKETS"], "JIRA_CB_MAX_TICKETS environment variable"
        )
    if "JIRA_CB_ROLLUP_LABEL" in os.environ:
        circuit_cfg["rollup_label"] = os.environ["JIRA_CB_ROLLUP_LABEL"]

    if "PROCESSING_MODE" in os.environ:
        merged.setdefault("processing", {})["mode"] = os.environ["PROCESSING_MODE"].strip()

    return merged


def _initialize_settings() -> Dict[str, Any]:
    """Builds initialize settings using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        settings = _load_settings_from_file()
    except Exception as exc:
        log("error", "Failed to load settings: {}", exc)
        raise
    _apply_env_overrides(settings)
    return settings


def reload_settings() -> Dict[str, Any]:
    """Builds reload settings using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    global _SETTINGS
    _SETTINGS = _initialize_settings()
    return _SETTINGS


def get_settings() -> Dict[str, Any]:
    """Gets settings using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return _SETTINGS


def _get_section(name: str) -> Dict[str, Any]:
    """Gets section using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    section = _SETTINGS.get(name)
    return section if isinstance(section, dict) else {}


def _coerce_int(value: Any, default: int) -> int:
    """Builds coerce int using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_processing_mode() -> str:
    """Gets processing mode using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    processing = _get_section("processing")
    mode = (processing.get("mode") or "validation").lower()
    return mode if mode in ("validation", "mitigation") else "validation"

    # Ticketing / circuit breaker
    circuit_cfg = merged.setdefault("jira_ticketing", {}).setdefault("circuit_breaker", {})
    if "JIRA_CB_ENABLED" in os.environ:
        circuit_cfg["enabled"] = os.environ["JIRA_CB_ENABLED"].lower() in ("true", "1", "yes", "on")
    if "JIRA_CB_MAX_TICKETS" in os.environ:
        circuit_cfg["max_tickets_per_run"] = _sanitize_circuit_breaker_limit(
            os.environ["JIRA_CB_MAX_TICKETS"], "JIRA_CB_MAX_TICKETS environment variable"
        )
    if "JIRA_CB_ROLLUP_LABEL" in os.environ:
        circuit_cfg["rollup_label"] = os.environ["JIRA_CB_ROLLUP_LABEL"]

    # Processing overrides
    processing_cfg = merged.setdefault("processing", {})
    if "PROCESSING_MODE" in os.environ:
        processing_cfg["mode"] = os.environ["PROCESSING_MODE"].strip()

    return merged


def get_labels() -> Dict[str, str]:
    """Gets labels using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    labels = _get_section("labels")
    return {
        "during_processing": labels.get("during_processing", DEFAULT_LABELS["during_processing"]),
        "after_processing": labels.get("after_processing", DEFAULT_LABELS["after_processing"]),
    }


def get_search_jql_base() -> str:
    """Gets search jql base using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    search = _get_section("search")
    jql = search.get("jql_base")
    return jql if isinstance(jql, str) else ""


def get_search_jql_bases() -> list[str]:
    """Gets search jql bases using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
    search = _get_section("search")
    raw = search.get("jql_bases")
    candidates: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())
    if not candidates:
        fallback = get_search_jql_base().strip()
        if fallback:
            candidates.append(fallback)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = " ".join(candidate.lower().split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def get_scheduler_interval_minutes() -> int:
    """Gets scheduler interval minutes using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    sched = s.get("scheduler", {})
    try:
        val = int(sched.get("interval_minutes", _DEFAULTS["scheduler"]["interval_minutes"]))
        return max(1, val)
    except Exception:
        return _DEFAULTS["scheduler"]["interval_minutes"]


def get_telemetry_settings() -> Dict[str, Any]:
    """Gets telemetry settings using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    tel = s.get("telemetry", {})
    merged = copy.deepcopy(_DEFAULTS["telemetry"])
    if isinstance(tel, dict):
        merged.update(tel)
        if "max_concurrent_threads" not in merged and "max_concurrent_processes" in tel:
            merged["max_concurrent_threads"] = tel["max_concurrent_processes"]
    if not merged.get("endpoint") and merged.get("region"):
        merged["endpoint"] = os.getenv("TELEMETRY_ENDPOINT", "")
    return merged


def get_jira_base_url() -> str:
    """Gets jira base url using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    jira = s.get("jira", {})
    return str(jira.get("base_url", _DEFAULTS["jira"]["base_url"]))


def get_jira_timeout_seconds() -> int:
    """Gets jira timeout seconds using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    api = s.get("api", {})
    return int(api.get("jira_timeout_seconds", 20))


def get_jira_max_results() -> int:
    """Gets jira max results using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    api = s.get("api", {})
    return int(api.get("jira_max_results", 100))


def get_action_timeout_seconds() -> int:
    """Gets action timeout seconds using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    api = s.get("api", {})
    return int(api.get("action_timeout_seconds", 3000))


def get_jira_ticketing_settings() -> Dict[str, Any]:
    """Gets jira ticketing settings using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    defaults = _DEFAULTS.get("jira_ticketing", {})
    cfg = s.get("jira_ticketing", {})
    if not isinstance(cfg, dict):
        return copy.deepcopy(defaults)
    return _deep_merge(defaults, cfg)


def get_ticket_circuit_breaker_settings() -> Dict[str, Any]:
    """Gets ticket circuit breaker settings using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    jira_ticketing = get_jira_ticketing_settings()
    defaults = _DEFAULTS["jira_ticketing"]["circuit_breaker"]
    cfg = jira_ticketing.get("circuit_breaker", {})
    merged = _deep_merge(defaults, cfg if isinstance(cfg, dict) else {})

    raw_limit = merged.get("max_tickets_per_run")
    sanitized_limit = _sanitize_circuit_breaker_limit(
        raw_limit,
        "jira_ticketing.circuit_breaker.max_tickets_per_run",
    )
    merged["max_tickets_per_run"] = sanitized_limit

    enabled_flag = bool(merged.get("enabled")) and sanitized_limit is not None
    if merged.get("enabled") and not enabled_flag:
        _LOGGER.warning(
            "Circuit breaker enabled but no valid max_tickets_per_run configured; treating as disabled."
        )
    merged["enabled"] = enabled_flag

    merged["rollup_label"] = _normalize_rollup_label(
        merged.get("rollup_label"),
        "jira_ticketing.circuit_breaker.rollup_label",
        breaker_enabled=enabled_flag,
    )

    return merged


def get_max_concurrent_groups() -> int:
    """Gets max concurrent groups using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    processing = s.get("processing", {})
    try:
        return max(1, int(processing.get("max_concurrent_groups", _DEFAULTS["processing"]["max_concurrent_groups"])))
    except Exception:
        return _DEFAULTS["processing"]["max_concurrent_groups"]


def get_processing_mode() -> str:
    """Gets processing mode using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    processing = s.get("processing", {})
    mode = processing.get("mode", _DEFAULTS["processing"]["mode"])
    if not isinstance(mode, str):
        return _DEFAULTS["processing"]["mode"]
    normalized = mode.strip().lower()
    if normalized not in ("active", "passive", "logging"):
        _LOGGER.warning("Unknown processing mode '%s'; defaulting to 'active'", mode)
        return _DEFAULTS["processing"]["mode"]
    return normalized
def get_processing_range_hours() -> int:
    """Gets processing range hours using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    processing = _get_section("processing")
    return max(0, _coerce_int(processing.get("range_hours", 0), 0))


def get_max_group_mitigations_per_hour() -> int:
    """Gets max group mitigations per hour using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    processing = _get_section("processing")
    return max(0, _coerce_int(processing.get("max_group_mitigations_per_hour", DEFAULT_MAX_GROUP_MITIGATIONS_PER_HOUR), DEFAULT_MAX_GROUP_MITIGATIONS_PER_HOUR))


def get_max_association_runtime_seconds() -> int:
    """Gets max association runtime seconds using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    processing = _get_section("processing")
    return max(0, _coerce_int(processing.get("max_association_runtime_seconds", DEFAULT_MAX_ASSOCIATION_RUNTIME_SECONDS), DEFAULT_MAX_ASSOCIATION_RUNTIME_SECONDS))


def get_max_telemetry_threads() -> int:
    """Gets max telemetry threads using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    telemetry = s.get("telemetry", {})
    raw_value = telemetry.get("max_concurrent_threads", telemetry.get("max_concurrent_processes", 2))
    try:
        return max(1, int(raw_value))
    except Exception:
        return _DEFAULTS["telemetry"]["max_concurrent_threads"]


def get_log_level() -> str:
    """Gets log level using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    logging_config = s.get("logging", {})
    level = logging_config.get("level", _DEFAULTS["logging"]["level"])
    level = str(level).lower()
    return level if level in ("info", "debug") else "info"


def get_ai_settings() -> Dict[str, Any]:
    """Gets ai settings using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    s = _load_settings()
    ai = s.get("ai", {})
    return ai.copy() if isinstance(ai, dict) else {}
def get_settings_path() -> str:
    """Gets settings path using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return SETTINGS_PATH


_SETTINGS = _initialize_settings()
