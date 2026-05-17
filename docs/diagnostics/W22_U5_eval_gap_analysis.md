# W22-U5 — NCPR-Bench v1 eval-gap analysis

Wave: W22-U5 (NCPR Benchmark v1 wave). Author: Claude Code. Date: 2026-05-17.
Scope: read-only audit. Answers: *does NCPR-Bench v1 fill a gap that the existing 9+ eval artifacts do not?*

---

## 1. Existing eval inventory

| # | Artifact | Scope | Primary metric(s) | Speed |
|---|----------|-------|-------------------|-------|
| 1 | `scripts/rag/evals/run_eval.py` | retrieval, end-to-end RAG path | `mean_hit_at_k` (primary), `mean_tag_precision_at_k`, `mean_cp_hit_at_k`, `mean_top1_score`, `coverage_rate` | seconds–20s |
| 2 | `scripts/rag/evals/harness.py` | retrieval (bm25_only vs hybrid), with `--strict` regression mode and baseline | `coverage_rate`, `hit_at_k_rate`, `mean_tag_precision` | seconds |
| 3 | `scripts/rag/evals/ablation_signal_drop.py` | retrieval, signal decomposition (dense / bm25 / tag / severity / MMR ablations) | per-signal Δ vs bm25_only control | moderate (6 runs) |
| 4 | `references/retrieval_eval/labeled_precision_at_5.json` | retrieval, per-query P@5 on 36 frozen queries (L01–L36) | `mean_labeled_P@5` | fast at eval; expensive at label time; append-only protocol |
| 5 | `references/case-studies/rag-eval-set.yaml` | retrieval, gate→`concern_id` hand-validated mapping | `Recall@5 ≥ 0.55`, `MRR@5 ≥ 0.45` | fast |
| 6 | `references/retrieval_eval/scenarios.json` | data: 30 hand-crafted gate-failure scenarios feeding #1–#3 | n/a (fixture) | — |
| 7 | `references/retrieval_eval/baseline_hybrid.{json,md}` + `post_wave7_baseline_hybrid.{json,md}` | frozen baseline JSON snapshots for `--diff` regression checks | n/a (snapshot) | — |
| 8 | `references/retrieval_eval/MLGG-Bench-v1.0/` (305 scenarios, 12 slices, incl. 4 OOD + 5 bench slices) | retrieval bench: in-dist paraphrases + adversarial/compound/long-tail/negatives + 40 OOD | `mean_hit_at_k=0.858`, `mean_cp_hit_at_k=0.794`, `mean_tag_precision_at_k=0.448` | moderate |
| 9 | `scripts/rag/evals/regen_scenarios.py` + `check_scenarios_codes.py` (W20-C1) | meta-eval: AST scan + W7 runtime harvest to detect ghost `failure_codes` in scenarios.json | CI pass/fail | fast |
| 10 | `references/retrieval_eval/METRIC_CONTRACT.md` | governance: forbids LLM-judge tuning; codifies primary `mean_tag_precision`, secondary `labeled_P@5`, 0.02 / 0.05 conflict-resolution thresholds | n/a (policy) | — |

## 2. Ground-truth provenance & held-out status

