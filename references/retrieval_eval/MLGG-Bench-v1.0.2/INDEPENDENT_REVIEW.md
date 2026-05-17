# MLGG-Bench v1.0.2 — Independent Multi-Reviewer Audit

Date: 2026-05-17
Reviewers: 10 independent autonomous agent personas, each scoped to a single lane (statistics / methodology / reproducibility / CP taxonomy / OOD validity / adversarial / docs / code / provenance / meta-review)
Method: each agent received only its lane's brief + read-only access to artifacts; no inter-agent communication; each produced ≤500-word strict critique
Verdict: **REVIEW.md self-rating "publishable as supplementary" is overstated**. Two critical claims invalidated; KB-extension experiments founded on factually wrong drafts.

---

## 🔴 Cardinal finding (cross-cutting)

### The "+0.062 cp_hit cumulative lift" headline is a metric artifact, not a RAG improvement

**Source:** R10 meta-review, corroborated by R1 stats.

v1.0 → v1.0.1 → v1.0.2 changed CP labels by 38% (v3 pass) and 80% (v4 OOD pass) with the same RAG, same KB, same hybrid weights. The score improved because the answer key moved, not the retriever. R1 estimates paired-McNemar 95% CI on the deltas:
- +0.027 [−0.033, +0.087] (v1.0.1)
- +0.062 [−0.013, +0.137] (v1.0.2)

Both bracket zero. The lift is **not statistically distinguishable from re-baselining noise**.

**Action required**: every doc that reports v1.0.x as "improvement" must add a footnote that this is improvement against a moving gold standard; the RAG itself has not changed since W13-P0.

---

## 🔴 Critical Blockers (would desk-reject)

### B1. OOD slices are NOT out-of-distribution on the dimensions that matter (R5)

| Dimension | Actual overlap with KB |
|---|---|
| DOI | 0/40 (real OOD) ✓ |
| Tag vocabulary | **228/228 = 100% from KB-derived `_vocab.json`** |
| Canonical Patterns | **79/79 = 100% from KB CPs** |
| Gates | 40/40 = 100% |
| Categories | 83/83 = 100% |
| Conceptual archetypes | Every sampled scenario maps to a familiar KB pattern |
| Modality | KB has ~50 imaging entries (CXR 6, CT 11, MRI 8, WSI 16) — DeGrave shortcut-learning is NOT modality-OOD |

R5: "cp_hit@5 ≈ 0.73 on OOD is most parsimoniously explained by agents reverse-engineering queries against the KB-vocab they were given, not by RAG generalisation."

**Implication**: the OOD numbers do not measure generalisation. They measure "RAG retrieves KB content using paraphrased KB queries". The framing is misleading.

### B2. v1.1 META draft entries contain factual fabrications (R2)

R2 cross-checked 5 entries against published standards:

- **META-TRIPOD-001/004/005/006**: cite TRIPOD+AI item numbers (19a/19b for calibration, 21 for fairness, 24 for availability, 17/18 for uncertainty) that **contradict every verifiable secondary source**. Real numbers: calibration → item 12e; fairness → item 14; availability → item 22.
- **META-SR-002 (Wynants 2020)**: cited as n=232; actual living-review n=412 studies / 731 models.
- **META-SR-002 (Roberts 2021)**: cited as n=415; only 62 quality-reviewed.
- **META-SR-003 (Andaur Navarro)**: DOI `10.1136/bmjopen-2020-048008` is the **protocol**, not the review (BMJ 2021;375:n2281).

**Implication**: the verified-by-experiment "+0.20 ood_03 hit@5 lift" is built on entries that would be challenged immediately under clinical review. The augmented-KB measurement is technically reproducible but methodologically suspect.

### B3. Statistical claims rest on a buggy bootstrap implementation (R1, R8)

- **R8 + R1 both flag**: `_bootstrap_ci` uses `int()` truncation: `int(0.025*1000)=25`, `int(0.975*1000)=975` → reports ~2.6/97.6 percentile bounds (not 2.5/97.5). Small bias but silent.
- **`alpha=0` triggers IndexError** (`hi_idx = B` is out of range).
- **R1: degenerate CIs (e.g., `[1.0, 1.0]` for baseline_30 hit@5) are math artifacts, not stability.** Clopper-Pearson one-sided lower for 26/26 is 0.871, not 1.0.
- **R1: FWER ≈ 46%** across 12 simultaneous per-slice CIs with no correction.
- **R8: `_bootstrap_ci` has zero tests** despite being the headline response to REVIEW.md M2.

