"""KB → embedding index builder for the MLGG RAG layer.

Reads ``references/case-studies/peer-review-kb.json``, flattens the 817
reviewer concerns into denormalized records (paper-level fields copied onto
each concern for retrieval-time convenience), embeds a rich text view of
each concern via :func:`scripts.rag.embeddings.embed_texts`, and caches the
result under ``.cache/rag/`` keyed by the sha256 of the KB file.

Cache layout (all under :data:`scripts.rag.config.CACHE_DIR`):

* ``concerns_embeddings.npz`` — float32 matrix ``(N, EMBEDDING_DIM)``.
* ``concerns_records.json`` — list of dicts, same order as the matrix rows.
* ``kb_hash.txt`` — sha256 hexdigest of the KB file used to build the cache.

On a clean call the embedding pass dominates wall time (~30-60 s for 817
concerns on CPU). Cache hits skip the model entirely and load in well
under a second.

Cache I/O primitives (atomic writes, sha256 hashing, npz load) live in
:mod:`scripts.rag.index.cache` so other RAG features (BM25 inverted index,
query-result cache) can share them.

Design contract: see ``/tmp/mlgg_rag_design.md`` (shared across 10 agents).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.rag.embeddings import embed_texts
from scripts.rag.config import (
    CACHE_DIR,
    EMBEDDINGS_CACHE,
    KB_HASH_CACHE,
    KB_PATH,
)
from scripts.rag.index.cache import (
    load_cached_embeddings_and_records,
    read_kb_hash,
    save_embeddings_and_records_atomically,
    write_kb_hash_atomically,
)

# Repo root anchors any relative paths coming from config so the module
# works regardless of the caller's cwd. This file lives at
# ``scripts/rag/index/builder.py`` — three parents up = repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Per-field truncation when assembling the embedding text. Keeps the input
# under typical sentence-transformer context windows (BGE-small ~512 tokens)
# while preserving the substantive content of long reviewer paragraphs.
_MAX_CONCERN_CHARS = 1500
_MAX_RESPONSE_CHARS = 800

# Records cache sits next to the embeddings npz (same directory, json sibling).
_RECORDS_CACHE_NAME = "concerns_records.json"


def _anchor(path: Path) -> Path:
    """Return ``path`` as-is if absolute, else resolved against the repo root."""

    return path if path.is_absolute() else (_REPO_ROOT / path)


def _build_concern_record(entry: dict[str, Any], concern: dict[str, Any]) -> dict[str, Any]:
    """Flatten one concern with denormalized paper-level fields.

    Args:
        entry: A paper-level dict from ``peer-review-kb.json`` ``entries``.
        concern: One element of ``entry["reviewer_concerns"]``.

    Returns:
        A dict conforming to the concern record schema in
        ``/tmp/mlgg_rag_design.md``. Scoring metadata fields
        (``_dense_score`` etc.) are deliberately omitted here — they are
        populated downstream by the search / ranker modules.
    """

    return {
        # --- identifiers ---
        "concern_id": concern.get("concern_id"),
        "paper_id": entry.get("id"),
        # --- denormalized paper-level fields (handy for citation rendering) ---
        "paper_title": entry.get("paper_title"),
        "paper_doi": entry.get("paper_doi"),
        "journal": entry.get("journal"),
        "year": entry.get("year"),
        "domain": entry.get("domain"),
        "prediction_task": entry.get("prediction_task"),
        "data_type": entry.get("data_type"),
        "sample_size": entry.get("sample_size"),
        # --- concern-level fields (per design schema) ---
        "reviewer": concern.get("reviewer"),
        "round": concern.get("round"),
        "category": concern.get("category"),
        "severity": concern.get("severity"),
        "mlgg_dimension": concern.get("mlgg_dimension"),
        "mlgg_gates": list(concern.get("mlgg_gates") or []),
        "mlgg_rules": list(concern.get("mlgg_rules") or []),
        "concern_text": concern.get("concern_text") or "",
        "author_response": concern.get("author_response") or "",
        "resolved": concern.get("resolved"),
        "tags": list(concern.get("tags") or []),
        "canonical_pattern_id": concern.get("canonical_pattern_id"),
        "_extraction_policy": concern.get("_extraction_policy"),
    }


def _build_embedding_text(record: dict[str, Any]) -> str:
    """Compose the rich text passed to the sentence-transformer.

    Combines what the reviewer asked (``concern_text``) with how the authors
    addressed it (``author_response``) plus light structural cues
    (``category``, ``tags``). RAG retrieval benefits from carrying both the
    "issue" and the "resolution" because user queries can match either side.

    Each component is truncated independently so a single runaway field can't
    crowd out the rest.
    """

    parts: list[str] = []

    concern_text = (record.get("concern_text") or "").strip()
    if concern_text:
        parts.append(f"Concern: {concern_text[:_MAX_CONCERN_CHARS]}")

    category = (record.get("category") or "").strip()
    if category:
        parts.append(f"Category: {category}")

    tags = record.get("tags") or []
    if tags:
        parts.append("Tags: " + ", ".join(str(t) for t in tags))

    response = (record.get("author_response") or "").strip()
    if response:
        parts.append(f"Author response: {response[:_MAX_RESPONSE_CHARS]}")

    return "\n".join(parts)


def _load_kb(kb_path: Path) -> list[dict[str, Any]]:
    """Load the KB and return ``entries``; raises with a helpful message on issues."""

    if not kb_path.exists():
        raise FileNotFoundError(f"peer-review-kb.json not found at {kb_path}")
    return _parse_kb_bytes(kb_path.read_bytes(), kb_path)


def _parse_kb_bytes(kb_bytes: bytes, kb_path: Path) -> list[dict[str, Any]]:
    """Parse an already-read KB byte buffer and return ``entries``.

    Separated from :func:`_load_kb` so the cold path in
    :func:`build_or_load_index` can hash and parse from the *same* byte
    buffer, closing the read-twice race window between sha256 and json.load
    (W18-D5 CASE-5). ``kb_path`` is passed only for error messages.
    """

    data = json.loads(kb_bytes.decode("utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError(
            f"Malformed KB at {kb_path}: expected list under 'entries', got {type(entries).__name__}"
        )
    return entries


def _build_records(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten all reviewer concerns across all paper entries."""

    records: list[dict[str, Any]] = []
    for entry in entries:
        for concern in entry.get("reviewer_concerns") or []:
            if not concern.get("concern_id"):
                # Skip malformed rows rather than producing unidentifiable cache entries.
                continue
            records.append(_build_concern_record(entry, concern))
    return records


