# W15-A4 — Type Annotation Coverage Audit (Public Surface)

**Date:** 2026-05-17
**Scope:** `scripts/gates/`, `scripts/rag/**`, `scripts/diagnostics/` (READ-ONLY)
**Method:** AST walk via `/tmp/W15_A4_walker.py` — module-level `FunctionDef` / `AsyncFunctionDef` and public class methods (incl. dunders). Skips `self` / `cls`. Counts `arg.annotation` + `node.returns`. macOS `._*` metadata files filtered.
**mypy:** not installed; skipped (not auto-installing per task spec).

## Headline

| Surface | Files | Funcs | Fully Typed | Partial | Untyped |
|---|---:|---:|---:|---:|---:|
| `scripts/gates/` | 33 | 343 | **100.0 %** | 0.0 % | 0.0 % |
| `scripts/rag/` | 10 | 39 | **94.9 %** | 2.6 % | 2.6 % |
| `scripts/diagnostics/` | 31 | 156 | **92.9 %** | 1.9 % | 5.1 % |
| **Overall** | **74** | **538** | **97.6 %** | 0.7 % | 1.7 % |

## Verdict: PASS (≥85 % fully typed)

Threshold: PASS ≥85 %, YELLOW 60–85 %, RED <60 %. All three surfaces clear PASS individually; overall 97.6 % is well above bar. `scripts/gates/` is at 100 % — every public function on the gates surface is fully annotated.

## Worst-typed modules (≥3 public funcs)

| # | Dir | % full | Funcs | Path |
|---:|---|---:|---:|---|
| 1 | diagnostics | 0.0 % | 0 / 3 | `scripts/diagnostics/lint_kb_tags.py` |
| 2 | diagnostics | 28.6 % | 2 / 7 | `scripts/diagnostics/mlgg_web.py` |
| 3 | rag | 60.0 % | 3 / 5 | `scripts/rag/evals/run_eval.py` |
| 4 | diagnostics | 80.0 % | 4 / 5 | `scripts/diagnostics/find_code_repos.py` |
| 5 | diagnostics | 83.3 % | 5 / 6 | `scripts/diagnostics/merge_10_agent_findings.py` |

Only 5 files in the entire scanned surface have public-function typed-coverage below 100 %. All remaining 69 files are at 100 %.

## Sub-100 % files in full (for the record)

- `scripts/diagnostics/validate_gate_code_alignment.py` — 50.0 % (1 / 2)
- All other untyped functions cluster in the 5 worst-offenders above.

## W11–W14 recently-shipped code

Spot-check: `lint_kb_tags.py` (W9-D2) and `run_eval.py` (lineage W3 → W9 → W11) are pre-W12 vintage. W12/W13/W14 churn touched `fairness_equity_gate.py`, `ablation_signal_drop.py`, harness fixes (W14-F3, W14-R0) — all land in files at **100 %** typed. Newly-shipped wave code is clean; the residue is older diagnostic utilities.

## Recommendation: Wave-N+ targeted typed-pass

Scope a **single tiny ticket** to fully type the 5 listed files (≈22 public funcs, an hour of work). Specifically:

1. `scripts/diagnostics/lint_kb_tags.py` (3 funcs, 0 % typed) — highest leverage; this is a public diagnostics CLI shipped in W9-D2 without annotations.
2. `scripts/diagnostics/mlgg_web.py` (7 funcs, 28.6 % typed) — Flask-ish web shim, easy `-> Response` / `-> str` adds.
3. `scripts/rag/evals/run_eval.py` (5 funcs, 60 % typed) — eval entry-point, type-tightening here helps W11-F* follow-ups.
4. `find_code_repos.py`, `merge_10_agent_findings.py`, `validate_gate_code_alignment.py` — 1–2 missing annotations each, trivially cleanable in the same PR.

No structural refactor needed. Recommend **Wave-N+1 "C-tier"** ticket (style/lint), not a P0. Suggest pairing with a CI guard (`mypy --ignore-missing-imports` over `scripts/gates/` only, since that surface is already at 100 % and would catch regressions cheaply).

## Artifacts

- Walker: `/tmp/W15_A4_walker.py`
- Raw JSON: `/tmp/W15_A4_results.json`

— W15-A4 (read-only audit)