| Eval | Ground truth source | Held-out from KB? | Severity-weighted? | Category coverage measured? |
|------|---------------------|-------------------|--------------------|----------------------------|
| scenarios.json (#1, #2, #3, #7) | author-curated `expected_tags` / `expected_categories` / `expected_canonical_pattern_ids` | NO (same KB) | NO | only via `expected_categories` per scenario |
| labeled_precision_at_5 (#4) | **LLM self-eval (Opus 4.7)** — `circularity_warning` documented; NOT publication-grade | NO (queries hit same KB) | NO | NO |
| rag-eval-set.yaml (#5) | hand-curated `relevant_concern_ids` per (gate, issue_codes) | NO | NO | NO |
| MLGG-Bench v1.0 in-dist slices (265/305) | KB-derived paraphrases — `expected_tags`+`expected_canonical_pattern_ids` | NO (same KB) | NO | slice-level only |
| MLGG-Bench v1.0 OOD slices (40/305: retraction_watch / openreview / TRIPOD / open_peer) | external sources — real critiques and reviewer reports | **PARTIAL** (papers external to KB, but eval still measures *retrieval into the same KB*) | NO | slice-level only |
| **NCPR-Bench v1 (proposed)** | **real reviewer concerns from `peer-review-kb.json` on 30 held-out papers (paper_doi excluded from KB build via `--exclude-papers`)** | **YES** (T4 prereq) | **YES** (CRITICAL > HIGH > MEDIUM > LOW; severity-weighted F1) | **YES** (5-category macro: leakage / design / eval / reporting / external_val) |

## 3. NCPR-specific value-add

1. **End-to-end pipeline measurement** — lint (R001–R030) + 33 gates + RAG + LLM synthesis, scored as one system. Every existing eval terminates at RAG top-K. W17-C5 spot-check already found 3/10 papers where retrieval was perfect but the final MLGG report still missed a reviewer-grade concern (i.e., the gap lives downstream of retrieval); existing evals are structurally unable to see this.
2. **Real reviewer concerns as ground truth** — peer-review-kb rows tied to paper_doi, not MLGG's own author-curated proxy tags. Removes the target-leakage critique that existing evals reward systems whose tagging conventions match the scenario authors'.
3. **True held-out papers** — KB rebuild excludes holdout DOIs (T4 `--exclude-papers`). The closest existing analogue (MLGG-Bench OOD slices, 40 scenarios) holds out the *papers* but still measures retrieval against the same KB; NCPR additionally holds out from the KB itself.
4. **Severity-weighted scoring** — CRITICAL miss costs more than a LOW miss. All existing P@5 / hit@K / Recall@5 metrics are unweighted; an existing eval cannot distinguish "missed an S01 split violation" from "missed a minor reporting nit".
5. **Category coverage across the 5-cat S/P/F/M/E ladder** — measures whether the system misses *whole dimensions* on novel papers. Existing evals measure tag overlap inside top-K, not category recall across a paper.
6. **Defensible version comparison** — closes the W18-D2 plateau (`labeled_precision_at_5` flat at 0.92 across W15–W18 while retriever tuning moved <0.01) and W14-F1 ("we have no pipeline-level eval") gaps. First number that maps to the user-visible question.
7. **Makes the "NC-grade reviewer" claim falsifiable** — currently rhetoric; with NCPR it becomes a measured recall / precision pair on Nature-family held-out papers.

## 4. What NCPR does NOT replace

NCPR is **additive**. It runs ~30–60 min wall-clock per run (ADR 0005 §4) and cannot answer retrieval-component questions. Existing evals retain distinct jobs:

- `ablation_signal_drop.py` — only tool that can localize a retrieval regression to dense vs BM25 vs tag-overlap vs severity vs MMR; NCPR runs the whole stack and cannot decompose.
- `labeled_precision_at_5.json` — longitudinal per-query P@5 anchor with W8–W18 deltas on file; cheap regression signal even with its circularity warning.
- `scenarios.json` + `run_eval.py` / `harness.py` — per-scenario retrieval regression with `--diff post_wave7_baseline_hybrid.json` is the per-commit fast gate.
- `MLGG-Bench v1.0` — 305 scenarios across 12 slices, incl. adversarial / compound / long-tail / negatives / distractors that NCPR's 30 papers cannot cover.
- `rag-eval-set.yaml` — gate→concern_id Recall@5 / MRR@5 hand-curated mapping; unique to the gate-bridge code path.
- `check_scenarios_codes.py` — scenarios.json data-integrity CI (W20-C1); unrelated concern.
- `METRIC_CONTRACT.md` — governance; the no-LLM-judge rule cited in ADR 0005 §3 Alt B is what *forces* NCPR's frozen-embedding matcher.

## 5. Recommended integration story

| Tier | When | What runs | Budget |
|------|------|-----------|--------|
| 1 — per-commit fast | every push | `run_eval.py --diff post_wave7_baseline_hybrid.json`, `harness.py --strict`, `check_scenarios_codes.py` | seconds |
| 2 — per-PR moderate | PR open / update | MLGG-Bench v1.0 dev slice (40), `ablation_signal_drop.py` on suspected retrieval regressions | ~1–2 min |
| 3 — nightly / pre-release slow | nightly cron | **NCPR-Bench v1 on 30 holdout (full pipeline)**, MLGG-Bench v1.0 full 305 incl. OOD | ~30–60 min |
| 4 — wave / release only | wave close | NCPR-Bench held-out test split, append `labeled_precision_at_5_v2.json` for longitudinal drift | hours |

This matches ADR 0005 §4 Migration: existing retrieval evals remain as component tests; NCPR is the system-level integration test.

## 6. Verdict

**PASS** — NCPR-Bench v1 genuinely fills a gap that no combination of the existing 10 artifacts covers. The four uniquely-NCPR axes (pipeline-level / held-out-from-KB / real-reviewer-concern ground truth / severity-weighted) are each unaddressed by current infrastructure, and they are exactly the axes ADR 0005 §1 named as motivating the project.

**Caveat — yellow-flag risk (ADR 0005 §6 self-challenge)**: at N=30 with non-deterministic LLM synthesis and a frozen-embedding semantic matcher, the score's confidence interval may be wide enough that two MLGG versions a reasonable person would call "clearly better" and "clearly worse" produce overlapping intervals. If the W22 baseline run (T7) shows the CI exceeds the typical inter-version delta, NCPR must be downgraded from CI gate to advisory-only until the v2 N=100 expansion lands. The pass verdict is therefore *conditional on the T7 baseline CI width landing inside the inter-version delta typical of the W15–W18 retrieval changes (~0.02–0.05 absolute on `mean_tag_precision`)*.
