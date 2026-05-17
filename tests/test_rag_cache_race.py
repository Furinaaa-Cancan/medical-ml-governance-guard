"""Regression test for the KB-hash-then-load race (W18-D5 CASE-5, W20-F4 fix).

Background
----------
``scripts.rag.index.builder.build_or_load_index`` keys its embedding cache on
the sha256 of ``peer-review-kb.json``. Pre-W20-F4, the cold path read the KB
file twice: once through ``kb_sha256()`` to compute the hash, then again
through ``_load_kb()`` to parse JSON. If another process rewrote the KB in the
narrow window between those two reads, the function returned records built
from KB **v2** but cached/labelled with the hash of KB **v1** — a stale
return to its caller (subsequent calls self-heal on the next miss, but the
caller that triggered the race got wrong data).

The fix reads the KB bytes exactly once and feeds the same buffer to both
``hashlib.sha256`` and ``json.loads``, so the hash and the parsed entries
are guaranteed to describe the same byte sequence.

Test strategy
-------------
We instrument ``Path.read_bytes`` to observe every read the cold path makes
against the KB file. The contract under test is:

    On the cold path, ``build_or_load_index`` reads the KB bytes **at most
    once**; the bytes used to compute ``kb_hash`` are the same bytes used
    to build the returned records.

This is enforced deterministically (no thread-scheduling luck required) by
swapping the file contents the *second* time ``Path.read_bytes`` is called on
the KB path. With the fix, the second read never happens and the swap never
takes effect; the returned records correspond to v1 and the cached hash is
v1's hash. Without the fix, the swap leaks through and v2 records get
labelled with v1's hash — the race we are guarding against.

We monkeypatch ``embed_texts`` to a cheap stub so the test does not depend
on the sentence-transformer download.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("scripts.rag.index.builder")

from scripts.rag import config
from scripts.rag.index import builder as builder_mod
from scripts.rag.index import cache as cache_mod


def _tiny_kb(version: str) -> dict[str, Any]:
    """Return a minimal-but-valid peer-review KB structure tagged with ``version``."""
    return {
        "contract_version": "test.v1",
        "entries": [
            {
                "id": f"TEST-{version}-001",
                "paper_title": f"{version} paper",
                "reviewer_concerns": [
                    {
                        "concern_id": f"TEST-{version}-001-C01",
                        "severity": "HIGH",
                        "mlgg_gates": ["leakage_gate"],
                        "tags": [version],
                        "concern_text": f"concern body for {version}",
                    }
                ],
            }
        ],
    }


def _redirect_cache(
    monkeypatch: pytest.MonkeyPatch, kb_path: Path, cache_dir: Path
) -> None:
    """Point ``scripts.rag.config`` (and any builder re-exports) at ``tmp_path``."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "KB_PATH", kb_path, raising=True)
    monkeypatch.setattr(config, "CACHE_DIR", cache_dir, raising=True)
    monkeypatch.setattr(
        config, "EMBEDDINGS_CACHE", cache_dir / "concerns_embeddings.npz", raising=True
    )
    monkeypatch.setattr(
        config, "KB_HASH_CACHE", cache_dir / "kb_hash.txt", raising=True
    )
    for attr in ("KB_PATH", "CACHE_DIR", "EMBEDDINGS_CACHE", "KB_HASH_CACHE"):
        if hasattr(builder_mod, attr):
            monkeypatch.setattr(
                builder_mod, attr, getattr(config, attr), raising=True
            )


