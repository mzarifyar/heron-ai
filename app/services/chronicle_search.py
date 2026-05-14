"""Chronicle semantic search — two-tier search across all incident history.

Tier 1 — BM25 keyword search (zero deps, instant):
  Ranks incidents by term frequency / inverse document frequency against
  a query.  Works immediately with no API calls or configuration.

Tier 2 — Semantic reranking (optional, requires HERON_AI_PROVIDER):
  Takes the top-k BM25 results, embeds query + incident text via the AI
  provider, and reranks by cosine similarity.  Falls back gracefully
  when AI isn't configured.

Index:
  In-memory inverted index built from Incident.title + Incident.service +
  TimelineEvent.description.  Rebuilt on first search and every
  INDEX_REFRESH_INTERVAL seconds (default 5 minutes).

Usage:
  from app.services.chronicle_search import chronicle_search
  results = chronicle_search.search("connection pool payment-processor", limit=10)
"""

from __future__ import annotations

import math
import re
import threading
import time
from datetime import datetime
from typing import Any

from ..core import get_logger

logger = get_logger(__name__)

INDEX_REFRESH_INTERVAL = 300   # seconds


# ── Text helpers ──────────────────────────────────────────────────────────────

_STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "as", "this", "that", "it", "its",
    "and", "or", "not", "but", "if", "so", "then", "than", "into",
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9_-]*", text.lower())
    return [w for w in words if w not in _STOP and len(w) > 1]


def _doc_text(inc: dict[str, Any]) -> str:
    """Concatenate all searchable fields of an incident document."""
    parts = [
        inc.get("title", ""),
        inc.get("service", ""),
        inc.get("severity", ""),
        inc.get("status", ""),
        inc.get("region", ""),
        inc.get("environment", ""),
        " ".join(inc.get("timeline_text", [])),
    ]
    return " ".join(p for p in parts if p)


# ── BM25 implementation ───────────────────────────────────────────────────────

class _BM25:
    """Okapi BM25 scorer over a corpus of incident documents."""

    k1 = 1.5
    b  = 0.75

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []
        self._tf: list[dict[str, int]] = []          # term freq per doc
        self._df: dict[str, int] = {}                # doc freq per term
        self._avg_len: float = 1.0
        self._n: int = 0

    def build(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self._tf = []
        self._df = {}
        total_len = 0

        for doc in docs:
            toks = _tokens(_doc_text(doc))
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self._tf.append(tf)
            total_len += len(toks)
            for term in set(toks):
                self._df[term] = self._df.get(term, 0) + 1

        self._n = len(docs)
        self._avg_len = total_len / max(self._n, 1)
        logger.info("BM25 index built: %d documents", self._n)

    def score(self, query: str, doc_idx: int) -> float:
        tf = self._tf[doc_idx]
        doc_len = sum(tf.values())
        score = 0.0
        for term in _tokens(query):
            if term not in tf:
                continue
            df = self._df.get(term, 0)
            idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1)
            tf_val = tf[term]
            norm = tf_val * (self.k1 + 1) / (
                tf_val + self.k1 * (1 - self.b + self.b * doc_len / self._avg_len)
            )
            score += idf * norm
        return score

    def search(self, query: str, limit: int = 20) -> list[tuple[float, dict[str, Any]]]:
        if not self._docs:
            return []
        scored = [
            (self.score(query, i), self._docs[i])
            for i in range(self._n)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(s, d) for s, d in scored if s > 0][:limit]


# ── Semantic reranker ─────────────────────────────────────────────────────────

def _embed_text(text: str) -> list[float] | None:
    """Get embedding via the configured AI provider. Returns None if unavailable."""
    try:
        provider_name = __import__("os").getenv("HERON_AI_PROVIDER", "").strip()
        api_key = __import__("os").getenv("HERON_AI_API_KEY", "").strip()
        if not provider_name or not api_key:
            return None

        if provider_name == "anthropic":
            # Claude doesn't have an embeddings API — use OpenAI-compatible endpoint
            # or fall back to None (BM25 only)
            return None

        if provider_name == "openai":
            import openai  # type: ignore
            client = openai.OpenAI(api_key=api_key)
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:2000],
            )
            return resp.data[0].embedding

        if provider_name == "ollama":
            import requests
            base = __import__("os").getenv("HERON_AI_BASE_URL", "http://localhost:11434")
            resp = requests.post(
                f"{base}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": text[:2000]},
                timeout=15,
            )
            return resp.json().get("embedding")
    except Exception as exc:
        logger.debug("Embedding failed (non-critical): %s", exc)
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def _rerank(
    query: str,
    candidates: list[tuple[float, dict[str, Any]]],
) -> list[tuple[float, dict[str, Any]]]:
    """Rerank BM25 candidates using embedding cosine similarity."""
    q_emb = _embed_text(query)
    if q_emb is None:
        return candidates   # no embedding available — return BM25 order

    reranked: list[tuple[float, dict[str, Any]]] = []
    for _bm25_score, doc in candidates:
        doc_emb = _embed_text(_doc_text(doc)[:500])
        sem_score = _cosine(q_emb, doc_emb) if doc_emb else 0.0
        # Blend: 40% BM25 (normalised) + 60% semantic
        combined = 0.4 * _bm25_score / 10.0 + 0.6 * sem_score
        reranked.append((combined, doc))

    reranked.sort(key=lambda x: x[0], reverse=True)
    return reranked


