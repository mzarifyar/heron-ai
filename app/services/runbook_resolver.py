"""Runbook resolver — surfaces relevant runbooks during incident detection.

Sources (tried in order):
  1. Local markdown directory (RUNBOOK_DIR env var, default: docs/runbooks/)
  2. Confluence (CONFLUENCE_BASE_URL + CONFLUENCE_TOKEN + CONFLUENCE_SPACE)
  3. Notion   (NOTION_TOKEN + NOTION_DATABASE_ID)

Matching: keyword overlap between incident signal (service + metric + summary)
and runbook title/tags/keywords. Returns ranked matches, best first.

Chronicle integration: surface_runbooks_for_incident() is called on new
incidents and a timeline entry is added if a match is found.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..core import get_logger

logger = get_logger(__name__)

_RUNBOOK_DIR = Path(os.getenv("RUNBOOK_DIR", "docs/runbooks"))


# ── Indexer ────────────────────────────────────────────────────────────────────

def index_local_runbooks(db: Any) -> int:
    """Scan RUNBOOK_DIR for .md files and index them into the Runbook table."""
    from ..db.models import Runbook
    from sqlalchemy import select
    import uuid
    from datetime import datetime

    if not _RUNBOOK_DIR.exists():
        logger.debug("Runbook dir %s does not exist — skipping local index", _RUNBOOK_DIR)
        return 0

    indexed = 0
    for md_file in _RUNBOOK_DIR.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            title   = _extract_title(content) or md_file.stem.replace("-", " ").replace("_", " ").title()
            tags    = _extract_tags(content, md_file)
            service = _infer_service(md_file, content)
            kws     = _build_keywords(title, content, tags, service)
            source_url = str(md_file.resolve())

            existing = db.execute(
                select(Runbook).where(Runbook.source_url == source_url)
            ).scalar_one_or_none()

            if existing:
                existing.title = title
                existing.content = content[:5000]
                existing.keywords = kws
                existing.tags = tags
                existing.service = service
                existing.indexed_at = datetime.utcnow()
            else:
                db.add(Runbook(
                    id=str(uuid.uuid4()),
                    title=title, service=service,
                    source="local", source_url=source_url,
                    content=content[:5000],
                    tags=tags, keywords=kws,
                    indexed_at=datetime.utcnow(),
                ))
            indexed += 1
        except Exception as exc:
            logger.debug("Failed to index %s: %s", md_file, exc)

    db.commit()
    logger.info("Runbook index: %d local runbooks indexed from %s", indexed, _RUNBOOK_DIR)
    return indexed


def index_confluence(db: Any) -> int:
    """Pull runbooks from Confluence and index them."""
    base  = os.getenv("CONFLUENCE_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("CONFLUENCE_TOKEN", "").strip()
    space = os.getenv("CONFLUENCE_SPACE", "").strip()
    if not base or not token or not space:
        return 0

    try:
        import requests
        import uuid
        from datetime import datetime
        from ..db.models import Runbook
        from sqlalchemy import select

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = requests.get(
            f"{base}/rest/api/content",
            params={"spaceKey": space, "type": "page", "limit": 100,
                    "expand": "body.storage,metadata.labels"},
            headers=headers, timeout=20,
        )
        resp.raise_for_status()
        pages = resp.json().get("results", [])
        indexed = 0
        for page in pages:
            title = page.get("title", "")
            if not any(kw in title.lower() for kw in ("runbook", "playbook", "sop", "incident")):
                continue
            url = f"{base}/wiki/spaces/{space}/pages/{page['id']}"
            body_html = (page.get("body", {}).get("storage", {}).get("value", "") or "")
            content = re.sub(r"<[^>]+>", " ", body_html)[:5000]
            tags = [l["name"] for l in (page.get("metadata", {}).get("labels", {}).get("results", []))]
            service = _infer_service_from_text(title + " " + content)
            kws = _build_keywords(title, content, tags, service)

            existing = db.execute(select(Runbook).where(Runbook.source_url == url)).scalar_one_or_none()
            if existing:
                existing.title = title; existing.keywords = kws; existing.tags = tags
            else:
                db.add(Runbook(id=str(uuid.uuid4()), title=title, service=service,
                               source="confluence", source_url=url,
                               content=content, tags=tags, keywords=kws,
                               indexed_at=datetime.utcnow()))
            indexed += 1
        db.commit()
        logger.info("Runbook index: %d Confluence pages indexed", indexed)
        return indexed
    except Exception as exc:
        logger.warning("Confluence runbook index failed: %s", exc)
        return 0


# ── Resolver ───────────────────────────────────────────────────────────────────

def find_runbooks(
    db: Any,
    *,
    service: str,
    metric_name: str = "",
    summary: str = "",
    severity: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Find the most relevant runbooks for an incident using keyword scoring."""
    from ..db.models import Runbook
    from sqlalchemy import select

    runbooks = db.execute(select(Runbook)).scalars().all()
    if not runbooks:
        return []

    query_tokens = _tokenise(f"{service} {metric_name} {summary} {severity}")

    scored: list[tuple[float, dict]] = []
    for rb in runbooks:
        score = 0.0
        rb_tokens = set(_tokenise(rb.keywords or ""))

        if rb.service and rb.service.lower() == service.lower():
            score += 3.0
        elif rb.service and any(s in service.lower() for s in rb.service.lower().split("-")):
            score += 1.5

        if severity and rb.severity and rb.severity == severity:
            score += 1.0

        overlap = len(query_tokens & rb_tokens)
        score += overlap * 0.5

        for tag in (rb.tags or []):
            if any(t in tag.lower() for t in query_tokens):
                score += 0.3

        if score > 0:
            scored.append((score, {
                "id": rb.id,
                "title": rb.title,
                "service": rb.service,
                "source": rb.source,
                "url": rb.source_url,
                "relevance_score": round(score, 2),
                "tags": rb.tags or [],
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


# ── Chronicle integration ─────────────────────────────────────────────────────

def surface_runbooks_for_incident(
    service: str,
    metric_name: str,
    summary: str,
    severity: str,
    incident_id: str,
) -> str | None:
    """Return a formatted string if matching runbooks found, else None."""
    try:
        from ..db.base import SessionLocal
        with SessionLocal() as db:
            matches = find_runbooks(db, service=service, metric_name=metric_name,
                                    summary=summary, severity=severity, limit=3)
        if not matches:
            return None
        lines = [
            f"  [{m['relevance_score']:.1f}] {m['title']} ({m['source']})" +
            (f"\n    → {m['url']}" if m.get("url") else "")
            for m in matches
        ]
        return f"{len(matches)} runbook(s) matched for {service}:\n" + "\n".join(lines)
    except Exception as exc:
        logger.debug("Runbook surface failed (non-critical): %s", exc)
        return None


# ── Backward-compatible resolver class ───────────────────────────────────────

class RunbookResolver:
    """Public interface — replaces the original stub."""

    def resolve(self, reference: str, *, context: dict | None = None) -> dict[str, Any]:
        ctx = context or {}
        try:
            from ..db.base import SessionLocal
            with SessionLocal() as db:
                matches = find_runbooks(
                    db,
                    service=ctx.get("service", ""),
                    metric_name=ctx.get("metric_name", ""),
                    summary=ctx.get("summary", reference),
                    severity=ctx.get("severity", ""),
                    limit=1,
                )
            if matches:
                m = matches[0]
                return {"resolved": True, "reference": reference,
                        "title": m["title"], "url": m.get("url", ""),
                        "source": m["source"], "score": m["relevance_score"]}
        except Exception:
            pass
        return {"resolved": False, "reference": reference}

    def resolve_many(self, references: list[str], *, context: dict | None = None) -> list[dict[str, Any]]:
        return [self.resolve(ref, context=context) for ref in references]


runbook_resolver = RunbookResolver()


# ── Text helpers ──────────────────────────────────────────────────────────────

_STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "for", "on", "at",
               "to", "of", "in", "and", "or", "not", "with", "by", "from", "this"}

def _tokenise(text: str) -> set[str]:
    tokens = re.findall(r"[a-z][a-z0-9_-]*", text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 2}

def _extract_title(content: str) -> str:
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""

def _extract_tags(content: str, path: Path) -> list[str]:
    tags = [p for p in path.parts[:-1] if p not in (".", "docs", "runbooks")]
    m = re.search(r"(?i)tags?:\s*(.+)", content)
    if m:
        tags += [t.strip().strip("#") for t in re.split(r"[,\s]+", m.group(1)) if t.strip()]
    return [t for t in tags if t]

def _infer_service(path: Path, content: str) -> str | None:
    stem = path.stem.lower()
    for part in re.split(r"[-_]", stem):
        if len(part) > 3 and part not in ("runbook", "playbook", "sop", "guide", "docs"):
            return part
    return _infer_service_from_text(content[:500])

def _infer_service_from_text(text: str) -> str | None:
    known = ["payment-processor", "auth-service", "checkout-service", "api-gateway",
             "search-service", "notification-service", "data-pipeline", "user-profile",
             "inventory-service", "recommendation-engine"]
    t = text.lower()
    for svc in known:
        if svc in t or svc.replace("-", "_") in t or svc.replace("-", " ") in t:
            return svc
    return None

def _build_keywords(*parts: Any) -> str:
    tokens: set[str] = set()
    for p in parts:
        if isinstance(p, list):
            tokens.update(_tokenise(" ".join(str(x) for x in p)))
        elif p:
            tokens.update(_tokenise(str(p)))
    return " ".join(sorted(tokens))
