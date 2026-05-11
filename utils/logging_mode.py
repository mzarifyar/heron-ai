"""Utilities for Cortex logging-only (dry run) mode."""
from __future__ import annotations

import atexit
import io
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.integrations.object_storage_uploader import ObjectStorageUploader
from utils.settings import get_sys_path, is_passive_mode
from utils.logger import debug_log  # lightweight telemetry substitute

try:  # pragma: no cover
    from app.integrations.telemetry import log_health
except Exception:  # pragma: no cover
    log_health = None

CONFIG_ENV_VAR = "CORTEX_LOGGING_CONFIG_PATH"
DEFAULT_CONFIG_NAME = "logging_mode.json"
OBJECT_STORAGE_CONFIG_NAME = "object_storage.json"
LOCAL_OBJECT_STORAGE_SECRETS = os.path.join("local", "object_storage_secrets.json")
LOGGING_AUTO_CREATE_ENV = "CORTEX_LOGGING_AUTO_CREATE"

_DEFAULT_CONFIG: Dict[str, Any] = {
    "logging_mode_enabled": False,
    "environment": "unknown",
    "log_file_path": "/logs/runit/caa-cortex/cortex_activity.log",
    "redaction_patterns": [],
    "object_storage": {
        "enabled": False,
        "namespace": "",
        "bucket_name": "",
        "region": "",
        "bucket_awsd": "",
        "account": "",
        "upload_mode": "sdk",
        "object_prefix": "cortex/logging/",
        "object_name_format": "cortex_activity_{yyyyMMdd}.log",
        "endpoint_override": "",
        "par_base_url_primary": "",
        "par_base_url_secondary": "",
        "pre_auth_request_id": "",
        "max_retry_attempts": 5
    },
    "upload_schedule": {
        "enabled": False,
        "frequency_minutes": 60
    }
}

SENSITIVE_KEYS = {
    "token",
    "authorization",
    "password",
    "secret",
    "api_key",
    "par_base_url",
    "pre_auth_request",
    "bearer",
    "session",
    "cookie",
    "auth",
}

DEFAULT_REDACTION_PATTERNS = [
    {"type": "substring", "value": "Bearer "},
    {"type": "substring", "value": "https://objectstorage"},
]

_config_cache: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()
_logger_instance: Optional["ActivityLogger"] = None
_logger_lock = threading.Lock()
_uploader_instance: Optional[ObjectStorageUploader] = None
_uploader_lock = threading.Lock()
_upload_thread: Optional[threading.Thread] = None
_upload_lock = threading.Lock()


def _config_path() -> str:
    """Builds config path using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    override = os.getenv(CONFIG_ENV_VAR)
    if override:
        return override
    root = get_sys_path() or "."
    return os.path.join(root, "config", DEFAULT_CONFIG_NAME)


def _config_dir() -> str:
    """Builds config dir using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    root = get_sys_path() or "."
    return os.path.join(root, "config")


def _load_json_if_exists(path: str) -> Optional[Dict[str, Any]]:
    """Loads json if exists using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        debug_log("Failed to load supplemental config %s: %s", os.path.basename(path), exc)
    return None


def _merge_section(cfg: Dict[str, Any], data: Optional[Dict[str, Any]], *, key: str, allow_flat: bool = False) -> None:
    """Merges section using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    if not data:
        return
    section: Optional[Dict[str, Any]] = None
    if isinstance(data, dict):
        if key in data and isinstance(data[key], dict):
            section = data[key]
        elif allow_flat:
            section = data
    if section:
        cfg.setdefault(key, {}).update(section)
    elif allow_flat:
        debug_log("Supplemental config for %s is not a dict; ignoring unexpected shape", key)


