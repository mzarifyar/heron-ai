"""Parsing helpers for Jira ticket summaries and alarm messages.

Ported from the legacy Cortex processor so associations work identically.

"""
from __future__ import annotations

import re
from typing import Dict

__all__ = ["normalize_message", "parse_ticket_summary"]


def normalize_message(msg: str) -> str:
    """Normalizes message using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return re.sub(r"\s+", " ", (msg or "").strip().lower())


def parse_ticket_summary(summary: str) -> Dict[str, str]:
    """Parses ticket summary using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    pattern = (
        r'^\s*\[(?P<airport>[^\]]+)\]\s*'
        r'\[(?P<realm>[^\]]+)\]\s*'
        r'\[(?P<env>[^\]]+)\]\s*'
        r'\[(?P<cluster>[^\]]+)\]\s*'
        r'(?P<message>.+?)\s*$'
    )
    match = re.match(pattern, summary or "")
    if not match:
        return {
            "airport_code": "",
            "realm": "",
            "environment": "",
            "cluster": "",
            "message": (summary or "").strip(),
        }
    return {
        "airport_code": match.group("airport").strip(),
        "realm": match.group("realm").strip(),
        "environment": match.group("env").strip(),
        "cluster": match.group("cluster").strip(),
        "message": match.group("message").strip(),
    }