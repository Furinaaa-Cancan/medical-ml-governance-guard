"""Tests for the ``excluded_paper_ids`` parameter on ``build_or_load_index``.

Background (W22-Y1)
-------------------
The NCPR benchmark evaluates retrieval honesty: for each paper-under-test,
``build_or_load_index`` must be able to produce a KB index that excludes that
paper's reviewer concerns. Otherwise the retriever can trivially "win" by
returning a concern from the paper it is being scored against — leaking the
ground truth into the prediction.

This module exercises the four invariants that protect that contract:

1. **Default behavior is preserved.** Calling without ``excluded_paper_ids``
   (or with ``None``) must return the full set of concerns and use the
   pre-W22 KB-hash-only cache key, so any cache already on disk stays valid.
2. **Filtering actually drops concerns.** Excluding a paper must remove
   exactly that paper's concerns from the returned records.
3. **Cache signature reflects the exclusion set.** Two builds with different
   excluded sets must write distinct ``kb_hash.txt`` keys; if they shared a
   key the second caller would be silently served the first caller's index.
4. **Unknown ids are a no-op (with a warning), not a crash.** Callers iterate
   over paper-id lists that may be supersets of the live KB; an unknown id
   must not break the build.

The tests follow the redirect-config / stub-embed pattern used by
``test_rag_cache_race.py`` so they don't pull in sentence-transformers or
touch the real ``.cache/rag/`` directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("scripts.rag.index.builder")

from scripts.rag import config
from scripts.rag.index import builder as builder_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kb_with_papers(paper_ids: list[str], concerns_per_paper: int = 2) -> dict[str, Any]:
    """Build a minimal-but-valid peer-review KB with the given paper ids.

    Each paper gets ``concerns_per_paper`` reviewer concerns whose
    ``concern_id`` encodes both the paper id and the concern index so
    assertions can identify exactly which concerns survived a filter.
    """

    entries: list[dict[str, Any]] = []
    for pid in paper_ids:
        entries.append(
            {
                "id": pid,
                "paper_title": f"{pid} paper",
                "reviewer_concerns": [
                    {
                        "concern_id": f"{pid}-C{i:02d}",
                        "severity": "HIGH",
                        "mlgg_gates": ["leakage_gate"],
                        "tags": [pid],
                        "concern_text": f"concern body for {pid} #{i}",
                    }
                    for i in range(concerns_per_paper)
                ],
            }
        )
    return {"contract_version": "test.v1", "entries": entries}


def _redirect_cache(
    monkeypatch: pytest.MonkeyPatch, kb_path: Path, cache_dir: Path
) -> None:
    """Point ``scripts.rag.config`` (and builder re-exports) at ``tmp_path``."""

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
    """Replace ``embed_texts`` with a cheap unit-norm one-hot fake."""

    def fake_embed_texts(texts: list[str]) -> np.ndarray:
        n = len(texts)
        out = np.zeros((n, 4), dtype=np.float32)
        for i in range(n):
            out[i, i % 4] = 1.0
        return out

    monkeypatch.setattr(builder_mod, "embed_texts", fake_embed_texts, raising=True)


def _write_kb(tmp_path: Path, paper_ids: list[str], per_paper: int = 2) -> Path:
    """Materialize a test KB at ``tmp_path/kb.json`` and return the path."""

    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps(_kb_with_papers(paper_ids, per_paper)), encoding="utf-8"
    )
    return kb_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_default_excluded_none_returns_full_index_and_legacy_cache_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``excluded_paper_ids=None`` must be a no-op AND keep the legacy cache key.

    Two guarantees in one test:
      * record count equals the full KB (nothing dropped); and
      * the persisted ``kb_hash.txt`` is the bare sha256 of the KB bytes (no
        compound suffix), so any cache already produced by pre-W22-Y1
        callers is still considered valid by this code path.
    """

    kb_path = _write_kb(tmp_path, ["PR-001", "PR-002", "PR-003"], per_paper=2)
    cache_dir = tmp_path / ".cache"
    _redirect_cache(monkeypatch, kb_path, cache_dir)
    _stub_embed(monkeypatch)

    embeddings, records = builder_mod.build_or_load_index(
        kb_path=kb_path, force_rebuild=True
    )

    assert len(records) == 6, "default path should return all 6 concerns"
    assert embeddings.shape[0] == 6

    cached_hash = (cache_dir / "kb_hash.txt").read_text(encoding="utf-8").strip()
    expected = hashlib.sha256(kb_path.read_bytes()).hexdigest()
    assert cached_hash == expected, (
        f"default cache key changed from bare KB sha256 to {cached_hash!r}; "
        "this would invalidate every existing on-disk cache"
    )


