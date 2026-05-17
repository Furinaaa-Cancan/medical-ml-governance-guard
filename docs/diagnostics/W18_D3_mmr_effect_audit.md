# W18-D3 — MMR Post-W13-P0 Promote/Demote Audit

**Date:** 2026-05-17
**Scope:** Confirm `_mmr_rerank` still re-ranks meaningfully after W13-P0 weight rebalance and that paper-diversity in top-5 remains non-trivial.
**Mode:** READ-ONLY in-process invocation of `scripts.rag.retrieval.hybrid.hybrid_rank`. Pre-MMR ranking captured by spying `_mmr_rerank` (records its input). 10 gate-anchored scenarios from `references/retrieval_eval/scenarios.json`.

Raw artefacts: `/tmp/W18_D3_per_query.json`, `/tmp/W18_D3_agg.json`, `/tmp/W18_D3_run.py`.

## Configuration

| Knob | Value | Source |
|---|---|---|
| `MMR_LAMBDA` | 0.7 | `scripts/rag/config.py:140` |
| `MMR_SAME_PAPER_PENALTY` | 0.5 | `scripts/rag/config.py:141` |
| `MMR_COSINE_FLOOR` | 0.88 | `scripts/rag/config.py:149` (W7-P0) |

## Headline numbers (n=10 gate-anchored)

- Mean paper-diversity in top-5: **4.9 / 5** (min 4, max 5).
- Diversity histogram: `{5: 9, 4: 1}` — 9 of 10 queries return 5 distinct papers.
- MMR no-op frequency: **9 / 10 (90%)**. Only `tuning_hyperparameter_on_test_set` saw the top-5 change.
- `blocker_reason` histogram across all 50 picks: `{"none": 50, "cosine": 0, "same_paper": 0}` — **MMR never recorded a diversity penalty in the gate-anchored suite.**

## The one active query

`tuning_hyperparameter_on_test_set` swap:
- Pre-MMR rank 5: `PR-EXP-0084-C04` (paper = `PR-EXP-0084`, same paper as rank 3 `PR-EXP-0084-C08`).
- Post-MMR rank 5: `PR-EXP-0200-C05` (was rank 6 pre-MMR; new paper).

The swap matches the same-paper diversity intent **but** the recorded breakdown for `PR-EXP-0200-C05` is `reason="none", max_sim=0`. So the swap came from MMR's deterministic re-traversal under near-tied `_final_score`, not from the penalty actually biting. See "Hidden bug" below.

## Most-promoted / most-demoted (top-5 sample only)

| Direction | Concern | Movement |
|---|---|---|
| Promoted | `PR-EXP-0200-C05` | rank 6 → rank 5 in 1 query (`tuning_hyperparameter_on_test_set`) |
| Demoted | `PR-EXP-0084-C04` | rank 5 → out of top-5 in same query |

No concern was systematically promoted or demoted across multiple queries.

## Spot-check: free-text mode (5 ad-hoc queries, not the formal suite)

Free-text MMR is slightly more active (2/5 noop=False; 1 `cosine` blocker fired in 25 picks). Paper diversity still 5/5 in every probe.

## Hidden bug (orthogonal but exposed by this audit)

Under the gate-anchored path, BM25-only records are stored with `_paper_id` (underscore prefix) at `scripts/rag/retrieval/bm25.py:336`, but `_mmr_rerank` reads `paper_id` (no underscore) at `scripts/rag/retrieval/hybrid.py:465`. When the BM25 path replaces or supplements a candidate, `paper_id` is missing → same-paper penalty never fires for BM25-only candidates. Even dense-side records can have `paper_id=None` after the union/gate filter in the gate-anchored path (empirically verified: all 5 top-5 records under `leakage_gate` had `paper_id is None`). This explains why `blocker_reason="same_paper"` is 0/50 in the gate-anchored suite. **Not in scope to fix here**; flagging for W18-D5 or a Wave-19 ticket.

## Verdict

**YELLOW** — MMR is effective at preserving the already-diverse pre-MMR list (9/10 queries are no-op because they need nothing), and paper diversity is high (4.9/5). But the diversity comes from the pre-MMR fusion ranking, **not** from MMR itself: the cosine penalty (floor 0.88) tripped 0/50 times in the gate-anchored suite, and the same-paper penalty is invisible because the `paper_id` field is dropped along the gate-anchored union path (see bug above).

## Wave-N+ recommendation

- **Keep MMR for now** — strip cost is negligible and the rare free-text `cosine` hit shows non-zero protective value.
- **Fix `paper_id` propagation** before any re-tune (the cosine_floor / same_paper_penalty knobs cannot be honestly assessed while half the signal is silently zeroed). Owner: W18-D5 or new W19 ticket.
- **Then** consider lowering `MMR_COSINE_FLOOR` from 0.88 → 0.80 in a Wave-19 A/B; current 0.88 is so lax it never bites even on adjacent siblings within the same canonical pattern.
- Do **not** drop MMR — re-evaluate after the `paper_id` fix lands.
