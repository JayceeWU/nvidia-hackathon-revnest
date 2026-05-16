from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # noqa: BLE001 - allow lightweight lexical fallback in sandboxes.
    SentenceTransformer = None  # type: ignore[assignment]


DEFAULT_DB_URL = "postgresql://postgres:postgres@127.0.0.1:55434/dev"
DEFAULT_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MODEL_CACHE = "/sandbox/.openclaw/workspace/.cache/strategy-memory/models"
DEFAULT_MIN_SCORE = 0.22


def database_url() -> str:
    return os.environ.get("STRATEGY_MEMORY_DATABASE_URL", DEFAULT_DB_URL)


def model_name() -> str:
    if os.environ.get("STRATEGY_MEMORY_MODEL"):
        return os.environ["STRATEGY_MEMORY_MODEL"]
    local_model = Path(os.environ.get("STRATEGY_MEMORY_MODEL_CACHE", DEFAULT_MODEL_CACHE)) / "all-MiniLM-L6-v2"
    if (local_model / "modules.json").exists():
        return str(local_model)
    return DEFAULT_MODEL_ID


def min_score() -> float:
    raw = os.environ.get("STRATEGY_MEMORY_MIN_SCORE")
    if not raw:
        return DEFAULT_MIN_SCORE
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_MIN_SCORE


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())


@lru_cache(maxsize=1)
def embedding_model() -> SentenceTransformer:
    if SentenceTransformer is None:
        raise RuntimeError("sentence_transformers is unavailable")
    cache_dir = os.environ.get(
        "STRATEGY_MEMORY_MODEL_CACHE",
        DEFAULT_MODEL_CACHE,
    )
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    return SentenceTransformer(model_name(), cache_folder=cache_dir)


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = embedding_model().encode(
        texts,
        batch_size=int(os.environ.get("STRATEGY_MEMORY_BATCH_SIZE", "16")),
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [[float(value) for value in vector] for vector in vectors]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def expand_query(query: str) -> str:
    q = query.strip()
    additions: list[str] = []
    lower = q.lower()

    if has_cjk(q) or any(
        token in q
        for token in (
            "\u7b56\u7565",
            "\u5b9a\u4ef7",
            "\u9152\u5e97",
            "\u6536\u76ca",
            "\u623f\u4ef7",
            "\u6709\u54ea\u4e9b",
        )
    ):
        additions.extend(
            [
                "what pricing strategies are there",
                "pricing strategies",
                "revenue management strategy",
                "rate strategy",
                "seasonality strategy",
                "day of week strategy",
                "booking window pace rules",
                "length of stay controls",
                "channel strategy",
                "direct booking strategy",
                "OTA wholesale package promotion strategy",
                "event compression pricing",
                "Dream Inn Santa Cruz",
                "Airbnb pricing playbook",
            ]
        )

    if "dream" in lower or "hotel" in lower:
        additions.extend(["Dream Inn Santa Cruz hotel revenue management pricing strategy"])
    if "airbnb" in lower or "short-term" in lower or "str" in lower:
        additions.extend(["Airbnb short-term rental pricing strategy manual"])

    merged: list[str] = []
    seen: set[str] = set()
    for part in [q, *additions]:
        normalized = " ".join(part.split())
        key = normalized.lower()
        if normalized and key not in seen:
            merged.append(normalized)
            seen.add(key)
    return " | ".join(merged)


def is_strategy_domain_query(query: str, expanded_query: str) -> bool:
    cjk_terms = [
        "\u7b56\u7565",
        "\u5b9a\u4ef7",
        "\u4ef7\u683c",
        "\u623f\u4ef7",
        "\u6536\u76ca",
        "\u9152\u5e97",
        "\u6c11\u5bbf",
        "\u6e20\u9053",
        "\u5165\u4f4f\u7387",
        "\u4fc3\u9500",
    ]
    if any(term in query for term in cjk_terms):
        return True

    domain_terms = [
        "revnest",
        "dream inn",
        "airbnb",
        "pricing",
        "price",
        "rate",
        "strategy",
        "strategies",
        "revenue",
        "rms",
        "revpar",
        "adr",
        "occupancy",
        "booking",
        "channel",
        "seasonality",
        "demand",
        "bar",
        "ota",
        "promotion",
        "package",
        "hotel",
        "short-term rental",
    ]
    text = f"{query} {expanded_query}".lower()
    return any(term in text for term in domain_terms)


def lexical_score(content: str, section: str | None, source: str | None, terms: list[str]) -> float:
    haystack = f"{source or ''} {section or ''} {content}".lower()
    if not terms:
        return 0
    hits = sum(1 for term in terms if term in haystack)
    phrase_bonus = 1 if any(phrase in haystack for phrase in ("pricing strategy", "revenue management", "airbnb", "dream inn")) else 0
    return min(1.0, (hits + phrase_bonus) / max(4, min(len(terms), 12)))


def lexical_search_strategy_memory(query: str, expanded_query: str, top_k: int) -> dict[str, Any]:
    terms = []
    for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", expanded_query.lower()):
        if term not in terms:
            terms.append(term)
    limit = max(1, min(int(top_k or 8), 20))
    chunks: list[dict[str, Any]] = []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, source_path, section, content, metadata
                FROM strategy_memory_chunks
                """
            )
            for source, source_path, section, content, metadata in cur.fetchall():
                score_value = lexical_score(content or "", section, source, terms)
                if score_value <= 0:
                    continue
                chunks.append(
                    {
                        "source": source,
                        "source_path": source_path,
                        "section": section,
                        "score": round(score_value, 4),
                        "content": content,
                        "metadata": metadata if isinstance(metadata, dict) else json.loads(metadata),
                    }
                )
    chunks.sort(key=lambda item: item["score"], reverse=True)
    return {
        "query": query,
        "expanded_query": expanded_query,
        "retrieval_mode": "lexical",
        "chunks": chunks[:limit],
    }


def search_strategy_memory(query: str, top_k: int = 8) -> dict[str, Any]:
    expanded_query = expand_query(query)
    if not is_strategy_domain_query(query, expanded_query):
        return {"query": query, "expanded_query": expanded_query, "chunks": []}
    try:
        query_vector = vector_literal(embed_texts([expanded_query])[0])
    except Exception:
        return lexical_search_strategy_memory(query, expanded_query, top_k)
    limit = max(1, min(int(top_k or 8), 20))

    sql = """
        SELECT
          source,
          source_path,
          section,
          content,
          metadata,
          1 - (embedding <=> %s::vector) AS score
        FROM strategy_memory_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """

    chunks: list[dict[str, Any]] = []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (query_vector, query_vector, limit))
            for source, source_path, section, content, metadata, score in cur.fetchall():
                score_value = float(score or 0)
                if score_value < min_score():
                    continue
                chunks.append(
                    {
                        "source": source,
                        "source_path": source_path,
                        "section": section,
                        "score": round(score_value, 4),
                        "content": content,
                        "metadata": metadata if isinstance(metadata, dict) else json.loads(metadata),
                    }
                )

    return {"query": query, "expanded_query": expanded_query, "chunks": chunks}
