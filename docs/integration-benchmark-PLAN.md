# Integration Benchmark Plan — NCPR-Bench v2 ("tri-layer")

> Status: **PLAN — awaiting approval. Nothing built yet.**
> Author: drafted 2026-06-05, grounded by a 5-agent recon (see commit trailer).
> Supersedes nothing; extends NCPR-Bench v1 (`scripts/rag/evals/run_ncpr_benchmark.py`).

## 0. The gap this closes

The product is three layers — **①** 33 deterministic gates + 30 lint rules on code → **②** RAG
retrieving real peer-review concerns → **④** an LLM advisory layer that synthesizes concerns, folded
into `publication_gate` under `final = min(gate, llm)` (wired end-to-end in PR #34).

**All 12 existing benchmarks test exactly one layer in isolation.** The only cross-layer one,
NCPR-Bench v1, defaults to `rag_only=True` (`run_ncpr_benchmark.py:504-508`) and runs on a 30-paper
holdout that ships no code — so **the gate layer never executes on real artifacts, and `final=min` has
never been measured on a real paper.** We do not know whether the deterministic layer earns its cost
or whether the LLM adds anything beyond echoing the KB.

## 1. Questions the benchmark must answer

- **Q1 (gate contribution):** Do the 33 gates + 30 lint rules surface real reviewer concerns that RAG
  retrieval alone misses? `recall(full) − recall(rag_only)`.
- **Q2 (LLM novelty):** Does the LLM synthesis add value, or does it copy retrieved KB entries verbatim?
- **Q3 (asymmetry on real data):** Does `final = min(gate, llm)` behave correctly on real papers — never
  upgrades a verdict, blocking concern caps the tier?
- **Q4 (overlap/redundancy):** How much do gate-surfaced and RAG-surfaced concerns overlap (are we
  paying for two paths that find the same things)?

## 2. Feasibility — the data gate (VERIFIED real)

| Source | Count | What it gives | Use |
|---|---|---|---|
| `paper/code-repos-corpus.json` | **21** | KB id + DOI + verified `primary_repo` + code/data sections | **Tier A** — lint on real repos |
| `paper/code-repos-cohort-binary.json` | **125** | cohort-binary papers with a detected `primary_repo` | Tier A expansion pool |
| `references/case-studies/peer-review-kb.json` | 335 (170 NCPR-eligible) | `reviewer_concerns` per paper | ground truth (all tiers) |
| `experiments/authority-e2e/` UCI datasets | 7 | runnable training pipelines (Heart, BreastCancer, CKD, Sepsis, RHC, NHANES, SUPPORT2) | **Tier C** — gate-execution truth |

Only ~12% of eligible papers ship runnable code, and (critically) **even those don't emit MLGG
evidence artifacts** — see §5. So the benchmark is **tiered** rather than "run all 33 gates on every
paper":

- **Tier A — real papers, real code (21, expandable to 125):** `mlgg lint` on the actual repo +
  RAG + LLM on the methods text. Real-world coverage of layers ①(lint)②④.
- **Tier B — real papers, methods-text only (rest of holdout):** RAG + LLM only (NCPR v1's existing
  mode). Broad coverage of ②④.
- **Tier C — proxy datasets with seeded defects (authority-e2e):** full 33-gate execution against
  datasets where we *inject* known leakage/calibration/imbalance faults → **controlled ground truth for
  the gate layer ①** that real papers can't give us.

This split is the honest core of the design: **real papers give us text/lint coverage; proxy datasets
give us gate-execution truth.** Conflating the two is exactly the trap NCPR v1 avoided.

## 3. Reuse, don't rebuild

| Need | Reuse |
|---|---|
| Flag ↔ concern matching | `ncpr_matcher.match_all` / `match_flag_to_concern` (cosine ≥ 0.70 + exact-code) |
| Severity-weighted F1 / recall | `ncpr_severity_score.{weighted_tp_fn_fp, per_paper_score, macro_average}` |
| 5-category coverage | `ncpr_category_coverage.{category_coverage, aggregate_coverage}` |
| Aggregation + report | `ncpr_aggregator.{aggregate, write_results_json, write_report_md}` |
| Orchestration | extend `run_ncpr_benchmark.py` (add `rag_only=False` + ablation modes); don't fork |
| Pipeline | the PR #34 stack: `mlgg lint`, `run_dag_pipeline`, `llm_review --rag`, `publication_gate` |
| Paper selection | `references/benchmark/ncpr_v1_holdout_criteria.md` (pre-registered) |
| RAG exclusion (dense) | `index/builder.py` `excluded_paper_ids` (already exists; not yet threaded — see §6) |

## 4. Net-new components

1. **Tri-layer paper runner** — per paper: run the available layers, capture each layer's flags tagged
   by origin (`lint` / `gate` / `rag` / `llm`), then score the union vs ground truth.
2. **Ablation harness** — three configs per paper: **L1** gates/lint-only, **L2** RAG-only, **L3** full.
3. **Circularity controls** (§6) — the prerequisite correctness work.
4. **Contribution metrics** — recall delta, gate∩RAG Jaccard, novelty rate (§7).

## 5. The integration friction (stated honestly)

`mlgg strict` (the 33 gates) consumes `evidence/*.json` produced by an **instrumented training run**, not
a code repo. A cloned paper repo does not emit those artifacts, and reproducing each paper's training is
infeasible at scale (different data access, environments, runtime). **This is why v1 went `rag_only`.**

Consequence for v2:
- Real-paper **gate** coverage is *not* achievable end-to-end. We get real-paper coverage of **lint**
  (static, runs on code as-is) + **RAG/LLM** (runs on methods text).
- The **gate layer** is validated on **Tier C proxy datasets** where we control the training run and
  seed known defects → unambiguous ground truth for whether gates fire correctly.
- Q1/Q4 (gate contribution / overlap) are answered as: lint-vs-RAG contribution on Tier A, and
  gate-vs-(known-defect) precision/recall on Tier C — reported separately, not blended.

## 6. Validity controls — circularity (MUST, prerequisite)

**The KB is both the RAG index and the ground-truth answer key.** When evaluating paper P, RAG can
retrieve P's own concerns and the LLM can echo them → inflated recall. Current state: `excluded_paper_ids`
exists at dense index-build (`builder.py:221-225`) but is **not** threaded through `rag_query` →
`hybrid_rank` → BM25, and `hybrid_rank` has **no `paper_id` self-match filter** (only a soft MMR diversity
penalty, `hybrid.py:477-490`).

| Control | What | Where |
|---|---|---|
| **C1 LOPO** | leave-one-paper-out: exclude P's concerns from retrieval when scoring P | thread `excluded_paper_ids` through `rag_query` (`query.py:55`) → `hybrid_rank` → BM25 `retrieve_for_failure` |
| **C2 hard self-filter** | drop any candidate with `paper_id == P` before scoring | `hybrid_rank` union step (`hybrid.py:645-656`) |
| **C3 novelty check** | flag each LLM concern as `copy_from_rag` (verbatim) vs `synthesized` | `llm_review.run_llm_review` post-synthesis |
| **C4 ablation** | L1/L2/L3 runs isolate each layer's true contribution | benchmark orchestration |
| **C5 GT isolation** | ground truth in a separate read-only file, loaded *after* flag generation, hashed per record | benchmark orchestration |

**C1/C2 are a real product correctness fix, not just a benchmark need** — today a live `mlgg llm-review
--rag` on a KB paper can leak that paper's own reviewer concerns back into its review. Recommend building
C1/C2 first as a standalone PR (with tests), independent of the rest of the benchmark.

Other threats: deterministic adapter by default (avoid LLM non-determinism + paid calls; live arm
optional, reported mean±std); freeze KB version + commit hash in benchmark metadata; stratify Tier A by
domain/journal to check the open-source-author selection bias.

## 7. Metrics

- **Per-layer severity-weighted F1 / recall@K** (reuse `ncpr_severity_score`) for L1/L2/L3.
- **Gate/lint contribution** = `recall(L3) − recall(L2)` (Tier A: lint; Tier C: gates vs seeded defects).
- **Overlap** = Jaccard of matched concern-ids between the lint/gate set and the RAG set.
- **Novelty rate** = fraction of LLM concerns not verbatim-copied from a retrieved KB entry (C3).
- **`final=min` distribution** = pass / concern / fail outcomes across real papers, with a check that no
  paper's tier was ever raised by LLM/RAG input.
- **Category coverage** across the 5 buckets (`ncpr_category_coverage`).

## 8. Phasing & rough effort

| Phase | Scope | Effort |
|---|---|---|
| **P0** | Circularity controls C1+C2 (thread `excluded_paper_ids`, self-match filter) + tests. Standalone PR. | ~1–2 days |
| **P1** | Tri-layer runner + ablation on Tier A (21 papers, lint+RAG+LLM) + Tier C proxies (full gates, seeded defects) → first integration numbers. | ~3–5 days |
| **P2** | Tier B methods-text over the holdout; aggregate + Markdown report; C3/C5 controls. | ~2–3 days |
| **P3** *(optional)* | scale Tier A to the 125-pool; novelty deep-dive; live-LLM arm. | open |

Not the 40–80h of pure code an earlier estimate suggested: the repo corpus + methods extraction already
exist in `paper/`; the scoring/aggregation stack already exists. The genuine cost is P0 (correctness) +
the Tier-C seeded-defect fixtures.

## 9. Decisions needed before building

- **D1 — Tier A scope:** lint+RAG+LLM on real repos + Tier C proxies for gate truth (recommended), vs.
  attempt full gate runs on real repos (expensive, mostly infeasible per §5).
- **D2 — Build C1/C2 (RAG self-exclusion) first as a standalone correctness PR?** (recommended yes — it's
  a real leak today, benchmark or not).
- **D3 — Adapter:** deterministic-only for v2 (recommended), or include a paid live-LLM arm.
- **D4 — Location:** where benchmark code + frozen ground truth live (`scripts/rag/evals/` + `paper/` vs a
  new `benchmarks/` tree).