def _stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``embed_texts`` with a deterministic, dependency-free fake.

    The fake returns a unit-norm one-hot matrix of the right shape so any
    downstream shape / row-count invariants the builder enforces still hold,
    without pulling in sentence-transformers.
    """

    def fake_embed_texts(texts: list[str]) -> np.ndarray:
        n = len(texts)
        # Width is arbitrary as long as it's positive; pick something cheap.
        out = np.zeros((n, 4), dtype=np.float32)
        for i in range(n):
            out[i, i % 4] = 1.0
        return out

    monkeypatch.setattr(builder_mod, "embed_texts", fake_embed_texts, raising=True)


def test_parse_kb_bytes_helper_roundtrips(tmp_path: Path) -> None:
    """Sanity check on the helper that makes the race-free contract enforceable."""
    kb = _tiny_kb("v1")
    raw = json.dumps(kb).encode("utf-8")
    entries = builder_mod._parse_kb_bytes(raw, tmp_path / "kb.json")
    assert isinstance(entries, list)
    assert entries[0]["reviewer_concerns"][0]["concern_id"] == "TEST-v1-001-C01"


def test_cold_path_reads_kb_bytes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cold path must read the KB file exactly once.

    This is the structural guarantee that closes the W18-D5 CASE-5 race: if
    only one byte sequence is ever read, hash-vs-parse mismatch is impossible.
    """
    kb_path = tmp_path / "kb.json"
    cache_dir = tmp_path / ".cache"
    kb_path.write_text(json.dumps(_tiny_kb("v1")), encoding="utf-8")
    _redirect_cache(monkeypatch, kb_path, cache_dir)
    _stub_embed(monkeypatch)

    real_read_bytes = Path.read_bytes
    read_count = {"kb": 0}

    def counting_read_bytes(self: Path) -> bytes:
        if self == kb_path:
            read_count["kb"] += 1
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

    embeddings, records = builder_mod.build_or_load_index(
        kb_path=kb_path, force_rebuild=True
    )

    assert records, "cold path returned no records"
    assert read_count["kb"] == 1, (
        f"cold path read KB {read_count['kb']} times; race window requires "
        "exactly one read so hash and parse see identical bytes"
    )
    assert embeddings.shape[0] == len(records)


def test_concurrent_kb_swap_between_hash_and_parse_cannot_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic CASE-5 reproduction: a swap between reads must not leak.

    We instrument ``Path.read_bytes`` so that the *second* read of the KB
    path returns v2 content while the first returns v1. With the W20-F4 fix
    the cold path only reads once, so v2 content is never observed and the
    returned records all correspond to v1 — matching the cached hash. Without
    the fix the second read would feed v2 entries to ``_build_records`` while
    the hash captured at line 214 still belongs to v1: the records returned
    would no longer match the hash they're cached under.
    """
    kb_path = tmp_path / "kb.json"
    cache_dir = tmp_path / ".cache"
    v1_bytes = json.dumps(_tiny_kb("v1")).encode("utf-8")
    v2_bytes = json.dumps(_tiny_kb("v2")).encode("utf-8")
    kb_path.write_bytes(v1_bytes)
    _redirect_cache(monkeypatch, kb_path, cache_dir)
    _stub_embed(monkeypatch)

    real_read_bytes = Path.read_bytes
    state = {"reads_on_kb": 0, "second_read_bytes": None}

    def swapping_read_bytes(self: Path) -> bytes:
        if self != kb_path:
            return real_read_bytes(self)
        state["reads_on_kb"] += 1
        if state["reads_on_kb"] == 1:
            return v1_bytes
        # Simulate a concurrent writer flipping the file to v2 between reads.
        state["second_read_bytes"] = v2_bytes
        return v2_bytes

    monkeypatch.setattr(Path, "read_bytes", swapping_read_bytes)

    embeddings, records = builder_mod.build_or_load_index(
        kb_path=kb_path, force_rebuild=True
    )

    # The records ID is the canary: v1 has 'TEST-v1-001-C01', v2 has 'TEST-v2-001-C01'.
    concern_ids = {rec["concern_id"] for rec in records}
    assert concern_ids == {"TEST-v1-001-C01"}, (
        f"race leaked: builder returned v2 records {concern_ids} even though "
        "the hash was captured from v1 bytes — this is exactly W18-D5 CASE-5"
    )

    # And the cached hash must equal the hash of the bytes used for parsing.
    cached_hash = (cache_dir / "kb_hash.txt").read_text(encoding="utf-8").strip()
    assert cached_hash == hashlib.sha256(v1_bytes).hexdigest(), (
        "cached hash does not match the bytes that produced the records — "
        "hash/load buffer divergence"
    )
    # Sanity: only one read should have happened; the v2 swap should not have
    # been observed at all.
    assert state["reads_on_kb"] == 1, (
        f"cold path read KB {state['reads_on_kb']} times; the fix relies on a "
        "single read"
    )
    assert state["second_read_bytes"] is None, (
        "a second read happened and consumed v2 bytes — race window still open"
    )
    assert embeddings.shape[0] == len(records)