def load_logging_mode_config(refresh: bool = False) -> Dict[str, Any]:
    """Loads logging mode config using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    global _config_cache
    if not refresh and _config_cache is not None:
        return _config_cache

    path = _config_path()
    cfg = json.loads(json.dumps(_DEFAULT_CONFIG))
    auto_create_allowed = os.getenv(LOGGING_AUTO_CREATE_ENV, "true").lower() not in ("0", "false", "no", "off")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                cfg.update(data)
                if isinstance(data.get("object_storage"), dict):
                    cfg["object_storage"].update(data["object_storage"])
                if isinstance(data.get("upload_schedule"), dict):
                    cfg["upload_schedule"].update(data["upload_schedule"])
                if isinstance(data.get("redaction_patterns"), list) and data["redaction_patterns"]:
                    cfg["redaction_patterns"] = data["redaction_patterns"]
        except Exception as exc:
            print(f"[logging_mode] Failed to load config {path}: {exc}")
    else:
        if not auto_create_allowed:
            raise FileNotFoundError(
                f"Logging mode config missing at {path}. Set {LOGGING_AUTO_CREATE_ENV}=true to allow auto-creation."
            )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)

    config_dir = _config_dir()
    supplemental_files = [
        os.path.join(config_dir, OBJECT_STORAGE_CONFIG_NAME),
        os.path.join(config_dir, LOCAL_OBJECT_STORAGE_SECRETS),
    ]
    for supplemental_path in supplemental_files:
        supplemental = _load_json_if_exists(supplemental_path)
        _merge_section(cfg, supplemental, key="object_storage", allow_flat=True)
        _merge_section(cfg, supplemental, key="upload_schedule", allow_flat=False)

    if not cfg.get("redaction_patterns"):
        cfg["redaction_patterns"] = list(DEFAULT_REDACTION_PATTERNS)

    if is_passive_mode():
        cfg["logging_mode_enabled"] = True
    _config_cache = cfg
    return cfg


def refresh_logging_mode_config() -> Dict[str, Any]:
    """Builds refresh logging mode config using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return load_logging_mode_config(refresh=True)


def is_logging_mode_enabled() -> bool:
    """Checks logging mode enabled using local reads or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
    return bool(load_logging_mode_config().get("logging_mode_enabled"))


def _redact_dict(data: Dict[str, Any], patterns: list) -> Dict[str, Any]:
    """Builds redact dict using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    redacted: Dict[str, Any] = {}
    for key, value in data.items():
        lowered = str(key).lower()
        if any(secret in lowered for secret in SENSITIVE_KEYS):
            redacted[key] = "***"
            continue
        redacted[key] = redact_payload(value, patterns)
    return redacted