def test_excluding_paper_drops_only_its_concerns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Excluding ``PR-001`` removes its 2 concerns and keeps the rest intact."""

    kb_path = _write_kb(tmp_path, ["PR-001", "PR-002", "PR-003"], per_paper=2)
    cache_dir = tmp_path / ".cache"
    _redirect_cache(monkeypatch, kb_path, cache_dir)
    _stub_embed(monkeypatch)

    embeddings, records = builder_mod.build_or_load_index(
        kb_path=kb_path, force_rebuild=True, excluded_paper_ids=["PR-001"]
    )

    paper_ids = {rec["paper_id"] for rec in records}
    assert paper_ids == {"PR-002", "PR-003"}, (
        f"PR-001 leaked into the holdout index: {paper_ids}"
    )
    assert len(records) == 4
    assert embeddings.shape[0] == 4

    concern_ids = {rec["concern_id"] for rec in records}
    assert all(not cid.startswith("PR-001") for cid in concern_ids)


def test_distinct_exclusion_sets_produce_distinct_cache_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two excluded sets MUST yield two cache signatures.

    Critical invariant: if the cache key didn't depend on the exclusion set,
    a holdout call right after a different holdout call would hit the wrong
    cached records (the wrong paper excluded) and silently return a leaky
    index. We assert the persisted ``kb_hash.txt`` differs between the two
    runs and that neither equals the bare KB hash (the default cache key).
    """

    kb_path = _write_kb(tmp_path, ["PR-001", "PR-002", "PR-003"], per_paper=2)
    cache_dir = tmp_path / ".cache"
    _redirect_cache(monkeypatch, kb_path, cache_dir)
    _stub_embed(monkeypatch)

    builder_mod.build_or_load_index(
        kb_path=kb_path, force_rebuild=True, excluded_paper_ids=["PR-001"]
    )
    key_after_first = (cache_dir / "kb_hash.txt").read_text(encoding="utf-8").strip()

    builder_mod.build_or_load_index(
        kb_path=kb_path, force_rebuild=True, excluded_paper_ids=["PR-002"]
    )
    key_after_second = (cache_dir / "kb_hash.txt").read_text(encoding="utf-8").strip()

    bare_kb_hash = hashlib.sha256(kb_path.read_bytes()).hexdigest()

    assert key_after_first != key_after_second, (
        "exclusion sets {'PR-001'} and {'PR-002'} produced the same cache key — "
        "a holdout build would be served the wrong cached index"
    )
    assert key_after_first != bare_kb_hash, (
        "exclusion-set build reused the legacy bare-KB cache key, which "
        "would collide with default-path callers"
    )
    assert key_after_second != bare_kb_hash

    # Also assert the compound-key shape: "<kb_hash>:<excl_sig>".
    for key in (key_after_first, key_after_second):
        prefix, _, suffix = key.partition(":")
        assert prefix == bare_kb_hash, "compound key prefix must be the KB sha256"
        assert len(suffix) == 64, "compound key suffix must be a sha256 hex digest"


def test_excluding_unknown_paper_id_is_noop_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown paper ids must NOT crash; they should log a warning instead.

    Holdout callers iterate over paper-id lists that may be supersets of the
    current KB (e.g. ids extracted from external metadata). Hardening here
    keeps the benchmark runner robust without quietly hiding the mismatch —
    we want the warning in the log for the audit trail.
    """

    kb_path = _write_kb(tmp_path, ["PR-001", "PR-002"], per_paper=2)
    cache_dir = tmp_path / ".cache"
    _redirect_cache(monkeypatch, kb_path, cache_dir)
    _stub_embed(monkeypatch)

    caplog.set_level(logging.WARNING, logger="scripts.rag.index.builder")

    _, records = builder_mod.build_or_load_index(
        kb_path=kb_path,
        force_rebuild=True,
        excluded_paper_ids=["PR-DOES-NOT-EXIST"],
    )

    # Nothing matched the unknown id, so all 4 concerns survive.
    assert len(records) == 4
    assert {rec["paper_id"] for rec in records} == {"PR-001", "PR-002"}

    # And we got an audit-trail warning naming the missing id.
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("PR-DOES-NOT-EXIST" in m for m in warning_messages), (
        f"expected a warning naming the unknown paper id, got: {warning_messages}"
    )


def test_helpers_normalize_and_sign_excluded_set() -> None:
    """Unit-level guard on the helpers that back the cache-signature change.

    Empty / ``None`` collapse to ``frozenset()`` and the empty signature
    string (= legacy cache key). A non-empty set produces a deterministic
    64-char hex digest that's order-independent — two equivalent sets must
    sign identically, else cache hits would depend on caller iteration order.
    """

    assert builder_mod._normalize_excluded(None) == frozenset()
    assert builder_mod._normalize_excluded([]) == frozenset()
    assert builder_mod._normalize_excluded(["", None]) == frozenset()

    assert builder_mod._exclusion_signature(frozenset()) == ""

    sig_ab = builder_mod._exclusion_signature(frozenset({"A", "B"}))
    sig_ba = builder_mod._exclusion_signature(frozenset({"B", "A"}))
    assert sig_ab == sig_ba, "signature must be order-independent"
    assert len(sig_ab) == 64

    sig_other = builder_mod._exclusion_signature(frozenset({"A", "C"}))
    assert sig_ab != sig_other, "distinct sets must sign distinctly"