# ── Index loader ──────────────────────────────────────────────────────────────

def _load_incidents() -> list[dict[str, Any]]:
    """Load all incidents + their timeline text from DB."""
    try:
        from ..db.base import SessionLocal
        from ..db.models import Incident, TimelineEvent
        from sqlalchemy import select

        with SessionLocal() as db:
            incidents = db.execute(
                select(Incident).order_by(Incident.started_at.desc())
            ).scalars().all()

            docs = []
            for inc in incidents:
                # Pull timeline event descriptions for this incident
                timeline_rows = db.execute(
                    select(TimelineEvent.description)
                    .where(TimelineEvent.incident_id == inc.id)
                    .limit(20)
                ).scalars().all()

                docs.append({
                    "id":            inc.id,
                    "title":         inc.title,
                    "service":       inc.service,
                    "severity":      inc.severity,
                    "status":        inc.status,
                    "region":        inc.region,
                    "environment":   inc.environment,
                    "auto_healed":   inc.auto_healed,
                    "mttr_seconds":  inc.mttr_seconds,
                    "started_at":    inc.started_at.isoformat() if inc.started_at else "",
                    "timeline_text": [t for t in timeline_rows if t],
                })
        return docs
    except Exception as exc:
        logger.warning("Failed to load incidents for search index: %s", exc)
        return []


# ── Search service ────────────────────────────────────────────────────────────

class ChronicleSearch:
    """Two-tier Chronicle search: BM25 + optional semantic reranking."""

    def __init__(self) -> None:
        self._bm25 = _BM25()
        self._lock  = threading.Lock()
        self._built_at: float = 0.0
        self._doc_count: int = 0

    def _maybe_rebuild(self) -> None:
        """Rebuild index if stale (>5 minutes) or empty."""
        now = time.time()
        if now - self._built_at < INDEX_REFRESH_INTERVAL and self._doc_count > 0:
            return
        with self._lock:
            if now - self._built_at < INDEX_REFRESH_INTERVAL and self._doc_count > 0:
                return
            docs = _load_incidents()
            self._bm25.build(docs)
            self._doc_count = len(docs)
            self._built_at = time.time()

    def rebuild(self) -> int:
        """Force a full index rebuild. Returns document count."""
        with self._lock:
            docs = _load_incidents()
            self._bm25.build(docs)
            self._doc_count = len(docs)
            self._built_at = time.time()
        return self._doc_count

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        semantic: bool = True,
        filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search Chronicle incident history.

        Args:
            query:    Natural language query — "connection pool payment processor"
            limit:    Max results to return.
            semantic: If True, rerank top BM25 results with embeddings (when available).
            filters:  Optional exact-match filters: {"service": "...", "severity": "..."}

        Returns:
            List of incident dicts with a "score" field added.
        """
        if not query.strip():
            return []

        self._maybe_rebuild()
        candidates = self._bm25.search(query, limit=limit * 3)

        # Apply filters
        if filters:
            candidates = [
                (s, d) for s, d in candidates
                if all(d.get(k) == v for k, v in filters.items() if v)
            ]

        if semantic and candidates:
            candidates = _rerank(query, candidates[:limit * 2])

        results = []
        for score, doc in candidates[:limit]:
            results.append({**doc, "score": round(score, 4)})

        return results

    def status(self) -> dict[str, Any]:
        return {
            "doc_count": self._doc_count,
            "built_at": datetime.fromtimestamp(self._built_at).isoformat() if self._built_at else None,
            "stale": time.time() - self._built_at > INDEX_REFRESH_INTERVAL,
            "semantic_available": bool(
                __import__("os").getenv("HERON_AI_PROVIDER", "") in ("openai", "ollama")
            ),
        }


chronicle_search = ChronicleSearch()
