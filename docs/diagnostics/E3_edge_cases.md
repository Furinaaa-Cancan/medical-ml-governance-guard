# E3: Edge Cases + CLI Parity + Failure Modes

## Summary
- Total tests: 38 (22 Python API + 10 CLI + 3 parity + 3 degradation + 1 concurrency batch of 5 threads)
- Crashes (unexpected exceptions): 0 in user-facing API; 1 contract-deviation observation (see below)
- API/CLI parity: **PASS** (3/3 cases produce identical id list in identical order)
- Graceful degradation: **PASS** (KB-missing → `[]`; non-graceful exceptions propagate as documented)
- Concurrency: **TESTED** (5 parallel `rag_query` calls; all identical results, no crashes)

## Test results

### A. Python API edge cases

| input | expected | actual | verdict |
|---|---|---|---|
| `rag_query("")` | `[]` | `list(len=0)` | OK |
| `rag_query("   ")` | `[]` | `list(len=0)` | OK |
| `rag_query("\n\t")` | `[]` | `list(len=0)` | OK |
| `rag_query(None)` | `[]` per defensive normalization | `list(len=0)` | OK |
| `rag_query(123)` | `[]` per defensive normalization | `list(len=0)` | OK |
| `rag_query("calibration", top_k=0)` | clamp → 1 result | `list(len=1)` | OK |
| `rag_query("calibration", top_k=-5)` | clamp → 1 result | `list(len=1)` | OK |
| `rag_query("calibration", top_k=1)` | 1 result | `list(len=1)` | OK |
| `rag_query("calibration", top_k=1000)` | `≤ 817` (KB size) | `list(len=50)` | **WARN** (silent cap at 50) |
| `rag_query("calibration", top_k=10000)` | `≤ 817` | `list(len=50)` | **WARN** (silent cap at 50) |
| `rag_query("x")` | small list | `list(len=5)` | OK |
| `rag_query("a"*10000)` | should not crash | `list(len=5)` | OK |
| unicode + emoji query | should not crash | `list(len=5)` | OK |
| `'; DROP TABLE concerns; --` | no crash (no DB) | `list(len=5)` | OK |
| `../../etc/passwd` | no crash | `list(len=5)` | OK |
| `gate="leakage_gate"` off-topic | list | `list(len=2)` | OK |
| `gate="nonexistent_gate_xyz"` | empty filter result | `list(len=0)` | OK |
| `gate=""` | treated as no gate? | `list(len=5)` | OK (empty string falsy) |
| `failure_codes=[]` | treated as no codes | `list(len=5)` | OK |
| `failure_codes=None` | no codes | `list(len=5)` | OK |
| `failure_codes=[""]` | no crash | `list(len=5)` | OK |
| `failure_codes=["A"*1000]` | no crash | `list(len=5)` | OK |

### B. CLI invocations

| command | expected exit | actual exit | output snippet | verdict |
|---|---|---|---|---|
| `--help` | 0 | 0 | `usage: scripts/rag/query.py ...` | OK |
| (no args) | 2 | 2 | `error: the following arguments are required: query` | OK |
| `"calibration"` | 0 | 0 | table with 5 rows | OK |
| `"calibration" --format json` | 0 | 0 | well-formed JSON array | OK |
| `"calibration" --top-k 3` | 0 | 0 | 3 rows | OK |
| `"calibration" --top-k 0` | 2 | 2 | `error: --top-k must be a positive integer` | OK |
| `"calibration" --top-k abc` | 2 | 2 | `error: argument --top-k: invalid int value: 'abc'` | OK |
| `"calibration" --format xml` | 2 | 2 | `error: argument --format: invalid choice: 'xml'` | OK |
| `"calibration" --codes ""` | 0 | 0 | table (codes parsed as None) | OK |
| `"calibration" --codes "a,,b"` | 0 | 0 | table (empty token dropped) | OK |
| `"missing CI" --gate evaluation_quality_gate --codes "MLGG-E01,MLGG-E02"` | 0 | 0 | 5 rows, top hit PR-032-C02 | OK |

### C. Parity

| Query | Python ids | CLI ids | Match? |
|---|---|---|---|
| `"calibration"` (short) | `[PR-EXP-0092-C03, PR-110-C03, PR-EXP-0109-C03, PR-EXP-0092-C04, PR-EXP-0155-C03]` | identical | YES |
| `"missing CI"` + `gate=evaluation_quality_gate` | `[PR-032-C02, PR-003-C05, PR-035-C05, PR-102-C01, PR-EXP-0170-C02]` | identical | YES |
| `"label leakage"` + `codes=[MLGG-F01, MLGG-S01]` | `[PR-107-C04, PR-014-C01, PR-072-C01, PR-002-C03, PR-EXP-0084-C08]` | identical | YES |

