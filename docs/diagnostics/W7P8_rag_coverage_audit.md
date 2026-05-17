# W7-P8: scripts/rag/ test coverage audit

## Aggregate
- Lines (Stmts): 1156 total / 754 covered / 402 uncovered (65%)
- Tests run: 177 passed, 1 skipped, 17 deselected (1m40s)
- Modules: 13 measured
  - >=85%: 9 (config, embeddings, builder, cache, dense, hybrid, bridge, rag/__init__, retrieval/__init__)
  - 70-85%: 0
  - <70%: 4 (harness 31%, run_eval 37%, query 45%, bm25 48%)

## Per-module

| Module | Lines | Cov% | Uncovered functions / blocks | Action |
|--------|------:|-----:|------------------------------|--------|
| scripts/rag/__init__.py | 2 | 100% | - | none |
| scripts/rag/config.py | 24 | 100% | - | none |
| scripts/rag/embeddings.py | 30 | 90% | OSError fallback in get_model (44-45), normalize-zero guard (120) | edge OK |
| scripts/rag/evals/harness.py | 145 | 31% | parse_args, _retrieve_bm25_only, print_human_summary, check_regression, main (CLI driver) | acceptable — exercised by harness CLI tests not in this slice |
| scripts/rag/evals/run_eval.py | 95 | 37% | aggregate/render_markdown/main CLI path (140-301) | acceptable — CLI driver |
| scripts/rag/index/builder.py | 73 | 90% | KB FileNotFound, malformed-shape, empty-records, embed-dim mismatch (defensive raisers) | edge OK |
| scripts/rag/index/cache.py | 47 | 87% | OSError on read (57-58), JSONDecodeError / shape-mismatch (98-108) | edge OK |
| scripts/rag/query.py | 101 | 45% | `_truncate`, `_render_table`, `_parse_codes` partial, full `main()` CLI path (260-393) | CLI driver — covered by test_mlgg_rag_subcommand integration |
| scripts/rag/retrieval/__init__.py | 0 | 100% | - | none |
| scripts/rag/retrieval/bm25.py | 254 | 48% | `_sanitize_text` non-str path, `_sanitize_tags` non-list, `retrieve_by_text` (755-788), `retrieve_combined` (713-729), `retrieve_by_category/domain/paper` (636-683), `count_concerns_with_tag` synonym branch (812-819), `get_stats_summary` (796-798), legacy `format_peer_context` w/ display caps (840-867) | mostly LEGACY library helpers not on the hybrid hot path; one real gap (see below) |
| scripts/rag/retrieval/dense.py | 31 | 94% | empty-query guard (76), missing-model error (88) | edge OK |
| scripts/rag/retrieval/hybrid.py | 237 | 89% | scattered defensive branches (severity-tier ties, MMR degenerate cases, empty top-k) | edge OK |
| scripts/core/gate_rag_bridge.py | 117 | 92% | `_is_weak_match` malformed-score branch (202-204) + string-reasons coercion (208); `_is_low_confidence` malformed-dense branch (250-251); `_synthesize_query` gate-name-only fallback (295); `_format_reasons` string branch (391); registry-lookup exception swallow (443-444) | TRIVIAL — added focused test (see Action taken) |

## Gaps worth filling

1. **bridge `_is_weak_match` / `_is_low_confidence` malformed-input branches** — narrow defensive guards on `_final_score` / `_dense_score` parse failure. Easy to exercise with crafted concern dicts. FIXED THIS WAVE.
2. **bridge `_synthesize_query(gate_name=...)` empty-input fallback** — 1-line branch covering the contract that bare gate name is a valid query. Exercised by adding direct unit test. FIXED THIS WAVE.
3. **bridge registry-lookup exception** (443-444) — defensive try/except around `_gate_registry` import in `format_for_gate_report`. Worth a focused test (would require monkey-patching). FIXED THIS WAVE.
4. **bm25 `retrieve_by_text`** (755-788) — substantive helper (multi-term, stopword filter, min_match_ratio, ranking) still used by some agent flows. Currently UNCOVERED. Deserves a Wave 8 backlog test: feed a tiny KB fixture, assert ratio gating + sort order.
5. **bm25 legacy `retrieve_by_category/domain/paper`** — thin wrappers around `_collect_concerns`; low risk, but a single parametrised test could close all three.

## Recommendation

- **Trivial gaps fixed now**: added `tests/test_gate_rag_bridge_defensive.py` with 5 focused tests for the malformed-input / fallback branches in `gate_rag_bridge.py`. Lifts bridge from 92% → ~98% with no infra cost.
- **Wave 8 backlog** (do not fix this wave):
  - `retrieve_by_text` BM25 helper: build a 5-concern KB fixture, exercise min_match_ratio = 0.4 / 0.6 / 1.0 boundary and stopword stripping.
  - `retrieve_by_category/domain/paper` parametric test.
  - harness.py / run_eval.py: their CLI `main()` paths are already smoke-tested by `test_rag_evals_harness.py` / `test_rag_run_eval.py` but the *report-rendering* helpers aren't unit-tested directly. Acceptable — integration coverage is sufficient.
- **Do NOT chase** harness/run_eval/query line counts; the uncovered ranges are argparse + I/O wiring already proxied through smoke tests.
