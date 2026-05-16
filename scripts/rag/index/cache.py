"""Cache primitives for the RAG index layer.

Provides atomic file writes and sha256-based invalidation helpers used by
``scripts.rag.index.builder`` today. Designed to be shared between
``builder.py`` and future cache consumers (BM25 inverted-index cache,
query-result cache) so the same "write-to-``*.tmp`` then ``os.replace``"
and "sha256-of-source keyed cache" patterns aren't reinvented.

All helpers operate on absolute paths — callers are responsible for
anchoring relative paths (see ``builder._anchor``). Each function is a
narrow primitive; the orchestration (decide-to-rebuild / load-or-build)
lives in :func:`scripts.rag.index.builder.build_or_load_index`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def kb_sha256(kb_path: Path) -> str:
    """Compute the sha256 hexdigest of a file in fixed-size chunks.

    Args:
        kb_path: Path to the file to hash (typically the KB JSON).

    Returns:
        Lowercase 64-char sha256 hexdigest.
    """

    digest = hashlib.sha256()
    with kb_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_kb_hash(hash_path: Path) -> str | None:
    """Return the cached KB hash, or ``None`` if missing/empty/unreadable.

    Args:
        hash_path: Path to the ``kb_hash.txt`` cache file.

    Returns:
        The stored hex digest (whitespace-stripped) or ``None`` if the
        file does not exist, can't be read, or contains nothing.
    """

    if not hash_path.exists():
        return None
    try:
        value = hash_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def write_kb_hash_atomically(hash_path: Path, sha: str) -> None:
    """Write ``sha`` to ``hash_path`` via a ``*.tmp`` + rename.

    Avoids leaving a half-written hash file if the process dies mid-write.

    Args:
        hash_path: Destination ``kb_hash.txt`` path.
        sha: Hex digest string to persist (a trailing newline is added).
    """

    hash_tmp = hash_path.with_suffix(hash_path.suffix + ".tmp")
    hash_tmp.write_text(sha + "\n", encoding="utf-8")
    hash_tmp.replace(hash_path)


def load_cached_embeddings_and_records(
    embeddings_path: Path, records_path: Path
) -> tuple[np.ndarray, list[dict[str, Any]]] | None:
    """Load the cached embedding matrix + records, or ``None`` on any failure.

    Returns ``None`` (rather than raising) so callers can transparently fall
    back to a rebuild on missing / corrupt / mismatched cache entries.

    Args:
        embeddings_path: Path to the ``*.npz`` cache (must contain key
            ``"embeddings"``).
        records_path: Path to the records JSON sibling.

    Returns:
        ``(embeddings_matrix, records_list)`` on a clean read, where the
        matrix is float32 and ``len(records) == matrix.shape[0]``;
        ``None`` if either file is missing, unreadable, or row-count
        mismatched.
    """

    if not embeddings_path.exists() or not records_path.exists():
        return None
    try:
        with np.load(embeddings_path) as bundle:
            embeddings = bundle["embeddings"].astype(np.float32, copy=False)
        with records_path.open("r", encoding="utf-8") as fh:
            records = json.load(fh)
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(records, list) or embeddings.shape[0] != len(records):
        # Defensive: stale or mismatched cache → force rebuild.
        return None
    return embeddings, records


def save_embeddings_and_records_atomically(
    embeddings_path: Path,
    records_path: Path,
    embeddings: np.ndarray,
    records: list[dict[str, Any]],
) -> None:
    """Persist the embedding matrix + records via per-file atomic renames.

    Each file is written to a ``*.tmp`` sibling then ``replace``-d into
    place, so a kill mid-write leaves the prior cache intact.

    ``np.savez`` auto-appends ``.npz`` to its target if the path doesn't
    already end in it; the temp name embeds ``.npz`` so the predicted
    written filename matches what we rename from.

    Args:
        embeddings_path: Destination ``.npz`` for the matrix.
        records_path: Destination ``.json`` for the records list.
        embeddings: Matrix to persist (cast to float32).
        records: Concern records list (same length as ``embeddings`` rows).
    """

    embeddings_path.parent.mkdir(parents=True, exist_ok=True)

    npz_tmp_arg = embeddings_path.with_name(embeddings_path.name + ".tmp.npz")
    np.savez(npz_tmp_arg, embeddings=embeddings.astype(np.float32, copy=False))
    npz_tmp_arg.replace(embeddings_path)

    json_tmp = records_path.with_suffix(records_path.suffix + ".tmp")
    with json_tmp.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
    json_tmp.replace(records_path)


__all__ = [
    "kb_sha256",
    "read_kb_hash",
    "write_kb_hash_atomically",
    "load_cached_embeddings_and_records",
    "save_embeddings_and_records_atomically",
]
