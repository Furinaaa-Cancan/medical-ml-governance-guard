# W18-D5: RAG Cache Invalidation Audit

**Scope:** `scripts/rag/index/builder.py::build_or_load_index` + `scripts/rag/index/cache.py`. Verifies that edits to `references/case-studies/peer-review-kb.json` propagate to the next retrieval (no stale-cache silent serving). All probes run against `/tmp/W18_D5_kb_modified*.json` with `CACHE_DIR` monkey-patched to `/tmp/W18_D5_cache*/`; production cache and KB untouched.

## Verdict: **PASS (5/5)**

The on-disk SHA-256-keyed invalidation contract holds. Single-process edits, adds, and removes all bust the cache and force a rebuild on the next call. The concurrent-write race produces a transient mislabeled-cache window that self-corrects on the next invocation.

## Cache mechanism

- **Key:** `sha256(KB_file_bytes)` (full-file digest, `cache.py::kb_sha256`, 1 MB chunks).
- **Store:** `.cache/rag/kb_hash.txt` (atomic `*.tmp` + `os.replace`).
- **Artifacts:** `concerns_embeddings.npz` + `concerns_records.json`, written atomically per-file.
- **Decision (`builder.py:216-221`):** if `force_rebuild=False` AND `cached_hash == kb_hash` AND both artifact files load cleanly AND `embeddings.shape[0] == len(records)` → return cached. Any miss → cold rebuild.
- **No mtime, no version field, no env override of `KB_PATH`.** Pure content-hash invalidation. `CACHE_DIR` is module-level config; not per-call.

## Per-case results

| Case | Probe | Result | Note |
| --- | --- | --- | --- |
| 1 PRISTINE | cold build, then warm reload | **PASS** | cold 14.1 s build, warm reload 4.6 ms; hash matches |
| 2 EDIT | mutate `PR-001-C01.concern_text` to sentinel | **PASS** | hash changes, rebuild 2.4 s, new text in records, sentinel query returns edited concern at rank-1 |
| 3 ADD | append synthetic concern `PR-W18D5-ADD2` | **PASS** | n_records 817→818, new record present with exact text (v2 probe, `/tmp/W18_D5_results_v2.json`). v1 probe flagged a false-FAIL because the chosen sentinel ("ZZZUNICORNADD2026") is a nonce token poorly modeled by BGE-small — a *ranker* artifact, not a cache miss. |
| 4 REMOVE | drop `PR-001-C01` | **PASS** | n_records 818→817, removed concern absent from records and absent from top-5 for its former text |
| 5 RACE | mid-build overwrite (thread sleeps 50 ms then rewrites KB) | **PASS** | First build labels its artifacts with the pre-race hash (`hash_A`). Next normal call detects `stored_hash != current_kb_hash` and rebuilds → records reflect post-race state. |

## Failure modes observed / discussed

1. **Transient race window (CASE-5).** Between `kb_sha256()` (line 214) and `_load_kb()` (line 224), the KB file can be rewritten. The builder then persists records derived from KB-state-B but labels them with hash-of-KB-state-A. Until the next invocation, an in-process caller that *just* received the return value sees stale-labeled records. The mismatch is detected on the next call. **Not fail-closed in-process, but self-healing across calls.** No retries happen mid-call.
2. **`KB_PATH` is not env-overridable.** Tests must monkey-patch `config.KB_PATH` and `builder.KB_PATH` (the builder binds the symbol at import time). Acceptable for prod; mildly fragile for ops who want to swap KBs without restart.
3. **Hash file and artifacts are written non-atomically *as a set*.** Each file is written atomically, but a crash between `save_embeddings_and_records_atomically` (builder.py:239) and `write_kb_hash_atomically` (builder.py:245) leaves new artifacts under the *old* hash → next call rebuilds. Conservative; correct.
4. **Cache-key is content-only.** Two KBs with identical bytes but different paths share a cache. Not a problem in production (single KB), but a footgun for any future multi-KB deployment.

## Wave-N+ recommendations

- **R1 (HIGH, optional).** Eliminate the CASE-5 race window: read KB bytes once, then hash + parse from the in-memory buffer. ~5-line change in `_load_kb` + `build_or_load_index`. Preserves the existing on-disk contract.
- **R2 (LOW).** Document the "hash-then-load" race in `cache.py` module docstring so the next refactor doesn't widen the window.
- **R3 (LOW, defer).** When/if MLGG ships per-tenant or multi-KB retrieval, key the cache on `(KB_PATH, sha256)` instead of `sha256` alone. Not needed today.

## Artifacts

- Probes: `/tmp/W18_D5_probe.py`, `/tmp/W18_D5_probe_v2.py`
- Raw results: `/tmp/W18_D5_results.json`, `/tmp/W18_D5_results_v2.json`
- Run log: `/tmp/W18_D5_probe.log`
