# MLGG-Bench v1.0–v1.0.2 — Final Self-Review

Date: 2026-05-17
Reviewer: Claude (in Nature Methods / JAMA reviewer mode per project CLAUDE.md)
Scope: v1.0 → v1.0.2 (305 scenarios across 12 slices, plus v1.1_proposed/)
Verdict: **acceptable as supplementary material; NOT publication-ready as a main-figure benchmark**.

---

## Headline numbers with bootstrap 95% CI (added in commit alongside this review)

`scripts/rag/evals/run_eval.py` now reports percentile-bootstrap CI on every mean metric. v1.0.2 numbers:

| Metric | Point | **95% CI** (n=305 bootstrap) |
|---|---|---|
| `mean_hit_at_k` | 0.858 | **[0.819, 0.897]** |
| `mean_cp_hit_at_k` (n_cp_eval=250) | 0.856 | **[0.812, 0.900]** |
| `mean_tag_precision_at_k` | 0.448 | **[0.410, 0.488]** |

Per-slice CIs (bootstrap B=1000, seed=20260517):

| Slice | n | hit@5 [95% CI] | cp_hit@5 [95% CI] |
|---|---|---|---|
| baseline_30 | 26 | 1.000 [1.00, 1.00] | — (no CP gold) |
| indist_155 | 155 | 0.935 [0.89, 0.97] | 0.955 [0.92, 0.98] |
| ood_01 Retraction Watch | 10 | 0.800 [0.50, 1.00] | 0.778 [0.44, 1.00] |
| ood_02 OpenReview | 10 | 0.600 [0.30, 0.90] | 0.800 [0.50, 1.00] |
| **ood_03 TRIPOD+AI** | 10 | **0.300 [0.10, 0.60]** | **0.556 [0.22, 0.89]** |
| ood_04 F1000/eLife | 10 | 0.900 [0.70, 1.00] | 0.800 [0.50, 1.00] |
| bench_01 fairness | 10 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] (n_cp=7) |
| bench_02 long-tail | 25 | 0.840 [0.68, 0.96] | 0.720 [0.56, 0.88] |
| **bench_03 compound** | 10 | **0.200 [0.0, 0.50]** | **0.500 [0.20, 0.80]** |
| bench_07 adv extended | 15 | 0.733 [0.53, 0.93] | 0.533 [0.27, 0.80] |

**Reviewer takeaway**: with per-slice n=10, no two slices' point estimates are statistically distinguishable from each other at α=0.05 *except* the extremes (ood_03 vs ood_04 / bench_01). Reporting per-slice point estimates without CIs in subsequent docs is misleading. **The pre-CI-addition versions of v1.0/v1.0.1/v1.0.2 README all reported point estimates only — this review now corrects that.**

---

## Major Concerns

### M1. Entire benchmark is LLM-generated; no human-authored gold

305 scenarios from 25 autonomous agent dispatches. OOD slices used LLM paraphrase of WebFetched external material. No truly external, human-author-blinded gold standard exists. Every hit/cp_hit value is "LLM vs LLM-trained on similar corpus".

**Cannot be fixed by any v1.0.x PATCH** — requires prospective evaluation on real reviewer-in-the-loop data.

### M2. Per-slice n=10 yields ±25–31pp 95% CIs (confirmed above)

ood_03 hit@5 = 0.30 95% CI [0.10, 0.60] is barely distinguishable from random (0.20 for chance retrieval into top-5 of 49 CPs). The benchmark as currently sized cannot resolve practically-relevant differences in retrieval quality at slice level.

**Mitigations applied**: (a) bootstrap CI in harness as of this review's commit; (b) pool-then-report convention documented in `split_spec.md`.

**Mitigations NOT applied**: scaling up per-slice n. The 10-sample slices were time-budget choices, not principled.

### M3. CI red on all 7 of my commits (verified by gh api)

| Commit | `unit (3.12)` |
|---|---|
| f607116 (v1.0) | failure |
| b2c6b62 (v1.0.1) | failure |
| a5ce7be (spot-audit) | failure |
| 252a243 (audit fixes) | failure |
| 9bcec05 (cp-mint exp) | failure |
| 14df46f (v1.0.2) | failure |
| a035843 (cross-ref) | failure |
| (parallel session commits also fail same job) | failure |

Cause: parallel-session race on README test-count drift (`tests/test_check_readme_stats.py::TestDriftLint`). Not introduced by this benchmark work, but the consequence is a main branch that has been visibly red for the entire v1.0–v1.0.2 development window. **Any external reviewer pulling the repo will see a red main as their first impression.**

**Fix candidate (not applied — needs explicit user approval to touch `.githooks/`)**: a 20-line pre-commit hook that auto-bumps the README test count to match `tests/` tree.

### M4. CP-Relabel disagreement rates are alarmingly high

| Pass | Disagreement with prior | Scope |
|---|---|---|
| v2 (seeded by IRR audit) | — | 25/155 (16%) |
| v3 fullpass (override anchor) | vs v2: **38%** | 59/155 indist |
| v4 OOD | vs v1.0 OOD originals: **80%** | 32/40 OOD |

cp_hit@5 = 0.856 is measured against v3+v4 labels, which themselves represent ~50–80% disagreement with the prior labels. A future v5 (currently absent) could disagree similarly. **The metric depends on labels that are not converging — interpret with caution.**

### M5. Two known failure modes shipped unfixed in v1.0.2

| Failure | v1.0 | v1.0.2 | v1.1 attempt | Status |
|---|---|---|---|---|
| bench_03 compound | hit=0.20 [0,0.50] | unchanged | decompose-and-merge prototype | **NEGATIVE result** |
| ood_03 meta-methodology | cp_hit=0.20 | 0.56 (CP-relabel helped, but META entries not merged) | TRIPOD draft + new CPs | **pending clinical review** |
| bench_07 adv extended | hit=0.73 | unchanged | not attempted | open |