def redact_payload(payload: Any, patterns: Optional[list] = None) -> Any:
    """Builds redact payload using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if patterns is None:
        patterns = load_logging_mode_config().get("redaction_patterns", [])
    if isinstance(payload, dict):
        return _redact_dict(payload, patterns)
    if isinstance(payload, list):
        return [redact_payload(item, patterns) for item in payload]
    if isinstance(payload, (tuple, set)):
        return [redact_payload(item, patterns) for item in payload]
    if isinstance(payload, str):
        for pattern in patterns:
            if pattern.get("type") == "substring" and pattern.get("value"):
                payload = payload.replace(pattern["value"], "***")
        return payload
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    if isinstance(payload, bytes):
        try:
            decoded = payload.decode("utf-8", errors="replace")
        except Exception:
            decoded = repr(payload)
        return redact_payload(decoded, patterns)
    return payload


@dataclass
class ActivityLogger:
    """Provides ActivityLogger behavior using local state or integrations and exposes structured outputs for callers."""
    config: Dict[str, Any]
    log_file_path: str = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _fh: Optional[io.TextIOWrapper] = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Handles post init protocol behavior using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.log_file_path = self.config.get("log_file_path") or _DEFAULT_CONFIG["log_file_path"]
        self._ensure_logfile()
        self._open_handle()
        atexit.register(self.close)

    def _ensure_logfile(self) -> None:
        """Ensures logfile using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        directory = os.path.dirname(self.log_file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
            try:
                os.chmod(directory, 0o750)
            except PermissionError:
                pass
        if not os.path.exists(self.log_file_path):
            fd = os.open(self.log_file_path, os.O_CREAT | os.O_WRONLY, 0o640)
            os.close(fd)
        try:
            os.chmod(self.log_file_path, 0o640)
        except PermissionError:
            pass

    def append(self, record: Dict[str, Any]) -> None:
        """Builds append using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        payload = redact_payload(record)
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            if self._fh is None:
                self._open_handle()
            if self._fh is not None:
                self._fh.write(line + "\n")
                self._fh.flush()

    def _open_handle(self) -> None:
        """Builds open handle using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        try:
            self._fh = open(self.log_file_path, "a", encoding="utf-8", buffering=1)
        except Exception as exc:
            print(f"[logging_mode] Failed to open activity log handle: {exc}")
            self._fh = None

    def close(self) -> None:
        """Builds close using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None


def get_activity_logger() -> Optional[ActivityLogger]:
    """Gets activity logger using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    global _logger_instance
    if not is_logging_mode_enabled():
        return None
    with _logger_lock:
        if _logger_instance is None:
            _logger_instance = ActivityLogger(load_logging_mode_config())
    return _logger_instance


def build_base_record(ticket: Dict[str, Any], *, environment: str, mode: str = "logging") -> Dict[str, Any]:
    """Builds base record using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    now = datetime.now(timezone.utc).isoformat()
    key = ticket.get("key") or ""
    issue_id = ticket.get("id")
    base_url = ticket.get("url_base", "")
    url = ticket.get("url")
    if not url and key and base_url:
        url = f"{base_url.rstrip('/')}/{key}"
    return {
        "timestamp": now,
        "service": "cortex",
        "environment": environment,
        "mode": mode,
        "ticket": {
            "key": key,
            "id": issue_id,
            "url": url,
        },
        "matched_dvm": None,
        "ai": None,
        "knowledge_base": None,
        "planned_jira_actions": [],
        "execution": {
            "executed": False,
            "reason": "logging_mode_enabled"
        },
        "correlation_id": ticket.get("correlation_id")
    }


def record_planned_action(record: Optional[Dict[str, Any]], action_type: str, payload: Any) -> None:
    """Records planned action using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    if record is None:
        debug_log("Dropping planned action %s due to missing activity record", action_type)
        return
    record.setdefault("planned_jira_actions", []).append({
        "type": action_type,
        "payload": payload,
    })


def add_operation(record: Optional[Dict[str, Any]], operation: Dict[str, Any]) -> None:
    """Builds add operation using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    if record is None:
        debug_log("Dropping operation %s due to missing activity record", operation.get("type"))
        return
    record.setdefault("operations", []).append(operation)


def _get_uploader(cfg: Dict[str, Any]) -> Optional[ObjectStorageUploader]:
    """Gets uploader using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    global _uploader_instance
    object_cfg = cfg.get("object_storage") or {}
    schedule_cfg = cfg.get("upload_schedule") or {}
    if not (object_cfg.get("enabled") and schedule_cfg.get("enabled")):
        return None
    with _uploader_lock:
        if _uploader_instance is None:
            _uploader_instance = ObjectStorageUploader(cfg)
        else:
            _uploader_instance.update_config(cfg)
        return _uploader_instance


def _start_upload_thread(uploader: ObjectStorageUploader, file_path: str) -> None:
    """Starts upload thread using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    global _upload_thread

    def _run() -> None:
        """Runs the request using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        try:
            uploader.upload(file_path, background=True)
        except Exception as exc:  # pragma: no cover
            print(f"[logging_mode] Upload thread error: {exc}")

    thread = threading.Thread(target=_run, name="cortex-log-upload", daemon=True)
    _upload_thread = thread
    thread.start()


def upload_logs_if_due(*, background: bool = True, refresh_config: bool = False) -> bool:
    """Builds upload logs if due using local reads or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
    cfg = load_logging_mode_config(refresh=refresh_config)
    log_path = cfg.get("log_file_path") or _DEFAULT_CONFIG["log_file_path"]
    uploader = _get_uploader(cfg)
    if uploader is None:
        return False
    if not uploader.should_upload() or not uploader.due_for_upload():
        return False
    if not os.path.exists(log_path):
        print(f"[logging_mode] Activity log file {log_path} missing; skipping upload trigger")
        if log_health:
            try:
                log_health("cortex_logging_activity_file_missing", False, module="logging_mode", status="DOWN", state="missing")
            except Exception:
                pass
        return False

    if background:
        with _upload_lock:
            if _upload_thread and _upload_thread.is_alive():
                return False
            _start_upload_thread(uploader, log_path)
    else:
        uploader.upload(log_path, background=False)
    return True


def reset_upload_schedule() -> None:
    """Resets upload schedule using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    with _uploader_lock:
        if _uploader_instance is not None:
            _uploader_instance.reset_last_uploaded()


def force_upload_now(background: bool = False) -> bool:
    """Builds force upload now using local reads or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
    cfg = load_logging_mode_config()
    uploader = _get_uploader(cfg)
    if uploader is None:
        return False
    log_path = cfg.get("log_file_path") or _DEFAULT_CONFIG["log_file_path"]
    if not os.path.exists(log_path):
        print(f"[logging_mode] Activity log file {log_path} missing; cannot force upload")
        return False
    uploader.reset_last_uploaded()
    return upload_logs_if_due(background=background, refresh_config=False)


def reset_logging_state_for_tests() -> None:
    """Resets logging state for tests using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    global _config_cache, _logger_instance, _uploader_instance, _upload_thread
    with _config_lock:
        _config_cache = None
    with _logger_lock:
        if _logger_instance is not None:
            try:
                _logger_instance.close()
            except Exception:
                pass
        _logger_instance = None
    with _uploader_lock:
        _uploader_instance = None
    with _upload_lock:
        _upload_thread = None
