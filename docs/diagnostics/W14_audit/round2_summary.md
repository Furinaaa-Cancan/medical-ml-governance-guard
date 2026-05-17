# W14 Round-2 Audit — Synthesis

**Date**: 2026-05-17
**Method**: 10 parallel sub-agents launched after the W14 strict self-review
(R1–R5) shipped. Goal: address audit-B's recommendation to audit the other
6 non-negotiable rules for KB coverage, plus deepen R1 / R3 / meta-audit
the original 10 W14 reports.

This round explicitly drew on the calibration lesson from round 1: **agents
who run tests/evals survive post-hoc review; agents who only read code do
not**. Where possible, round-2 prompts asked for runnable evidence
(keyword scan counts, A/B isolation, WebFetch verbatim quotes), not
narrative summary.

## 7-rule KB coverage audit

| Rule | What it enforces | DIRECT count | Tag precision | Verdict |
|---|---|---:|---:|---|
| **S01** | Same patient not cross-split | 9 | 58 % | Well-covered, tags broken |
| **P01** | fit() only on training | 0 | n/a | True 0 in this KB; **but KB is 2-journal Nature-family slice** — absence is sampling bias, not field reality |
| **F01** | Label not as feature | 5 | 1/5 correctly tagged | Floor of "well-covered", tags broken |
| **F02** | No post-prediction info | 8 | Clean | Adequate, F02 tags are reliable (the outlier) |
| **M01** | Test set not in tuning | 14 | gate fires 8× wider than rule | Well-covered |
| **E01** | 95 % CI on primary metric | ~9–10 | 88 % precision, 60 % recall | Coverage gap from tag-only methodology |
| **E02** | Complete metric panel | 22 + 12–15 untagged | 76 % direct rate | Construct OK, under-coding |

