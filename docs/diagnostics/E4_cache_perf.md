# E4: Cache + Performance Benchmarks

## Summary

- Warm load: mean **4.9 ms**, max 7.8 ms (target <100ms): **PASS**
- Cold build: **15.1 s** (target <60s): **PASS**
- Cache invalidation: **PASS** (sha256-keyed; mutated KB triggers rebuild, new record present)
- Query P50/P95: **12.3 / 31.4 ms** (P99-ish max 228 ms = first-query model warm-up)
- Memory leak: **NONE** (RSS decreased after 50 extra queries — see notes)
- Atomic writes: **VERIFIED** (write-to-`*.tmp` then `Path.replace` in `cache.py` for all 3 files)

## Per-test results

### Test 1 — Warm load latency (5 runs)

| run | ms    |
|-----|-------|
| 1   | 7.8   |
| 2   | 4.2   |
| 3   | 4.2   |
| 4   | 4.1   |
| 5   | 4.0   |

Mean **4.9 ms**, max **7.8 ms** (first call includes lazy numpy import). Shape `(817, 384)`, 817 records. ~20× under spec target of <100ms. The cache hit short-circuits before `embed_texts` runs — verified in `builder.build_or_load_index` lines 216–221.

### Test 2 — Cold build latency

After moving `.cache/rag` → `.cache/rag.bak`, a single cold run produced:
- **Cold build: 15.1 s** (817 concerns × 384-dim BGE-small embeddings on CPU).
- Resulting `concerns_embeddings.npz`, `concerns_records.json`, `kb_hash.txt` byte-identical to the backup (`shasum` diff = 0). This is strong evidence the build is **deterministic** for the same KB sha — good news for reproducibility audits.
- Cache restored cleanly (mtime preserved; backup folder removed; real cache back in place).

Well under the spec's pessimistic 30–60 s.

### Test 3 — Cache invalidation correctness

Performed against a temp KB at `tempfile.mkdtemp()/kb.json` (Note: because cache dir is fixed at `.cache/rag/`, this evicted the real cache — I pre-backed-up to `.cache/rag.bak2` and restored after the test).

| step                          | time     | n_records |
|-------------------------------|----------|-----------|
| First build (cold, tmp KB)    | 15.3 s   | 817       |
| Second load (warm, same KB)   | 6.7 ms   | 817       |
| After append new concern      | 2.2 s    | **818**   |

Assertion `any(r["concern_id"] == "PR-TEST-C01" for r in recs3)` succeeded → rebuild path correctly observed the mutation. Curiosity: the post-mutate build took 2.2 s vs. 15 s cold — embedding model was already loaded in-process, so only the actual encode (817+1 → 384) ran. That's a pleasant property for callers that pre-warm the model.

After Test 3 I restored `.cache/rag.bak2` → `.cache/rag/`, confirmed `kb_hash.txt` (`670617de…0d6c4`) matches `sha256(peer-review-kb.json)`, and verified warm load = 8.7 ms with 817 records.

### Test 4 — Query latency (60 queries, 12 distinct × 5)

| metric | ms    |
|--------|-------|
| min    | 9.6   |
| P50    | 12.3  |
| mean   | 19.8  |
| P95    | 31.4  |
| max    | 228.4 |

P50 and P95 are comfortably interactive. The max (228 ms) is the **first** query — sentence-transformer model load + first BM25 index build dominate. Subsequent queries are ~10–30 ms each. Interactive-CLI verdict: comfortable; no perceived lag.

### Test 5 — Memory footprint

`psutil` available (so RSS is direct, not `ru_maxrss` proxy).

| snapshot                        | RSS (MB) | delta            |
|---------------------------------|----------|------------------|
| baseline (after imports only)   | 20.3     | —                |
| after first query (model load)  | 616.6    | +596.3           |
| after 50 additional queries     | 457.5    | **−159.1**       |

Memory **decreased** after sustained query load — no leak. The negative delta is likely torch deallocating one-off warm-up buffers (autograd scratch, embedding-pass workspaces) after the first encode. Steady-state ~460 MB for an in-process model load is reasonable for BGE-small + tokenizer + 817×384 matrix.

### Test 6 — Atomic write safety (code inspection)

`scripts/rag/index/cache.py`:

- `write_kb_hash_atomically` (lines 62–74): writes to `hash_path.with_suffix(suffix + ".tmp")`, then `.replace(hash_path)`. **Atomic on POSIX.**
- `save_embeddings_and_records_atomically` (lines 112–143):
  - npz: writes to `<name>.tmp.npz`, then `.replace(embeddings_path)`. Note the temp filename explicitly embeds `.npz` so it matches what `np.savez` actually writes (defends against `np.savez`'s auto-suffix quirk). **Atomic.**
  - records JSON: writes to `<path>.tmp`, then `.replace(records_path)`. **Atomic.**
- `load_cached_embeddings_and_records` (lines 77–109): swallows `OSError/KeyError/ValueError/JSONDecodeError` and returns `None`, **plus** validates `embeddings.shape[0] == len(records)` — protects against an embedding/record row-count drift even if both files load cleanly. Good defensive code.

**One minor non-issue**: hash file is written **after** the data files (`builder.py` lines 239–245). If a crash happens between `save_embeddings_and_records_atomically` and `write_kb_hash_atomically`, the next call sees a fresh npz/json but stale (or missing) `kb_hash.txt`. Behavior: cache miss → rebuild. **Safe** — invariant "if `kb_hash.txt` matches current sha, then the npz/json correspond to it" is preserved.

## Concerns

- **None blocking.** All targets met by wide margins. Cold build is 2–4× faster than spec.
- **Minor — first-query latency spike (228 ms)** is the only "rough edge." Could be smoothed by lazy-loading the sentence-transformer model in a background thread on process start, or by exposing a `prewarm()` helper. Acceptable as-is for both CLI (`mlgg`) and gate-bridge (one-shot) use cases.
- **Minor — steady-state RSS ~460 MB** is fine for an interactive CLI but worth flagging if MLGG ever runs many concurrent gate workers; each process re-pays the BGE-small load. Not a regression vs. spec, just a heads-up.
- **Observation (not a defect): builds are deterministic.** Re-running the cold build produced byte-identical npz / records / hash files. That's a desirable property and worth noting in the docstrings/spec so future maintainers don't break it by accident (e.g. introducing nondeterministic batch order in `embed_texts`).

## Verdict

- **Performance acceptable? YES** — all 5 numeric targets exceeded.
- **Cache correctness verified? YES** — sha256 invalidation works, atomic writes in place, hash-after-data ordering is crash-safe, restored real cache verified against current KB sha.
