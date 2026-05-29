# MLGG RAG Eval — Metric Contract

**Status**: Draft, established 2026-05-17 (audit W14-G follow-up).
**Owner**: RAG eval maintainer (currently unassigned — assign before any external claim).

## Why this file exists

The MLGG peer-review RAG is evaluated against two co-existing metrics that
**disagree on the optimal fusion weight**:

| Metric | Source | Best at | Production at α=0.45 |
|---|---|---|---|
| `mean_tag_precision` (proxy) | `baseline*.json` aggregate (uses `scenarios.json` `expected_tags`) | α ≈ 0.40–0.50 (BM25-leaning) | **0.438** |
| `mean_labeled_P@5` (LLM-self-eval, **OFFLINE rag_query path**) | `labeled_precision_at_5.json` (36 W8-W2/W9-A2 queries, Opus 4.7 labels) | α ≈ 0.10–0.30 (dense-leaning) | **0.494** |

> **PATH WARNING (added 2026-05-29):** Both numbers above were measured on the
> **OFFLINE `rag_query` hybrid path** (dense + BM25 + tag + severity + MMR,
> *with* a hand-authored `query_text` per case) — the path
> `scripts/review/llm_paper_audit.py` / `peer_review_lookup.py` use. They are
> **NOT** the production **gate path**. A gate failure routes through
> `scripts/core/_gate_framework.py` `build_report_envelope` →
> `scripts.rag.retrieval.bm25.retrieve_for_failure` with **only** gate_name +
> issue codes, `limit=5`, and **no `query_text`** (BM25-only, no dense, no MMR).
> The gate-path P@5 is measured by **Track A**
> (`scripts/rag/evals/gate_path_eval.py`) and is materially lower — see §5.

(See `post_wave7_baseline_hybrid.json` for current production numbers, and
`/tmp/audit_agent_G_hybrid_grid.md` for the W14 grid-search receipts.)

Without a written contract, anyone tuning the ranker can show a "+17pt
improvement" by switching metrics without changing the ranker. This file
nails the contract so deltas are honest.

## The contract

### 1. Primary metric: **`mean_tag_precision`**

For regression detection in CI and in `--strict` checks, the primary metric
is `mean_tag_precision` from the harness in `scripts/rag/evals/run_eval.py`,
aggregated over `references/retrieval_eval/scenarios.json`.

**Reasons**:
- `expected_tags` are author-curated against the reviewed paper's concern
  text, so the metric is independent of any single labeler's bias.
- The scenarios.json set is the longitudinal anchor (versioned, diffed
  through W7–W14).
- Cheap to compute, deterministic, no LLM cost.

### 2. Secondary metric: **`mean_labeled_P@5`**

For periodic quality audits (≥ Wave-level, not per-commit), `mean_labeled_P@5`
from `labeled_precision_at_5.json` is the secondary metric. **It measures the
OFFLINE `rag_query` hybrid path, NOT the gate path** (see Path Warning above).

**Constraints on use**:
- This file's labels are LLM self-eval (see `labeling_protocol.circularity_warning`
  in the JSON itself, after audit W14-E). **Absolute values are NOT suitable
  for manuscript / external / publication-grade claims** without independent
  human re-labeling.
- Acceptable internal uses: regression detection across retrieval-pipeline
  changes (deltas are informative even if absolute level is biased); error
  analysis of obvious miss patterns; sanity-check that proxy-tag improvements
  don't tank labeled-P@5.

### 3. Conflict-resolution rule

When the two metrics disagree on a tuning decision:

1. If `mean_tag_precision` regresses by **> 0.02 absolute**, the change is
   **rejected**, regardless of `mean_labeled_P@5` movement.
2. If `mean_tag_precision` is within ±0.02 and `mean_labeled_P@5` improves
   by **> 0.05 absolute**, the change is **accepted with a recorded note**.
3. Otherwise, **default to the production setting** (currently α=0.45 per
   `scripts/rag/config.py:WEIGHT_BM25`).