Aggregate signal across 6/7 rules: **tag precision and recall are
systemically broken** in `peer-review-kb.json`. Only F02 has clean tags.
This means any audit that counts MLGG-rule tags to make a coverage claim
(including audit-W14-B's "0 P01") is **measuring tag-application
quality**, not phenomenon prevalence.

## Audit-W14-B re-evaluation (the headline of round 2)

Audit B claimed the KB has 0 concerns describing the canonical MLGG-P01
preprocessing-leak pattern (scaler/encoder fitted on full pool before
split). Round-2 Agent 2 (P01-deep) ran a broader 40+ keyword sweep
plus manual classification:

- **count**: confirmed 0 DIRECT_P01 (audit B's number was right)
- **framing caveat audit B missed**: the KB samples only **2 journals**
  (Nature Communications n=248, Communications Medicine n=87), heavily
  weighted to 2024–2025. These are Nature-family flagship venues with
  above-average reviewer ML literacy. **The 0-DIRECT result means
  "P01 doesn't survive Nature peer review", NOT "P01 doesn't exist
  in the field"**.

For the curated fallback (`commit c8e651c`) this means:

1. The fallback IS justified — the KB cannot back P01 with case-study
   evidence regardless of whether the field-wide rate is high.
2. **R3-trace (Agent 9) found the fallback is dead code in the eval
   path anyway**: `scripts/rag/evals/run_eval.py` and `harness.py` both
   route through `rag_query()` directly, bypassing `gate_rag_bridge.
   rag_context_for_failure()` which is the only caller of
   `_curated_precedent_for()`. Even if it weren't, 0/30 scenarios.json
   entries carry `MLGG-P01`/`MLGG-P04` codes or the op+order lexical
   pair, so no scenario would trigger the fallback.

Net: audit B's diagnosis stands, its remedy works in production (gate
runs go through the bridge), but its remedy contributes 0 to the
published eval — exactly as R3 found.

## R1 verified, 2 wrong tags removed

Round-2 Agent 8 (R1-deep) independently WebFetched the source papers
for R1's two ✗ flags:

- LIT-036 (Ojala & Garriga 2010 JMLR) → seed_stability_gate:
  CONFIRMED WRONG. Paper is strictly permutation-significance testing,
  zero seed-stability content.
- LIT-029 (Van Calster STRATOS TG6) → imbalance_policy_gate:
  CONFIRMED WRONG. Paper is probability-evaluation tutorial, zero
  imbalance-correction content.

Both tags removed in `commit 6261b09`. R1's false-positive rate on this
sample: 0/2.

## P01-deep recommended fixes (KB content)

This round applies two specific peer-review-kb fixes recommended by
Agent 2:

1. **PR-006-C01**: remove `MLGG-P01` from `mlgg_rules`. The concern is
   about using one dataset for both GWAS and PRS parameterization
   (discovery/validation overlap → F03/S01 territory), not preprocessing
   fit-on-full.
2. **PR-113-C01**: add `MLGG-P02` to `mlgg_rules`. The concern describes
   SMOTE applied on merged MIMIC-III+IV BEFORE the 7:3 split — this is
   the P02 (resampling sibling of P01) textbook anti-pattern. Currently
   only tagged S01/M01.

These ship in the same commit as this summary doc.

## Meta-audit: which W14 agents were calibrated

Round-2 Agent 10 scored A–J:

| Agent | Calibration | Why |
|---|---|---|
| A (dense ablation) | **High** | numeric A/B; reproducible script |
| B (L27 leak) | Medium | claims about would-do; never ran the harness with patched bridge |
| **C (KB tag draft)** | **Low** | 38 H/M/L markers without PDF verification → R1 confirmed 20%+ wrong |
| D (sort fix) | **High** | pytest output + commit SHA |
| E (M1 desc) | Medium | static text edit; correct but doesn't run anything |
| F (bm25 m8) | **High** | function-level forensics with file:line; m8 was a false positive caught here |
| G (hybrid grid) | Medium | grid ran but did not isolate W13 retune as the actual driver |
| H (schema) | **High** | runnable validator + violation counts |
| I (zero-support) | Medium-High | found cohort=46% of concern volume; tag fix patch verified by R1 against C's overlapping patch |
| J (current state) | **High** | inventory with mtimes + caveats |

**Distinguishing pattern**: the single strongest predictor of post-hoc
survival was whether the agent **ran the test the claim would have to
pass**, vs **read code and asserted what it would do**. R3 caught
attribution inflation precisely because B and C didn't A/B-isolate.

Future audit prompts should require runnable evidence as the load-
bearing claim, not summary text. This is a methodology change worth
encoding into agent prompt templates.

## Items NOT addressed in this round (still open for owner)

1. **The 24 partial-promote PR-EXP-\*** (audit H, schema contract)
2. **F-01 fail-closed escalation** (exit 2 on publication-grade with
   pending entry)
3. **`METRIC_CONTRACT.md` owner** (currently unassigned)
4. **C-vs-I weak-link rows** from R1 (3 ⚠️ that need methodologist
   judgement, not LLM judgement)
5. **R3-trace's 9-line patch** to wire `rag_context_for_failure` into
   the eval harness, plus 1–2 new P01-coded scenarios. The audit B
   fallback can become measurable in the published eval if both land
   together.
6. **Specialty-journal KB sampling**: P01-deep's recommendation to
   broaden peer-review-kb beyond Nature Communications + Comm Medicine
   if the goal is real-world coverage validation.
7. **KB-wide re-tag pass**: 5 of 7 rules audited show systemic tag
   precision/recall problems. A single LLM pass over `concern_text`
   emitting `(rule_id, confidence)` tuples for ALL rules at once
   (Agent 6's recommendation) would be cheaper than per-rule audits.

## What this round means for the W14 audit narrative

The original W14 audit was a real value-add **as a coverage scan** but
made several methodology-bias errors that round-2 caught:

- "P01 = 0 concerns" → correct count, biased framing (now caveatted)
- "audit B/C drove the 0.669 baseline lift" → wrong attribution (R3
  corrected)
- "audit C's 38 tags are H/M/L confidence" → ~20 % were wrong (R1 +
  R1-deep confirmed 2/2; 5 ⚠️ remain pending)
- "ship the curated fallback to address M2" → curated fallback is dead
  code in eval (R3-trace)

None of these errors are catastrophic — the original commits are
still defensible documentation work — but they collectively show
the audit pattern needs run-not-read discipline. Documented for
future waves.
