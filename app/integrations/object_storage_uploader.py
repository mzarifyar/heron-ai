"""AWS Object Storage uploader for logging mode.

"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

try:  # pragma: no cover
    import aws
except ImportError:  # pragma: no cover
    aws = None


class ObjectStorageUploader:
    """Provides ObjectStorageUploader behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, config: Dict[str, Any]):
        """Initializes instance state using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if config is None:
            raise ValueError("config is required")
        self._client: Optional[Any] = None
        self._last_uploaded: Optional[float] = None
        self._mode: str = "sdk"
        self._state_path: Optional[str] = None
        self.update_config(config)

    def update_config(self, config: Dict[str, Any]) -> None:
        """Updates config using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.config = config or {}
        self.os_cfg = self.config.get("object_storage", {}) or {}
        self.schedule_cfg = self.config.get("upload_schedule", {}) or {}
        self._state_path = (
            self.schedule_cfg.get("state_path")
            or self.os_cfg.get("state_path")
            or None
        )
        new_mode = self._upload_mode()
        if new_mode != getattr(self, "_mode", None):
            self._client = None
        self._mode = new_mode
        self._load_persisted_state()

    def should_upload(self) -> bool:
        """Determines upload using local reads or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        return bool(self.os_cfg.get("enabled")) and bool(self.schedule_cfg.get("enabled"))

    def _upload_mode(self) -> str:
        """Builds upload mode using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        return str(self.os_cfg.get("upload_mode", "sdk")).strip().lower() or "sdk"

    def _max_attempts(self) -> int:
        """Builds max attempts using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        try:
            return max(1, int(self.os_cfg.get("max_retry_attempts", 5)))
        except Exception:
            return 5

    def _ensure_client(self) -> Any:
        """Ensures client using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if self._client is not None:
            return self._client
        if aws is None:
            raise RuntimeError("AWS SDK is not available")
        kwargs: Dict[str, Any] = {}
        endpoint = self.os_cfg.get("endpoint_override")
        if endpoint:
            kwargs["service_endpoint"] = endpoint

        signer: Optional[Any] = None
        client_config: Optional[Dict[str, Any]] = None

        if hasattr(aws, "config"):
            profile = self.os_cfg.get("aws_config_profile", "DEFAULT")
            cfg_path = self.os_cfg.get("aws_config_file")
            aws_config_override = self.os_cfg.get("aws_config")
            if isinstance(aws_config_override, dict) and aws_config_override:
                client_config = dict(aws_config_override)
            else:
                try:
                    if cfg_path:
                        client_config = aws.config.from_file(str(cfg_path), profile_name=profile)
                    else:
                        client_config = aws.config.from_file(profile_name=profile)
                except Exception:
                    client_config = None

        auth_type = (self.os_cfg.get("auth_type") or "").lower()
        if auth_type == "instance_principals" and hasattr(aws, "auth"):
            try:
                signer = aws.auth.signers.InstancePrincipalsSecurityTokenSigner()  # type: ignore[attr-defined]
            except Exception as exc:
                raise RuntimeError(f"Failed to create AWS Instance Principals signer: {exc}") from exc
        elif auth_type == "resource_principals" and hasattr(aws, "auth"):
            try:
                signer = aws.auth.signers.get_resource_principals_signer()  # type: ignore[attr-defined]
            except Exception as exc:
                raise RuntimeError(f"Failed to create AWS Resource Principals signer: {exc}") from exc

        if client_config is None and signer is None:
            client_config = {}

        self._client = aws.object_storage.ObjectStorageClient(client_config or {}, signer=signer, **kwargs)
        return self._client

    def build_object_name(self, now: Optional[datetime] = None) -> str:
        """Builds object name using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        if now is None:
            now = datetime.now(timezone.utc)
        fmt = self.os_cfg.get("object_name_format") or "cortex_activity_{yyyyMMddHHmmss}.log"
        replacements = {
            "{yyyyMMddHHmmss}": now.strftime("%Y%m%d%H%M%S"),
            "{yyyyMMddHHmm}": now.strftime("%Y%m%d%H%M"),
            "{yyyyMMddHH}": now.strftime("%Y%m%d%H"),
            "{yyyyMMdd_HHmm}": now.strftime("%Y%m%d_%H%M"),
            "{yyyyMMdd}": now.strftime("%Y%m%d"),
        }
        for token, value in replacements.items():
            fmt = fmt.replace(token, value)
        prefix = self.os_cfg.get("object_prefix") or ""
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return f"{prefix}{fmt}"

    def due_for_upload(self, now: Optional[float] = None) -> bool:
        """Builds due for upload using local reads or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if not self.should_upload():
            return False
        if now is None:
            now = time.time()
        frequency = max(1, int(self.schedule_cfg.get("frequency_minutes", 60))) * 60
        if self._last_uploaded is None and self._state_path:
            self._load_persisted_state()
        if self._last_uploaded is None:
            return True
        return (now - self._last_uploaded) >= frequency

    def upload(self, file_path: str, *, now: Optional[datetime] = None, background: bool = True) -> None:
        """Builds upload using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        if not self.should_upload():
            return
        if not os.path.exists(file_path):
            print(f"[logging_mode] Log file {file_path} not found; skipping upload")
            return
        mode = self._upload_mode()
        object_name = self.build_object_name(now)
        try:
            self._perform_upload(mode, file_path, object_name, background=background)
            print(f"[logging_mode] Uploaded {file_path} to {object_name} via {mode} mode")
            self._last_uploaded = time.time()
            self._persist_last_uploaded()
        except Exception as exc:  # pragma: no cover
            print(f"[logging_mode] Upload failed: {exc}")

    def _perform_upload(self, mode: str, file_path: str, object_name: str, *, background: bool) -> None:
        """Builds perform upload using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        retries = 0
        backoff = 5
        max_attempts = self._max_attempts()
        max_attempts_foreground = max(1, int(self.schedule_cfg.get("foreground_max_attempts", 2)))
        max_sleep_foreground = max(1, int(self.schedule_cfg.get("foreground_max_sleep_seconds", 30)))
        while True:
            try:
                if mode == "par":
                    self._upload_via_par(file_path, object_name)
                else:
                    self._upload_via_sdk(file_path, object_name)
                return
            except Exception as exc:
                retries += 1
                attempt_limit = max_attempts if background else min(max_attempts, max_attempts_foreground)
                if retries > attempt_limit:
                    raise RuntimeError("upload failed after retries") from exc
                jitter = random.uniform(0, 1)
                sleep_for = backoff + jitter
                if not background and sleep_for > max_sleep_foreground:
                    sleep_for = max_sleep_foreground
                time.sleep(sleep_for)
                max_backoff = 300 if background else max_sleep_foreground
                backoff = min(backoff * 2, max_backoff)

    def _upload_via_sdk(self, file_path: str, object_name: str) -> None:
        """Builds upload via sdk using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        namespace = self.os_cfg.get("namespace")
        bucket = self.os_cfg.get("bucket_name")
        if not namespace or not bucket:
            raise RuntimeError("namespace or bucket is missing for SDK upload")
        client = self._ensure_client()
        with open(file_path, "rb") as fh:
            client.put_object(namespace, bucket, object_name, fh)

    def _upload_via_par(self, file_path: str, object_name: str) -> None:
        """Builds upload via par using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        primary = self.os_cfg.get("par_base_url_primary")
        secondary = self.os_cfg.get("par_base_url_secondary")
        if not primary and not secondary:
            raise RuntimeError("PAR mode requires at least one base URL")
        errors = []
        for label, base in (("primary", primary), ("secondary", secondary)):
            if not base:
                continue
            url = self._build_par_url(base, object_name)
            try:
                with open(file_path, "rb") as fh:
                    resp = requests.put(url, data=fh, headers={"Content-Type": "text/plain"}, timeout=60)
                if 200 <= resp.status_code < 300:
                    return
                errors.append(f"{label} status {resp.status_code}")
            except Exception as exc:  # pragma: no cover
                errors.append(f"{label} error {exc}")
        joined = ", ".join(errors) if errors else "no attempts recorded"
        raise RuntimeError(f"PAR upload failed ({joined})")

    @staticmethod
    def _build_par_url(base_url: str, object_name: str) -> str:
        # Expect base_url to end with a directory-style prefix containing namespace/bucket.
        # Only object names should be appended; object_name is URL-encoded once.
        """Builds par url using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        encoded = quote(object_name, safe="")
        if not base_url.endswith("/"):
            base_url += "/"
        return f"{base_url}{encoded}"

    def reset_last_uploaded(self) -> None:
        """Resets last uploaded using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._last_uploaded = None
        if self._state_path and os.path.exists(self._state_path):
            try:
                os.remove(self._state_path)
            except OSError:
                pass

    # Internal helpers -------------------------------------------------

    def _persist_last_uploaded(self) -> None:
        """Builds persist last uploaded using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        if not self._state_path or self._last_uploaded is None:
            return
        try:
            directory = os.path.dirname(self._state_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as fh:
                fh.write(str(self._last_uploaded))
        except Exception:
            # Persistence issues should not block uploads; best-effort only.
            pass

    def _load_persisted_state(self) -> None:
        """Loads persisted state using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                value = float(fh.read().strip())
            self._last_uploaded = value
        except Exception:
            self._last_uploaded = None