The 0.02 / 0.05 thresholds come from the typical run-to-run noise observed
in W11–W13 ablations. Revisit them when a benchmark of >100 hand-adjudicated
queries replaces the LLM-labeled set.

### 4. Forbidden tuning paths

- **No tuning to maximize `mean_labeled_P@5` alone** until M1 is resolved
  (independent human adjudication on ≥30% stratified sample of L01–L36).
  Reason: the labeler is the same model family as the retrieval pipeline;
  optimizing for self-eval is circular.
- **No head-to-head retriever comparison framed as "ground truth"** using
  this file's labels.
- **No claim of "human-validated" / "gold-standard"** anywhere in code
  comments, docstrings, README, or external comms.

### 5. Gate-path metric (Track A): **`mean_gate_path_p_at_5`**

The §2 `mean_labeled_P@5` measures the OFFLINE `rag_query` path. The metric a
gate-failure report (`peer_review_context`) actually delivers is measured by
**Track A**: `scripts/rag/evals/gate_path_eval.py`. Track A drives the shipping
retriever (`retrieve_for_failure`, gate_name + codes, no `query_text`, with the
`_gate_framework` stage-2 severity_fallback retry) over the SAME 36 labeled
cases (L01–L36) with the SAME relevance labels, and emits
`references/retrieval_eval/gate_path_precision_at_5_v1.json`.

Measured 2026-05-29 over L01–L36:

| Path | Metric | Value |
|---|---|---|
| OFFLINE `rag_query` hybrid (with query_text) | recorded `mean_labeled_P@5` | **0.639** |
| Production **gate** path (`retrieve_for_failure`, no query_text) | `mean_gate_path_p_at_5` | **0.244** |
| | mean delta (gate − offline) | **−0.394** |

The gate path replicates the production skip guard (`_gate_framework.py:272`
`if failures or warnings:`): 13/36 cases carry NO codes, so the shipping gate
returns an empty `peer_review_context` for them (`skipped_no_issues`) and they
score P@5 = 0 — exactly as in production. With the guard, **0/36** cases land in
`severity_fallback` (an earlier draft of this eval omitted the guard and forced
those 13 no-code cases through a severity-sorted top-5, inflating the headline
to 0.272 / delta −0.367; corrected here to 0.244 / −0.394). Off-scope probes
L19/L20 correctly stay at P@5 = 0 (any non-zero is a false-positive regression).
The same circularity caveat (§4) applies: the **absolute** gate-path P@5 is an
optimistic LLM-self-eval estimate; Track A's honest contribution is the
gate-vs-offline **delta** on a fixed label set, not a publication-grade number.
(NB: the prior 0.494 cell was the α=0.45 production-grid value; the 0.639 here
is the as-labeled `labeled_precision_at_5.json` mean over L01–L36.)

## Open questions (decide before W15)

1. **Who owns this contract?** Currently unassigned. Without an owner the
   contract has no enforcement teeth.
2. **What invalidates this contract?**
   - New labeled set (`labeled_precision_at_5_v2.json` per the existing
     append-not-replace protocol)
   - Metric definition change (e.g. swap to nDCG@5)
   - Production weight retune (would need new break-even thresholds)
3. **Should `mean_top1_score` be a third metric?** It's already in
   `post_wave7_baseline_hybrid.json` (current value 0.649) and behaves
   like a confidence proxy; not yet wired into the conflict rules above.

## Provenance

Established as the M3' resolution path in the W14 RAG audit
(2026-05-17). The original M3 finding ("hybrid mean_tag_precision dropped
22% vs BM25-only") was based on the pre-W13 `baseline_hybrid.json` snapshot
(0.338) and is RETRACTED — current production hybrid is at 0.438–0.538
depending on which baseline JSON is queried. The remaining substantive
issue (audit W14-G) is exactly this metric disagreement, which this file
resolves by writing down the rule rather than re-tuning weights again.
