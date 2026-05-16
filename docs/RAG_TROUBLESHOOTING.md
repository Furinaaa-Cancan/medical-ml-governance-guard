# RAG Layer Troubleshooting Guide

Companion to the "Known Limitations" sections of `README.md` / `README_EN.md`.
Covers diagnostics + fixes for the most common RAG issues surfaced during the
5-agent strict-eval, the G-wave, and the H-wave.

## Quick triage

| Symptom | Likely cause | Section |
|---|---|---|
| All `_bm25_score == 0` | Free-text mode (BM25 gate-anchored) | §1 |
| `_final_score` caps ~0.46 in free-text | Same — re-normalization shows higher | §1 |
| First query takes >5s | Model not pre-loaded | §2 |
| Query returns 0 hits | KB mismatch or `sentence_transformers` missing | §3 |
| Same paper appears 2-3x in top-5 | MMR not firing or weak tuning | §4 |
| Gate shows "No related peer-review concerns" | Either honest empty (`rag_optional`) or KB coverage gap | §5 |
| CI red on README drift | New file added without README count bump | §6 |
| `MLGG-E01` codes don't surface relevant results | BM25 `TAG_SYNONYMS` gap (fixed H1) | §7 |
| Cache won't rebuild after KB change | sha256 check passing unexpectedly | §8 |

---

## §1 BM25 inactive in free-text mode

CLI: `python3 scripts/rag/query.py "calibration"` — no `--gate`, no `--codes`.

In this mode the BM25 weight (0.3) is unallocated, so the remaining 3 signals
are re-normalized (dense 0.71, tag 0.21, severity 0.07). `_match_reasons`
includes `bm25_inactive_free_text` for transparency (see
`scripts/rag/retrieval/hybrid.py:594`).

**Fix** — pass `(gate, codes)` for full 4-signal ranking:

```python
from scripts.rag import rag_query
rag_query(
    "calibration",
    gate="evaluation_quality_gate",
    failure_codes=["MLGG-E01"],
)
```

Or from CLI: `mlgg rag "..." --gate G --codes c1,c2`.

---

## §2 Cold start latency

First call: ~11s (SentenceTransformer load) + ~250ms (BGE forward warm-up).
Steady-state: ~12ms / query.

Mitigation:

```python
from scripts.rag.query import prewarm
prewarm()  # call at service start / worker pool init
```

Or CLI: `python3 scripts/rag/query.py --prewarm` returns JSON timing
(see `scripts/rag/query.py:127`, `:330`).

---

## §3 Zero hits / import errors

- `ImportError: sentence_transformers` → `pip install -r requirements-optional.txt`
- 0 hits despite valid query → check KB path: `scripts.rag.config.KB_PATH`
  (resolves to `references/case-studies/peer-review-kb.json`).
- Empty query → returns `[]` by design (graceful degradation).
- Mocked KB missing → `[]` (test-fixture path; not a bug).

---

## §4 Same-paper duplicates in top-5

Post-G4, MMR diversity reranking is wired but configurable
(`scripts/rag/config.py:117-118`):

- `config.MMR_LAMBDA = 0.7` (relevance vs diversity tradeoff)
- `config.MMR_SAME_PAPER_PENALTY = 0.5`

If duplicates still appear at top-K > 5, tune `MMR_LAMBDA` down (e.g. 0.6).
Cross-paper near-duplicates are handled by MMR's dense-cosine similarity.

---

## §5 "No related peer-review concerns retrieved"

Two interpretations:

- **Honest empty** (`rag_optional=True`): infra/aggregation gates by design.
  Currently 4 such gates in `scripts/core/_gate_registry.py` (lines 138,
  152, 622, 635) — `manifest_lock`, `request_contract_gate`,
  `self_critique_gate`, `security_audit_gate`. No placeholder rendered.
- **KB coverage gap**: gate isn't `rag_optional` but KB has no tagged
  concerns. Run
  `pytest tests/test_rag_regression.py::test_all_33_gates_have_rag_coverage_or_are_rag_optional`
  to identify gaps. Fix: re-tag existing concerns OR add new ones to the
  KB, then `git commit` to invalidate the cache via sha256 change.

---

## §6 README count drift

CI's `tests/test_check_readme_stats.py::TestDriftLint` enforces that
tree-listing counts in `README.md` / `README_EN.md` match real file
counts on disk.

Activate the local guard (prevents push of drift):

```bash
pip install pre-commit
pre-commit install
```

The `readme-stats-drift` hook (`.pre-commit-config.yaml:77`) runs
`scripts/diagnostics/check_readme_stats.py` on every commit
(`always_run`, so it triggers even if no README file is staged).
A pre-push backstop also lives at `.githooks/pre-push`.

One-off check: `python3 scripts/diagnostics/check_readme_stats.py`.

Drift sources: adding/moving files under `scripts/{diagnostics,review,rag,...}/`
or `tests/`. Update the matching tree-listing count in both READMEs.

---

## §7 MLGG canonical codes ineffective

Pre-H1: `MLGG-E01` had no entry in `bm25.TAG_SYNONYMS`. The tokenizer
split it into `mlgg` and `e01` (the latter discarded as a 2-char token
unless allowlisted), so BM25 never surfaced CI-related concerns.

Post-H1 (`scripts/rag/retrieval/bm25.py`):

- Canonical codes (`MLGG-S01..E02`) now map to semantic tags via
  `TAG_SYNONYMS` (line 107).
- 2-char tokens like `ci` are preserved through `SHORT_TOKEN_ALLOWLIST`
  (line 104): `{"ci", "r2", "ml", "ai", "df", "or", "hr"}`.

If a new canonical code is added to `CLAUDE.md`, extend `TAG_SYNONYMS`
in `scripts/rag/retrieval/bm25.py` to keep it discoverable.

---

## §8 Cache won't rebuild

`scripts/rag/index/cache.py` uses sha256 of the KB file (`kb_sha256`,
line 25). If the cache incorrectly stays warm after a KB edit:

- Verify the hash changed:
  `sha256sum references/case-studies/peer-review-kb.json`
- Force rebuild from Python:
  ```python
  from scripts.rag.index.builder import build_or_load_index
  build_or_load_index(force_rebuild=True)
  ```
- Nuclear: `rm -rf .cache/rag/` then re-run any query (cold rebuild ~15s).

---

## §9 Adding a new gate to RAG

When you add a gate to `scripts/core/_gate_registry.py`:

1. Decide: peer-review-relevant (default) or `rag_optional=True`
   (infra/aggregation/security)?
2. If relevant: tag ≥3-5 KB concerns with the new gate name and commit
   the KB diff.
3. Bump the gate count assertion in
   `tests/test_rag_regression.py::test_all_33_gates_have_rag_coverage_or_are_rag_optional`
   (33 → 34, etc.).
4. Update the relevant tree-listing counts in `README.md` /
   `README_EN.md` if the gate ships with new source/test files.

---

## Reference: source files

- `scripts/rag/__init__.py` — public API (`rag_query`)
- `scripts/rag/config.py` — weights, thresholds, paths, MMR knobs
- `scripts/rag/query.py` — CLI + `prewarm()`
- `scripts/rag/retrieval/{dense,bm25,hybrid}.py` — 3 signals + fusion + MMR
- `scripts/rag/index/{builder,cache}.py` — embedding index + sha256 cache
- `scripts/core/gate_rag_bridge.py` — gate-to-KB bridge
- `scripts/core/_gate_registry.py` — gate registry (`rag_optional` flag)
- `scripts/diagnostics/check_readme_stats.py` — drift linter
