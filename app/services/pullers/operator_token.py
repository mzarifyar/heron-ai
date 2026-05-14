"""Operator token management with local cache + optional SSH refresh."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import base64
import json
import os
import subprocess

from ...core import get_logger

logger = get_logger(__name__)

from app.core.paths import config as _cfg, data as _dat
DEFAULT_TOKEN_STORE_PATH = _dat("operator_token.json")
DEFAULT_SSH_HOST = ""
DEFAULT_SSH_COMMAND = ""


@dataclass(frozen=True)
class OperatorToken:
    """Provides OperatorToken behavior using local state or integrations and exposes structured outputs for callers."""
    token: str
    source: str
    expires_at_utc: Optional[str] = None


class OperatorTokenManager:
    """Provides OperatorTokenManager behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._cache: OperatorToken | None = None

    @staticmethod
    def _normalize(value: str | None) -> str:
        """Normalizes the request using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        token = (value or "").strip()
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
            token = token[1:-1].strip()
        return token

    def _store_path(self) -> Path:
        """Builds store path using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        configured = (os.getenv("HERON_OPERATOR_TOKEN_STORE_PATH") or DEFAULT_TOKEN_STORE_PATH).strip()
        return Path(configured)

    def _allow_ssh_refresh(self) -> bool:
        """Builds allow ssh refresh using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = (os.getenv("HERON_OPERATOR_TOKEN_ALLOW_SSH_REFRESH") or "true").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _refresh_timeout(self) -> int:
        """Builds refresh timeout using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        raw = (os.getenv("HERON_OPERATOR_TOKEN_REFRESH_TIMEOUT_SECONDS") or "30").strip()
        try:
            return max(5, int(raw))
        except ValueError:
            return 30

    def _ssh_host(self) -> str:
        """Builds ssh host using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        return (os.getenv("HERON_OPERATOR_TOKEN_SSH_HOST") or DEFAULT_SSH_HOST).strip()

    def _ssh_command(self) -> str:
        """Builds ssh command using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        return (os.getenv("HERON_OPERATOR_TOKEN_SSH_COMMAND") or DEFAULT_SSH_COMMAND).strip()

    @staticmethod
    def _decode_exp(token: str) -> Optional[str]:
        """Builds decode exp using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        pad = "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode((payload + pad).encode("utf-8")).decode("utf-8")
            data = json.loads(decoded)
        except Exception:
            return None
        exp = data.get("exp")
        if not isinstance(exp, (int, float)):
            return None
        dt = datetime.fromtimestamp(float(exp), tz=timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _read_store(self) -> OperatorToken | None:
        """Reads store using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        path = self._store_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        token = self._normalize(payload.get("token"))
        if not token:
            return None
        return OperatorToken(
            token=token,
            source=str(payload.get("source") or "store"),
            expires_at_utc=str(payload.get("expires_at_utc") or "") or None,
        )

    def _write_store(self, token: OperatorToken) -> None:
        """Writes store using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "token": token.token,
            "source": token.source,
            "expires_at_utc": token.expires_at_utc,
            "updated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _is_expired(expires_at_utc: str | None) -> bool:
        """Checks expired using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if not expires_at_utc:
            return False
        try:
            text = expires_at_utc.replace("Z", "+00:00")
            expires = datetime.fromisoformat(text).astimezone(timezone.utc)
        except Exception:
            return False
        return datetime.now(timezone.utc) >= expires

    def status(self) -> Dict[str, Any]:
        """Builds status using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        token = self._cache or self._read_store()
        return {
            "has_token": bool(token and token.token),
            "source": token.source if token else None,
            "expires_at_utc": token.expires_at_utc if token else None,
            "expired": self._is_expired(token.expires_at_utc if token else None),
            "store_path": str(self._store_path()),
            "ssh_refresh_enabled": self._allow_ssh_refresh(),
        }

    def refresh_via_ssh(self) -> OperatorToken:
        """Builds refresh via ssh using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not self._allow_ssh_refresh():
            raise RuntimeError("SSH token refresh is disabled")
        host = self._ssh_host()
        command_parts = [part for part in self._ssh_command().split(" ") if part]
        if not host or not command_parts:
            raise RuntimeError("SSH token refresh host/command not configured")
        try:
            result = subprocess.run(
                ["ssh", host, *command_parts],
                capture_output=True,
                text=True,
                timeout=self._refresh_timeout(),
                check=True,
            )
            token_raw = result.stdout.strip()
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if isinstance(exc.stderr, str) else ""
            raise RuntimeError(f"operator token refresh failed (exit={exc.returncode}): {stderr}") from exc
        token = self._normalize(token_raw)
        if not token:
            raise RuntimeError("operator token refresh returned empty output")
        payload = OperatorToken(token=token, source="ssh-refresh", expires_at_utc=self._decode_exp(token))
        self._cache = payload
        self._write_store(payload)
        return payload

    def get_token(self, *, auto_refresh: bool = True) -> OperatorToken:
        # 1) explicit env first (keeps expected behavior in CI/container)
        """Gets token using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        for name in ("OPERATOR_ACCESS_TOKEN", "HERON_OPERATOR_ACCESS_TOKEN"):
            value = self._normalize(os.getenv(name))
            if value:
                token = OperatorToken(token=value, source=f"env:{name}", expires_at_utc=self._decode_exp(value))
                if not self._is_expired(token.expires_at_utc):
                    self._cache = token
                    return token
                logger.warning("Ignoring expired operator token from %s", name)

        # 2) cached/store token
        token = self._cache or self._read_store()
        if token and token.token and not self._is_expired(token.expires_at_utc):
            self._cache = token
            return token

        # 3) optional refresh via ssh
        if auto_refresh and self._allow_ssh_refresh():
            try:
                return self.refresh_via_ssh()
            except Exception as exc:
                logger.warning("Operator token SSH refresh failed: %s", exc)
        raise RuntimeError("No valid operator token found")


operator_token_manager = OperatorTokenManager()