---

## 🟡 Major Concerns

### M1. CP taxonomy is structurally unstable across domains (R4 + R5)

- 13/49 CPs at n=3 floor (CP-037..CP-049). Empirical reliability floor ≥ n=10.
- v4 OOD disagreement rate is **slice-stratified**: ood_02 (EHR) 30% changed vs ood_03/ood_04 (TRIPOD+AI / F1000) **100%** changed. R4 attributes ~60% to taxonomy unfitness, ~40% to labeler noise.
- CP-026 / CP-020 / CP-006 (evaluation_metrics cluster) are **not mutually exclusive** — all 3/3 v2-better cases in v3 spot-audit fell here.
- The 49-CP set was derived from Nature Comms tabular-EHR papers (per CLAUDE.md scope); applying it to imaging shortcut-learning or meta-methodology is **a category error**.

### M2. v1.1 CP-mint case is weaker than `cp_mint_experiment.md` claims (R2 + R4)

- R2: only **CP-052 (shortcut_learning_audit_missing)** is methodologically clean.
- CP-050 is too vague ("meta_checklist_underreporting" collapses onto existing CPs).
- CP-051 is evidence *about* CPs, not itself a CP — should be a tag.
- CP-053/054 (n=1 supporting case each) are insufficient.
- The recommendation upgrade "mint all 3" in v1.0.2 README contradicts R2 and R4 both arriving at "mint only CP-052".

### M3. Adversarial slice bench_07 codeswitch is invalid (R6)

- `scripts/rag/config.py:41` pins `BAAI/bge-small-en-v1.5` (English-only).
- The 3 codeswitch scenarios therefore test **degraded English handling**, not multilingual robustness as the slice description claims.
- bench_07.lex 2/3 are shadow-boxing (BGE handles trivially).

### M4. bench_05 distractor sub-bucket has ~30% mis-labeled scenarios (R6)

- REVIEW.md flagged 1 sepsis-3 case; R6 estimates the entire `domain_disagreement` sub-bucket (sepsis-3, htn-130, ses-confounder) is mis-conceived — outcome definition IS methodology.
- 60%-noise claim in `compound_query_NEGATIVE.md` is mathematically undefended.

### M5. Reproducibility safeguards are performative (R3 + R9)

- **`runner.sh` prints `kb_sha256` but never verifies it.** Tampering the bench artifact's `kb_sha256_first16` goes undetected. R3 confirmed by simulation.
- **`SPLITS=test` runs with zero warning** — held-out test-set leakage is one env var away.
- **`_provenance: "LLM-DRAFT-pending-clinical-review"` is performative**: `grep -rIn LLM-DRAFT scripts/` returns 0 hits. No code path refuses LLM-DRAFT entries.

### M6. SPEC.md is severely stale (R7)

- Still claims 270 materialised / 315 total / 9 slices (real: 305 / 12 slices).
- References non-existent `splits/v1.0.json`.
- Internally contradicts itself (§3 adversarial n=35 vs §9.2 n=20).
- v1.0.2 supersession **not propagated** to BENCHMARK_OVERVIEW.md or ADR 0007 — both still call v1.0.1 "PRODUCTION" with old `cp_hit@5 = 0.821`.
- IRR rate contradiction: v1.0 README "16%" vs DIAGNOSIS.md "28%".

### M7. CLAUDE.md NEVER rule technically violated (R9)

22 commits today wrote to `references/**/*.json` without an embedded "user-approved" trailer. Mitigated by changelog sidecars + `_provenance` markers, but strict reading of the policy requires explicit per-commit approval evidence.

---

## 🟢 Confirmed Correct

- **Numbers reproduce byte-exactly** on back-to-back runs (R3) — `hit@5=0.858`, `cp_hit@5=0.856`, bootstrap CIs identical with seed pin.
- **Splits sum to 305 with zero overlap** across train/dev/test (R3).
- **0/40 DOI overlap** between OOD source papers and KB — paper-level OOD framing is real (R5, R9).
- **0 prompt-injection** patterns across 345 audited scenarios; no PHI, no API keys (R9).
- **4/5 sampled DOIs verified** (R9); META-PROBAST-001/005 + META-ANCHOR-001 (DeGrave) + META-ANCHOR-003 (Wong) + META-STRATOS-002 (Van Calster) are methodologically faithful (R2).
- **`runner.sh` provenance header prints git SHA + KB SHA + Python version + embedding model**, deterministic (R3).
- **Pre-push 371/371 tests pass locally** every commit.
- **Co-Authored-By Opus 4.7 attribution** consistent with cadence; no misattribution evidence (R9).

