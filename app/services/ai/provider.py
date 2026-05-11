"""LLM provider abstraction — supports Anthropic (Claude), OpenAI, and Ollama.

Configure via .env:
    HERON_AI_PROVIDER = anthropic | openai | ollama
    HERON_AI_API_KEY  = sk-ant-... (or sk-... for OpenAI)
    HERON_AI_MODEL    = claude-sonnet-4-5  (default for Anthropic)
    HERON_AI_BASE_URL = http://localhost:11434  (Ollama only)
    HERON_AI_MAX_TOKENS = 1024
"""

from __future__ import annotations

import os
from typing import Optional

from ...core import get_logger

logger = get_logger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


class AIProvider:
    """Thin abstraction over LLM providers.

    Usage:
        provider = get_ai_provider()
        if provider:
            text = provider.complete(prompt, system=system_prompt)
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        base_url: str = "",
    ) -> None:
        self.provider   = provider.lower()
        self.api_key    = api_key
        self.model      = model
        self.max_tokens = max_tokens
        self.base_url   = base_url
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client

        if self.provider == "anthropic":
            try:
                import anthropic  # type: ignore
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. Run: pip install anthropic"
                )

        elif self.provider == "openai":
            try:
                import openai  # type: ignore
                self._client = openai.OpenAI(
                    api_key=self.api_key,
                    **({"base_url": self.base_url} if self.base_url else {}),
                )
            except ImportError:
                raise RuntimeError(
                    "openai package not installed. Run: pip install openai"
                )

        elif self.provider == "ollama":
            try:
                import openai  # type: ignore  # Ollama exposes an OpenAI-compatible API
                self._client = openai.OpenAI(
                    api_key="ollama",
                    base_url=self.base_url or "http://localhost:11434/v1",
                )
            except ImportError:
                raise RuntimeError(
                    "openai package not installed (needed for Ollama). Run: pip install openai"
                )
        else:
            raise ValueError(f"Unknown AI provider: {self.provider!r}")

        return self._client

    def complete(self, prompt: str, *, system: str = "") -> str:
        """Send a prompt and return the text response."""
        client = self._get_client()

        if self.provider == "anthropic":
            import anthropic  # type: ignore
            kwargs = {
                "model":      self.model,
                "max_tokens": self.max_tokens,
                "messages":   [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},  # prompt caching
                    }
                ]
            response = client.messages.create(**kwargs)  # type: ignore
            return response.content[0].text

        else:
            # OpenAI / Ollama — same interface
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(  # type: ignore
                model=self.model,
                max_tokens=self.max_tokens,
                messages=messages,
            )
            return response.choices[0].message.content or ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key or self.provider == "ollama")


def get_ai_provider() -> Optional[AIProvider]:
    """Return a configured AIProvider, or None if not set up."""
    provider = _env("HERON_AI_PROVIDER")
    if not provider:
        return None

    defaults = {
        "anthropic": "claude-sonnet-4-5",
        "openai":    "gpt-4o",
        "ollama":    "llama3",
    }
    model = _env("HERON_AI_MODEL") or defaults.get(provider, "")
    api_key   = _env("HERON_AI_API_KEY")
    base_url  = _env("HERON_AI_BASE_URL")
    max_tokens = int(_env("HERON_AI_MAX_TOKENS", "1024"))

    if provider not in ("anthropic", "openai", "ollama"):
        logger.warning("Unknown HERON_AI_PROVIDER=%r — ignoring", provider)
        return None

    if not api_key and provider != "ollama":
        logger.warning("HERON_AI_PROVIDER=%r set but HERON_AI_API_KEY missing", provider)
        return None

    return AIProvider(
        provider=provider,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        base_url=base_url,
    )
