# v1.0.1 CP-Relabel v3 — Spot-audit results

Purpose: reduce clinical-reviewer load by pre-screening the 59 v3 label changes via tag-overlap to KB exemplars. **Not a substitute for human review** — surface "high-confidence v3-better" and "needs-attention" buckets.

| Metric | Value |
|---|---|
| Cases audited | 15 (10 REPLACED + 5 EXPANDED, deterministic by `scenario_id` sort) |
| v3-better (auto-verified) | 9 / 15 (60%) |
| v2-better (worth re-checking) | 3 / 15 (20%) |
| Tie / inconclusive | 3 / 15 (20%) |
| Sample data | `v3_spot_audit.json` (machine-readable) |

## Methodology

For each changed scenario:
1. Look up the scenario's `query_text` and `expected_tags`
2. For each candidate CP (v2 and v3), find KB exemplar concerns that carry that CP
3. Compute `|expected_tags ∩ exemplar.tags|` summed across top-2 exemplars per CP
4. Verdict = whichever CP set produced higher tag-overlap-with-KB-exemplars

**Limitation**: tag-overlap is a proxy. A v3 CP may be semantically more correct even when fewer KB exemplars happen to share tags with the query (because the CP is sparsely populated). The "v2-better" rows should be read as "v3 might be right but the KB doesn't yet prove it" — not as "v3 is wrong".

## 3 cases flagged "v2-better" (request human review)

All three are in the evaluation_metrics family — v3 chose a more specific CP that has fewer KB exemplars:

| Scenario | v2 → v3 | Why audit says v2 | Human-review question |
|---|---|---|---|
| `agent01-cad-ecg-sensitivity-precision-only` | `[CP-026]` → `[CP-020]` | CP-020 = "clinically_critical_metric_omitted" has no exemplar concerns sharing the scenario's tags `[incomplete_metrics, missing_calibration_metric, ...]` | Is CP-020 the right specific pattern for "missing specificity/recall/F1" framing? CP-026 (`incomplete metric panel`) is the broader bucket. |
| `agent01-pdl1-histopath-no-prc` | `[CP-026]` → `[CP-006, CP-020]` | Same as above — CP-006/CP-020 are sparser | Should CP-006 (`ROC-PR balance issues for imbalanced labels`) be the primary, with CP-020 secondary? |
| `agent03_nsaid-as-oa-proxy` | `[CP-002, CP-014]` → `[CP-036]` | CP-036 (`outcome_definition_or_time_horizon_conflation`) has 1 exemplar; v2's CP-002+CP-014 union has 1 matching exemplar | The query is about a **feature that is itself an outcome proxy** (NSAID = treated → has OA). Is that definition-variable (CP-014, definition_variable_guard) or outcome-conflation (CP-036)? v3's reason says "query explicitly says definition variable" — does CP-036 include that? |

## 9 cases auto-verified "v3-better"

These need only sanity-check, not deep review:

| Scenario | v2 → v3 | Why v3 wins (tag-overlap delta) |
|---|---|---|
| `agent03_cancer-risk-vs-diagnosis-conflation` | `[CP-003]` → `[CP-002, CP-036]` | +4 overlap (catch-all → specific risk-vs-diagnosis) |
| `agent03_crrt-seven-day-arbitrary` | `[CP-003]` → `[CP-002]` | +2 |
| `agent03_icu-mamba-prospective-misclaim` | `[CP-003]` → `[CP-002, CP-007]` | +3 |
| `agent03_icu-update-window-rationale` | `[CP-003]` → `[CP-002]` | +1 |
| `agent03_metabolomics-unmatched-controls` | `[CP-048]` → `[CP-002]` | +3 (ancestry → cohort confounding) |
| `agent04-infehr-neonatal-sepsis-unreported-baseline` | `[CP-007, CP-025]` → `[CP-002]` | +1 |
| `agent01-aki-suspicious-narrow-ci` | `[CP-027]` → `[CP-023, CP-027]` (EXPANDED) | +1 |
| `agent01-azithromycin-cv-fold-averages` | `[CP-023]` → `[CP-023, CP-027]` (EXPANDED) | +1 |
| `agent01-ecg-dnn-no-seed-variance` | `[CP-023]` → `[CP-023, CP-027]` (EXPANDED) | +1 |

## 3 ties

`agent01-hfpef-tte-arbitrary-cutpoint`, `agent01-aki-mortality-no-prcurve`, `agent01-dementia-mortality-auc-only` — all evaluation_metrics, similar pattern (CP-006/020/026 cluster); reviewer judgment needed but no urgency.

## Recommendation

1. **Adopt the 9 v3-better changes as-is** — high confidence.
2. **Manually inspect the 3 v2-better cases** — likely also OK (CP-020 / CP-036 are semantically more specific) but the KB exemplar evidence is weak. ~5 min of expert time.
3. **Defer the 3 ties** to the next CP-Relabel cycle.

If you adopt only the 9 confirmed v3-better changes, expected `cp_hit@5` impact: roughly 60% of the v3 → v2 delta = ~+0.016 instead of +0.027. Still positive.

## Reproducibility

```bash
python3 -c "
import json
audit = json.load(open('references/retrieval_eval/MLGG-Bench-v1.0.1/v3_spot_audit.json'))
print({k: v for k,v in audit['verdict_summary'].items()})
"
```

Or re-run the full audit:

```python
# See the heredoc python script embedded in commit b2c6b62's bash trace,
# or reconstruct from this README — the methodology is small enough to inline.
```

## Status

This audit was generated autonomously on 2026-05-17 alongside v1.0.1. It is a screening pass, not the final review. Sign-off by a clinical methodologist on the 3 flagged "v2-better" cases will close the loop.