cp_hit@5 = 0.856 headline masks bench_03 = 0.50 [0.20, 0.80]. Per-slice reporting should be mandatory for any external claim.

### M6. v1.1 "+0.20 ood_03 hit" was measured via monkey-patched KB

The +0.20 lift on ood_03 hit@5 (in `v1.1_proposed/draft_meta_entries.md` and `cp_mint_experiment.md`) used a temporary augmented KB built in-memory. Production deployment requires merging 30 META entries into `references/case-studies/peer-review-kb.json` — which requires clinical-methodologist sign-off per the project's `disease-KB` provenance policy. **Until that merge happens, the +0.20 lift is a forecast, not a realised improvement.**

---

## Minor Concerns

| # | Issue | Impact |
|---|---|---|
| m1 | OOD `no_good_fit` makes cp_hit denominators uneven across slices (ood_01: 9/10, ood_03: 9/10) | comparison hygiene |
| m2 | bench_01 fairness has 3/10 scenarios with no CP fit; gap in 49-CP taxonomy is acknowledged but unaddressed | systematic |
| m3 | 158/664 (24%) of indist_155 expected_tags are OOV (KB tag pool lacks them) — pre-existing, unfixed | downward-biases hit@5 |
| m4 | `_provenance` field added to scenarios is not consumed by harness | dead data |
| m5 | `runner.sh` reports `git_state = "dirty"` because of untracked `.cache/` | provenance integrity |
| m6 | bench_05 distractor false-positive rate = 1/10 (0.10) has CI [0, 0.29] — not statistically meaningful | reporting honesty |
| m7 | baseline_30 still has 0 CP labels — entire slice excluded from cp_hit measurement | could be back-filled |

---

## Questions a Real Reviewer Would Ask

### Q1. Why aren't slice-level CIs in the main metric table of any v1.0/v1.0.1/v1.0.2 README?

**Answer:** they should be. This review and the harness update of 2026-05-17 fix it. Prior versions reported point estimates only — a presentation-bias mistake.

### Q2. What's the CP-Relabel v5 disagreement going to look like?

**Unknown.** v3 → v4 (different scopes) was 80%; v5 (full re-audit including bench slices) would be the test. Recommendation: do a sample-of-30 v5 spot-check before claiming v1.0.2 labels are stable.

### Q3. Are CP-053 (dataset-provenance) and CP-054 (reader-study asymmetry) real CP gaps, or LLM over-imagination?

**Cannot tell from current evidence.** They each came from 1 honest `no_good_fit` case (n=2 total). Two scenarios may not justify a CP-mint; could be argued for either side. Methodology expert needed.

### Q4. Is baseline_30 hit@5 = 1.000 a "real" number?

**No, it's in-sample.** The RAG's hybrid weights (W13-P0 commit message in `scripts/rag/config.py`) were tuned on this set. baseline_30 = 1.000 reflects training-set overfit, not generalization. Should be reported as "regression set" not "performance set" in any external claim.

### Q5. What's the prospective evaluation plan?

**None currently exists.** All 305 scenarios are retrospective constructions. Plan should be: take 3–5 real NC manuscripts in active review, have RAG retrieve top-5 concerns per reviewer query, have actual reviewers grade usefulness. Until that exists, the benchmark cannot answer "does RAG help peer reviewers?".

---

## Bootstrap CI in the harness — what it enables and what it doesn't

The new `_bootstrap_ci()` function in `run_eval.py` (B=1000, percentile method, seed=20260517) provides reproducible CIs on every mean metric. What it does:

- Quantifies sampling uncertainty on the 305-scenario eval set
- Enables honest reporting at slice level (where the wide CIs are the news)
- Reproducible across runs

What it does NOT do:

- **Does not bootstrap labels.** The CIs assume the gold labels are fixed. Given M4 (38–80% relabel rates), the *real* uncertainty is much higher than the scenario-resampling CIs show.
- **Does not address sampling bias** — the benchmark was constructed by selection, not random sampling, so the CIs underestimate true variance.
- **Does not validate the metric definition** — hit@K and cp_hit@K are by construction; their psychometric properties weren't tested.

Per-scenario bootstrap = floor estimate of uncertainty. For NC-grade claims, add label-level bootstrap (resample which-CP-is-gold from a panel of expert labels) on top.

---

## Final Verdict

**MLGG-Bench v1.0.2 is publishable as a methodological supplement** with the following narrative:
> "We constructed a 305-scenario LLM-generated benchmark for peer-review concern retrieval, stratified across 12 design slices. The RAG achieves hit@5 = 0.858 [0.819, 0.897] and cp_hit@5 = 0.856 [0.812, 0.900] on the in-domain composite, with documented per-slice weaknesses on TRIPOD+AI meta-methodology critiques (hit@5 = 0.30 [0.10, 0.60]) and compound multi-CP queries (hit@5 = 0.20 [0, 0.50]). We did not perform prospective evaluation; all numbers are retrospective on LLM-generated material."

It is **NOT publishable as a main-figure RAG quality claim** without:
1. Prospective evaluation on real-in-the-loop reviewers (M1)
2. CI-cleanup on main (M3)
3. Either CP-Relabel v5 convergence or label-level bootstrap CI (M4)
4. Larger per-slice n where it matters most (ood_03, bench_03) (M2)

---

## Acknowledgments

This review is a self-review. An independent reviewer would catch concerns this self-review missed — that limitation is itself an entry on the "concerns" list.