Parity is preserved. CLI is a thin wrapper as advertised.

### D. Graceful degradation

- **`build_or_load_index(kb_path=<missing>)`** raises `FileNotFoundError("[Errno 2] No such file or directory: ...")` — matches docstring. Good.
- **`rag_query(...)` when `build_or_load_index` raises `FileNotFoundError`** (mocked via `unittest.mock.patch`): returns `[]` cleanly. Matches docstring promise (1). Good.
- **`rag_query(...)` when sibling-module import fails** (mocked `_import_sibling_modules` to raise `ImportError`): raises `ImportError` — NOT caught by `query.py:108-111`. This is a contract-vs-code asymmetry: `query.py` catches the *initial* `from scripts.rag.retrieval.hybrid import hybrid_rank` ImportError, but `hybrid_rank`'s own deferred sibling imports convert any ImportError to **`RuntimeError`** before re-raising (see `hybrid.py:67-71`, `:75-79`). In practice the ImportError is therefore caught at the first layer; the only realistic way to leak is if a sibling module exists but throws at runtime, which would already be a `RuntimeError` (correctly propagated). **No actual user-facing bug, but the docstring promise "embeddings unavailable → `[]`" is slightly imprecise.**
- **`rag_query(...)` when ranker raises `RuntimeError`** (mocked): propagates as documented. Good.

### E. Concurrency

5 threads called `rag_query("calibration", top_k=5)` after cache warm-up. All 5 returned the same `concern_id` list as the baseline. No exceptions, no garbled output, no race conditions observed at this scale.

## Bugs found (severity ranked)

1. **MEDIUM — Silent `top_k` cap at 50.** The `rag_query` docstring says `top_k` is "Maximum number of concerns to return"; it does not warn that the hybrid ranker only considers `DEFAULT_MAX_CANDIDATES_BEFORE_RERANK = 50` dense candidates, so any `top_k > 50` is silently truncated. KB has 817 concerns. Users requesting `top_k=200` get only 50 with no indication. **Fix options:** (a) document the cap in the docstring + CLI `--top-k` help; (b) raise `dense_top_k = max(50, top_k)` so the ranker actually considers more candidates when the caller asks; (c) emit a warning when `top_k > DEFAULT_MAX_CANDIDATES_BEFORE_RERANK`. Option (b) is the principled fix.

2. **LOW — Docstring/code contract mismatch on ImportError.** `rag_query` docstring claims `sentence_transformers missing` produces `[]`, but `hybrid_rank._import_sibling_modules` converts ImportError to RuntimeError, which `rag_query` does **not** catch. Today this is benign (the top-level import in `query.py:108-111` catches the realistic failure mode first), but it's a latent landmine if someone refactors `hybrid.py` to import siblings at module level. **Fix:** either expand the docstring to be precise about which import paths degrade gracefully, or also catch `RuntimeError` matching `"required by retrieval.hybrid but could not be imported"` in `query.py:rag_query`.

3. **LOW — `gate=""` and `gate="nonexistent_gate_xyz"` behave differently.** Empty string is treated as no gate (returns 5 results); a non-existent gate name filters to 0 results. This is internally consistent (empty-string is falsy in Python) but could surprise programmatic callers. Worth a one-line docstring note.

4. **LOW — `failure_codes=[""]` and `failure_codes=["A"*1000]` are silently accepted.** No validation. Returns same as `failure_codes=None`. Acceptable for a lenient public API but a `--strict` mode could reject unknown codes.

## Verdict

- **Production-ready: Conditional Yes.** The public API surface is robust against the full standard battery of bad inputs (empty strings, None, type errors, injection-style strings, large unicode, oversize args). Parity between Python API and CLI is exact. KB-missing degradation works as advertised. Concurrency is safe at small scale.
- **Must-fix before release:** Document (or, better, fix) the silent `top_k > 50` cap. This is the only finding that could mislead a downstream caller into thinking they have the full ranking when they only have the top-50-of-dense-candidates rerank pool.
- **Should-fix:** Tighten the ImportError-vs-RuntimeError contract language in the docstring.
- **Nice-to-have:** Note the empty-vs-invalid-gate distinction in the docstring.
