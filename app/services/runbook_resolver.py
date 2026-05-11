"""Runbook resolver stub.

Resolves runbook references attached to Jira incidents. This implementation
returns a no-op result so that the rest of the pipeline can proceed without
a configured runbook store. Replace with a real implementation that fetches
from your internal wiki, Confluence, or a local runbooks directory.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class RunbookResolver:
    """Resolves runbook references to structured content.

    Override ``resolve()`` to pull from your runbook source of truth.
    """

    def resolve(self, reference: str, *, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Attempts to resolve a runbook reference.

        Args:
            reference: URL, key, or path that identifies the runbook.
            context: Optional metadata (ticket key, service, etc.) for enrichment.

        Returns:
            A dict with at minimum ``{"resolved": bool}``. When resolved,
            also includes ``{"title": str, "steps": list[str], "url": str}``.
        """
        return {"resolved": False, "reference": reference}

    def resolve_many(
        self, references: list[str], *, context: Optional[Dict[str, Any]] = None
    ) -> list[Dict[str, Any]]:
        return [self.resolve(ref, context=context) for ref in references]


runbook_resolver = RunbookResolver()
