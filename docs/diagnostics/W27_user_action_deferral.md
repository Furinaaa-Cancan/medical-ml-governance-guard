# W27 — USER ACTION 1 & 2 Deferral Note

**Date**: 2026-05-17
**Status**: Both deferred to a post-W27-RAG-wave cycle; tests already xfail-marked so CI stays green.

## What's deferred

| ID | Location | Action requested | Why deferred |
|---|---|---|---|
| **USER ACTION 1** | `tests/test_rag_eval_set.py:157` | Re-label `relevant_concern_ids` in eval-set YAML to include semantically-equivalent post-2026-04-18 KB additions; flip `xfail` back to hard assert. | This is **label-side work**. The W27 wave explicitly transitions from "improve answer keys" to "improve the system" (real RAG changes — W27-R1 dedup, W27-R2 score floor, both opt-in). Re-labelling before re-measuring with the new RAG knobs would conflate "labels caught up" with "system improved." |
| **USER ACTION 2** | `tests/test_retrieval_eval_harness.py:138` | Regenerate `references/retrieval_eval/post_w13_baseline_hybrid.json` with current `WEIGHT_DENSE=0.1` ranker; restore strict comparison. | Same reason. The baseline JSON is also a label artifact — regenerating it now would lock in the **pre-W27-RAG** ranker output as the new floor. Better to defer until W27-R1 + W27-R2 have been swept on the W25 corpus so the regenerated baseline reflects the actual W27 ranker. |

## When to revisit

After **at least one of**:

1. A W27-R1 (`dedup_by_code`) + W27-R2 (`min_score`) sweep on the W25 corpus picks defensible defaults (likely `min_score ∈ [0.1, 0.3]`, `dedup_by_code=True` for production callers).
2. The W27 external N=1 (`docs/diagnostics/W27_external_n1_plan.md`, blocked on user supplying Quanjel critique) produces a non-circular signal.
3. The user explicitly asks to resume label work.

## Why this isn't just procrastination

The W14-X1 / W15-W19 retros (`docs/PROCESS_DEBT.md`) flagged "label drift" — relabelling eval sets to match drifted RAG output is the most common form of MLGG self-grading. Two of the W15-W19 strict-review fires explicitly called out this anti-pattern. Resuming USER ACTION 1/2 before W27 produces real RAG output would re-instantiate the same pattern.

## Current xfail status (CI-visible)

```
tests/test_rag_eval_set.py::test_rag_eval_set_mrr_and_recall                XFAIL  (USER ACTION 1 pending)
tests/test_retrieval_eval_harness.py::test_strict_against_baseline_hybrid   XFAIL  (USER ACTION 2 pending)
```

Both stay xfail until W27 produces the artifacts above. No code change needed for this deferral — the xfail messages already cite USER ACTION 1/2 and explain the rationale.

## Cross-refs

- `docs/diagnostics/W27_external_n1_plan.md` — W27 external N=1 design.
- `scripts/rag/evals/ncpr_paper_runner.py` — W26-R1 + W27-R1 knobs (commits `8aa9320`, `5c68530`).
- `scripts/rag/query.py` — W27-R2 `min_score` knob (commit `5c68530`).
- `docs/PROCESS_DEBT.md` — label-drift anti-pattern.