def build_or_load_index(
    kb_path: Path = KB_PATH,
    force_rebuild: bool = False,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Build the embedding index or return the cached one.

    Behavior:
        1. Compute sha256 of ``kb_path``.
        2. If a cache exists, its hash matches, and ``force_rebuild`` is
           false → load the npz + records JSON and return.
        3. Otherwise: flatten reviewer concerns, embed via
           :func:`embed_texts`, persist the cache, and return.

    The function is idempotent: repeated calls on an unchanged KB return the
    same matrix / records without re-embedding.

    Args:
        kb_path: Path to ``peer-review-kb.json``. Relative paths are anchored
            to the repository root.
        force_rebuild: If ``True``, ignore any existing cache and rebuild.

    Returns:
        A 2-tuple ``(embeddings_matrix, concern_records)`` where
        ``embeddings_matrix`` has shape ``(N, EMBEDDING_DIM)`` (float32,
        normalized by :func:`embed_texts`) and ``concern_records`` is a list
        of length ``N`` whose entry ``i`` corresponds to row ``i`` of the
        matrix.

    Raises:
        FileNotFoundError: If the KB file is missing.
        ValueError: If the KB JSON has the wrong shape.
    """

    kb_path = _anchor(Path(kb_path))
    cache_dir = _anchor(CACHE_DIR)
    embeddings_cache = _anchor(EMBEDDINGS_CACHE)
    hash_cache = _anchor(KB_HASH_CACHE)
    records_cache = cache_dir / _RECORDS_CACHE_NAME

    # Read KB bytes ONCE so the sha256 we cache against and the JSON we
    # actually parse describe the same byte sequence — closes the
    # hash-then-load race window (W18-D5 CASE-5): a concurrent KB rewrite
    # between an earlier separate hash() call and a separate load() call
    # would otherwise tag records built from KB v2 with KB v1's hash.
    if not kb_path.exists():
        raise FileNotFoundError(f"peer-review-kb.json not found at {kb_path}")
    kb_bytes = kb_path.read_bytes()
    kb_hash = hashlib.sha256(kb_bytes).hexdigest()

    if not force_rebuild:
        cached_hash = read_kb_hash(hash_cache)
        if cached_hash == kb_hash:
            cached = load_cached_embeddings_and_records(embeddings_cache, records_cache)
            if cached is not None:
                return cached

    # Cold path: parse the SAME bytes we hashed, build records, embed.
    entries = _parse_kb_bytes(kb_bytes, kb_path)
    records = _build_records(entries)
    if not records:
        raise ValueError(
            f"No reviewer concerns found in {kb_path}; refusing to build empty index."
        )

    texts = [_build_embedding_text(rec) for rec in records]
    embeddings = embed_texts(texts)

    if embeddings.shape[0] != len(records):
        raise RuntimeError(
            f"embed_texts returned {embeddings.shape[0]} rows for {len(records)} concerns"
        )

    save_embeddings_and_records_atomically(
        embeddings_path=embeddings_cache,
        records_path=records_cache,
        embeddings=embeddings,
        records=records,
    )
    write_kb_hash_atomically(hash_cache, kb_hash)

    return embeddings.astype(np.float32, copy=False), records


__all__ = ["build_or_load_index"]
