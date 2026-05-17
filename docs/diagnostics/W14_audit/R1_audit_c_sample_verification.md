# R1 — Audit C sample verification (post-hoc self-review)

**Status**: Self-review finding, NOT yet acted upon. Tags remain as-shipped
in commit `de27889` pending owner adjudication.
**Date**: 2026-05-17
**Method**: Stratified random sample of 10 of audit C's 39 (lit_id, gate)
tag additions (one per distinct gate). Each pair evaluated by reading
the LIT entry's title + key_requirements vs the target gate's stated
purpose. Random seed 42.

## Why this audit pass

Self-review R1 (see CHANGELOG W14 audit block, retrospective entry)
flagged that audit C's 38 tag additions were applied to the production
lit-KB without independent verification. Each tag is a methodological
claim ("paper X authorises gate Y to cite it as precedent"). Confidence
markers in audit C's report (High/Medium/Low) were never validated by
reading the source papers.

This pass samples 10/39 ≈ 26% of the additions and rates each as
✓ correct / ⚠️ weak link / ✗ likely wrong.

## Sample results

| # | LIT id → Gate | Judgment | Reasoning |
|---|---|---|---|
| 1 | LIT-053 → feature_lineage_gate | ✓ | Paper is about ICD codes leaking outcome; gate detects feature-from-definition lineage. Direct hit. |
| 2 | LIT-041 → cohort_definition_gate | ✓ | TRIPOD 2015's 22-item checklist includes participant flow + cohort definition. |
| 3 | LIT-018 → reporting_bias_gate | ✓ | CONSORT-AI is a clinical-trial AI reporting standard; gate enforces reporting standards. |
| 4 | LIT-033 → permutation_significance_gate | ⚠️ | Paper is about competition ranking instability under small score gaps and seed sensitivity. Gate is about permutation-test significance. The link is indirect — ranking-instability ⊋ permutation testing. Better fits: `ci_matrix_gate` or `seed_stability_gate` (which are also tagged for LIT-033 per the diff). |
| 5 | LIT-035 → clinical_metrics_gate | ⚠️ | Paper is about how SMOTE/undersampling harm calibration + sensitivity-vs-specificity trade. Gate audits clinical performance measures. Defensible but the more direct fit is `calibration_dca_gate`. |
| 6 | LIT-036 → ci_matrix_gate | ⚠️ | Permutation Tests for Classifier Performance is the canonical permutation-test reference. ci_matrix_gate's overlap with permutation-derived nulls is indirect — the gate is about CI/CR matrix reporting, not significance testing. |
| 7 | LIT-036 → seed_stability_gate | ✗ | **Concept mismatch**. Permutation test = shuffling class labels to build a null distribution. Seed stability = running with different `random_state` to check determinism / variance. These are different statistical procedures. LIT-036 should NOT carry `seed_stability_gate`. |
| 8 | LIT-010 → feature_engineering_audit_gate | ✓ | Same paper title as LIT-053 (separate duplicate-title issue noted below); the feature-engineering audit angle on ICD-code leakage is direct. |
| 9 | LIT-029 → imbalance_policy_gate | ✗ | **Off-topic**. Paper assesses classic + contemporary performance measures for probability prediction (its category is `calibration`). Gate is about class-imbalance correction policy. No overlap in subject. Should be `evaluation_quality_gate` or `calibration_dca_gate`, NOT imbalance. |
| 10 | LIT-035 → evaluation_quality_gate | ✓ | Same paper as #5; the eval-quality angle on imbalance-corrected metrics is direct. |

## Aggregate

| Verdict | Count | Fraction |
|---|---|---|
| ✓ correct | 5 | 50% |
| ⚠️ weak link | 3 | 30% |
| ✗ likely wrong | 2 | 20% |

**Extrapolation to all 39 audit C additions** (with the usual sampling
caveat):

- ~19–20 confidently correct
- ~11–13 weak-but-defensible
- ~7–8 likely-wrong

That is **>20% error rate** at full coverage if the sample is representative.

## Caveats on this sample audit itself

This R1 verification is **another LLM self-review** with the same
methodological limitations as the M1 / R-meta concerns I previously
raised:

1. The judgments here are produced by Claude Opus 4.7 — the same model
   family that authored audit C's original tags. Systematic blind spots
   are shared.
2. I read titles + the first 2 `key_requirements` per LIT entry, NOT
   the source paper PDFs. A paper's full content may justify a tag even
   if its title doesn't.
3. The "indirect link" / "concept mismatch" calls are interpretive. A
   reviewer who reads the full LIT-036 paper might find seed-stability
   discussion I missed.
4. 10/39 is a small sample; 95% CI on the ✗ rate is wide.

## Recommended owner action

Do NOT auto-revert based on this sample. Instead, for each ⚠️ / ✗ row,
either:

1. Have a clinician-ML methodologist confirm the call (1–2 minute paper
   skim each), OR
2. Accept the ⚠️ tags as "weak but harmless" (they only ever surface as
   secondary precedents in RAG hits) and revert only the ✗ tags after
   independent verification.

If ✗ verifications confirm, the two corrections are:

- Remove `seed_stability_gate` from LIT-036's `gates_implementing`
- Remove `imbalance_policy_gate` from LIT-029's `gates_implementing`

These can ride in a small follow-up commit.

## Separate finding: LIT-010 vs LIT-053 (duplicate title, different DOI)

- LIT-010 — `doi: 10.1001/jamanetworkopen.2024.53956`, year 2025
- LIT-053 — `doi: 10.1001/jamanetworkopen.2025.50454`, year 2025
- Both titled: "Diagnostic Codes in AI Prediction Models and Label
  Leakage of Same-Admission Clinical Outcomes"

Either one paper is registered twice with two DOIs (data-quality bug),
or these are an article + a published correction / response (acceptable
to keep both but should carry an `applicability_note` explaining the
relationship). Owner should verify via DOI lookup.

## Reproducibility

```bash
/Volumes/Seagate/Skill/.venv/bin/python <<'PY'
import json, subprocess, random
before = json.loads(subprocess.run(
    ["git", "show", "de27889^:references/methodology/literature-knowledge-base.json"],
    capture_output=True, text=True).stdout)
after = json.loads(subprocess.run(
    ["git", "show", "de27889:references/methodology/literature-knowledge-base.json"],
    capture_output=True, text=True).stdout)
b = {e["id"]: set(e.get("gates_implementing", [])) for e in before["entries"]}
a = {e["id"]: set(e.get("gates_implementing", [])) for e in after["entries"]}
added = sorted({(lid, g) for lid in set(b)|set(a) for g in a.get(lid,set()) - b.get(lid,set())})
print(f"total added: {len(added)}")
random.seed(42)
gates = sorted(set(g for _,g in added))
sample = [random.choice([t for t in added if t[1]==g]) for g in gates]
random.shuffle(sample)
for lid, g in sample[:10]: print(lid, "->", g)
PY
```