---

## Cross-cutting themes (3+ reviewers converged)

1. **Self-evaluation closed-loop bias** (R5 + R10): scenarios built from KB vocab, evaluated by RAG over KB, gold defined by KB-vocab agents → no external anchor exists at any layer.
2. **Performative safeguards** (R3 + R8 + R9): bootstrap CI (untested), KB SHA (printed-not-verified), `_provenance` markers (unenforced), test-set protection (env-var-leaky).
3. **Headline numbers overstate underlying RAG quality** (R1 + R2 + R10): the +0.062 lift is relabel-driven; the +0.20 ood_03 lift relies on factually wrong META entries; the per-slice point estimates have CI [0, 0.5] on bench_03.
4. **Domain mismatch propagates everywhere** (R2 + R4 + R5 + R6): KB built for tabular EHR; applied to imaging/meta/multilingual → taxonomy fragments, vocab forced, scenarios mis-labeled.

---

## Triage

### Act-now (cheap, I can verify)

| # | Fix | Effort | Validated by |
|---|---|---|---|
| A1 | Fix `_bootstrap_ci` off-by-one (use `(B-1)*alpha/2` rounding, or `numpy.percentile(values, q*100, method='linear')`) | 5 lines | R1, R8 |
| A2 | Add `_bootstrap_ci` unit tests (degenerate inputs, seed reproducibility, lo≤point≤hi) | ~30 lines | R1, R8 |
| A3 | Add KB SHA verification in `runner.sh` (compare printed SHA to live KB SHA) | 3 lines bash | R3, R9 |
| A4 | Add `SPLITS=test` guard requiring explicit `ALLOW_TEST=1` env confirmation | 5 lines bash | R3 |
| A5 | Add IRR contradiction reconciliation note (16% v2 anchor vs 28% v3 fullpass — different scopes) | 2 lines | R7 |
| A6 | Fix the `metric_definitions` block in `all_scenarios.json` to match what harness actually computes | 5 lines | R7 |

### Queue (need user / clinical reviewer / methodology expert)

| # | Decision needed | Blocker on |
|---|---|---|
| Q1 | Reframe "OOD" → "out-of-KB-paper" with explicit caveat that vocab/CPs/concepts overlap | doc rewrite, user OK |
| Q2 | Reject-and-revise 30 META draft entries (TRIPOD item numbers wrong, Wynants n wrong, 1 DOI wrong) | methodology expert |
| Q3 | CP-mint decision: mint only CP-052 (per R2 + R4 convergence), not all 3 | methodology expert |
| Q4 | bench_07 codeswitch slice: remove (invalid given BGE-en-only model) or upgrade model | benchmark designer |
| Q5 | bench_05 domain_disagreement sub-bucket: re-label as in-distribution or remove | benchmark designer |
| Q6 | Add IAA / Cohen's κ on CP-Relabel v3/v4 changes (vs an independent reviewer) | independent reviewer |
| Q7 | Pre-register the cp_hit@5 metric definition and stratum boundaries before next eval | publication discipline |
| Q8 | Prospective NC manuscript evaluation (the one thing that breaks the closed-loop bias) | NC editor access |

---

## Self-assessment of this aggregation

This INDEPENDENT_REVIEW.md is itself produced by an LLM (Claude) synthesizing 10 LLM agent reports. It is therefore **not independent in the sense an external reviewer would understand**. The agents were given different lanes and read-only access, which mitigates blind spots within each lane but does not break the meta-loop. A genuinely independent review would require a human methodologist or peer reviewer not previously involved.

The aggregation should be read as: "the strongest internal critique we can muster against our own work". The fact that 10 strict-mode personas converged on B1+B2+B3 as critical blockers is evidence those criticisms are robust, not that the work passes.

---

## File pointers

Full per-reviewer outputs at `/tmp/mlgg_review_agents/R{1..10}_*.md` (transient — re-runnable by re-dispatching the agent prompts in this commit's history).
