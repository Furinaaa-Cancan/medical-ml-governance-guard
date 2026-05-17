# W18-D4 — BM25 Tokenization + Synonym Audit

**Scope:** 20 sample queries probed against `scripts.rag.retrieval.bm25`
(`_issue_code_keywords`, `retrieve_for_failure`, `retrieve_by_text`). Goal:
confirm that the W8-G8 short-token allow-list (`ci`, `r2`, `hr`, `ml`, `ai`,
`df`, `or`) and the `TAG_SYNONYMS` map together produce tokens that hit the
intended KB tags — and surface tokens that misfire or are missing.

**Mode:** READ-ONLY, in-process via `python3 -c`.
**Source script:** `/tmp/W18_D4_audit_script.py`
**Raw output:** `/tmp/W18_D4_audit_raw.json`, `/tmp/W18_D4_console.txt`
**KB:** 817 concerns across 184 entries (current `peer-review-kb.json`).

---

## Summary

| Metric | Value |
|---|---|
| Queries probed | 20 |
| Total tokens emitted (sum of per-query token sets) | 136 |
| MISFIRE tokens flagged (high-frequency English fragments) | 5 |
| MISSING tokens flagged (suspicious drops: `id`, `or`) | 3 |
| `TAG_SYNONYMS` entries | 65 |
| `SHORT_TOKEN_ALLOWLIST` entries | 7 (`ci, r2, ml, ai, df, or, hr`) |
| `_CODE_TOKEN_STOPWORDS` | 24 |

**Verdict: YELLOW** — the W8-G8 short-token allow-list works: `ci / r2 / hr /
df / ml / ai` survive code-path tokenization (Q03, Q07, Q08, Q15, Q16) and
`MLGG-X01` codes are reachable in three citation forms each. Off-scope queries
correctly return empty (Q17). Issues are softer:

1. **Synonym-expansion bloat.** Long synonym chains (Q02, Q18, Q20) emit
   12–17 tokens per code, several of which (`data`, `feature`, `before`,
   `via`) are very broad and would inflate text-overlap noise in any single
   concern that happens to mention them.
2. **`or` is both a stopword candidate AND in the short allow-list.**
   `_STOPWORDS` includes neither `or` nor `id`, but `or` is in
   `SHORT_TOKEN_ALLOWLIST` (odds-ratio). Q01/Q15 surface this collision:
   when "or" appears as natural-language conjunction it is treated as a
   medical abbreviation and survives. Low impact (single 2-char token), but
   semantically wrong.
3. **`id` is silently dropped.** Q04 ("patient id leaked…") loses `id`
   because length is 2 and not in the allow-list. `id` is a clear domain
   token in MLGG (patient_id_leakage).
4. **Gate-emitted codes outside `TAG_SYNONYMS`.** ~12 production gate codes
   have no entry — they will tokenize but cannot pull synonym families
   (PR-curve, calibration, fairness, reporting).

---

## Per-query table

| qid | query (truncated) | gate | top-1 paper\|sev\|mode\|s | misfire | missing |
|---|---|---|---|---|---|
| Q01 | no calibration plot or Brier score | calibration_dca_gate | PR-024\|MED\|kw\|10 | – | `or` |
| Q02 | missingness imputation done before split | split_protocol_gate | PR-072\|CRIT\|kw\|11 | `data` | – |
| Q03 | AUROC reported without confidence interval bootstrap | ci_matrix_gate | PR-EXP-0159\|MED\|kw\|8 | – | – |
| Q04 | patient id leaked across train test split | leakage_gate | PR-EXP-0185\|HIGH\|kw\|10 | – | `id` |
| Q05 | outcome variable used as feature | definition_variable_guard | PR-001\|CRIT\|kw\|6 | – | – |
| Q06 | no decision curve analysis clinical utility | calibration_dca_gate | PR-024\|MED\|kw\|20 | – | – |
| Q07 | `ci_matrix_not_passed` | ci_matrix_gate | PR-EXP-0159\|MED\|kw\|8 | – | – |
| Q08 | `missing_ci_method` | ci_matrix_gate | PR-EXP-0159\|MED\|kw\|8 | – | – |
| Q09 | ppv too low (`clinical_floor_ppv_not_met`) | clinical_metrics_gate | PR-004\|HIGH\|kw\|8 | – | – |
| Q10 | `ci_width_exceeds_threshold` | ci_matrix_gate | PR-035\|HIGH\|kw\|10 | – | – |
| Q11 | MLGG-S01 violation | leakage_gate | PR-EXP-0185\|HIGH\|kw\|10 | – | – |
| Q12 | MLGG-F02 future info | leakage_gate | PR-010\|CRIT\|kw\|6 | – | – |
| Q13 | MLGG-P01 fit on test | split_protocol_gate | PR-EXP-0155\|HIGH\|kw\|11 | `test` | – |
| Q14 | MLGG-E02 calibration missing | calibration_dca_gate | PR-002\|HIGH\|kw\|10 | – | – |
| Q15 | hr or df reported | ci_matrix_gate | PR-EXP-0159\|MED\|kw\|6 | – | `or` |
| Q16 | r2 ci ml ai | evaluation_quality_gate | PR-EXP-0110\|MED\|kw\|5 | – | – |
| Q17 | wood joinery dovetail mortise tenon (OFF-SCOPE) | free_text_probe | (empty) | – | – |
| Q18 | `discharge_finalized_icd_as_feature` | leakage_gate | PR-001\|CRIT\|kw\|23 | `feature` | – |
| Q19 | smote class imbalance unjustified | imbalance_policy_gate | PR-027\|HIGH\|kw\|17 | – | – |
| Q20 | `fit_before_split_detected` | split_protocol_gate | PR-113\|CRIT\|kw\|15 | `before, data` | – |

Legend: `kw` = `keyword_match`, `s` = raw overlap score, sev abbreviated.

---

## Token-class spot checks

- **Single-char tokens:** none ever survive (`len(tok) >= 3 or in allow-list`).
  Safe.
- **2-char tokens:** only allow-list members survive
  (`ci, r2, ml, ai, df, or, hr`). All seven appear in production gate codes
  (`missing_ci_method`, `r2_ci_missing`, `ml_ai_overstated`). PASS.
- **Domain codes `MLGG-S01` / `PR-018`:** the `code.lower().replace("-", "_")`
  normalisation feeds the synonym probe correctly. Q11–Q14 all retrieved
  semantically correct concerns at top-1.
- **Stopword vs domain:** `calibration`, `confidence`, `interval`,
  `imbalance`, `bootstrap`, `temporal` all preserved. `the / and / for / not`
  stripped. Correct.
- **`data` as token (broad):** appears as a *tag* in 50/817 concerns (~6%).
  Not catastrophic, but a synonym-chain query like Q02 emits 11 tokens
  including `data` and `via`, which contribute false-positive overlap.

---

## TAG_SYNONYMS gap list (top 10 missing entries)

Gate-emitted codes observed in `scripts/gates/*` that have **no** entry in
`TAG_SYNONYMS`. Without a synonym mapping they tokenize into raw fragments
that often miss the right KB tag family — `retrieve_for_failure` then falls
back to severity-only ranking.

1. `clinical_floor_ppv_not_met` → ought to map to `low_ppv`,
   `clinical_floor_violation`
2. `clinical_floor_sensitivity_not_met` → `low_sensitivity`,
   `clinical_floor_violation`
3. `baseline_improvement_insufficient` →
   `missing_baseline_comparison`, `incremental_improvement_small`
4. `fairness_disparity_exceeds` → `fairness_audit_missing`,
   `subgroup_disparity`
5. `shap_only_visual` → `shap_presentation`, `explainability_insufficient`
6. `no_external_validation` (already a tag, but no synonym key) →
   `external_validation_missing`, `single_center`
7. `no_subgroup_analysis` → `subgroup_analysis_missing`,
   `fairness_audit_missing`
8. `tripod_ai_missing` → `tripod_ai_noncompliance`, `reporting_bias`
9. `covariate_shift_detected` → `distribution_shift`,
   `external_validation_missing`
10. `epv_violation` → `overparameterized`, `underpowered`,
    `events_per_variable`

---

## Cross-check vs W14-F1

W14-F1 attributed the recall@5 drop to stale labels. This audit confirms the
**token layer is not the primary culprit** — code-path tokenization is
deterministic and produces semantically valid tokens for every query that
matched a synonym key. However, BM25 *does* now boost newer concepts whenever
a long synonym chain (Q18, Q20) emits 10+ tokens, several of which appear in
more recently-added KB entries. This compounds the W14-F1 stale-label
finding; not a new root cause, but a noise multiplier worth tracking in
W19+ eval.

---

## Wave-N+ fix candidates

| # | Fix | Effort | Owner-hint |
|---|---|---|---|
| F1 | Add `id` to `SHORT_TOKEN_ALLOWLIST` (patient_id_leakage anchor) | XS | rag-bm25 |
| F2 | Remove `or` from `SHORT_TOKEN_ALLOWLIST` OR add it to `_STOPWORDS` for the text-path (resolve conjunction collision) | XS | rag-bm25 |
| F3 | Add the 10 TAG_SYNONYMS gap entries above (PPV / sensitivity / fairness / TRIPOD / EPV) | S | rag-bm25 |
| F4 | Cap per-code synonym expansion at N tokens (Q18 emits 17 — diminishing returns past ~8) | S | rag-bm25 |
| F5 | Promote `data, feature, before, via, test` into `_CODE_TOKEN_STOPWORDS` (drop only from issue-code path, keep in concern_text matching) | XS | rag-bm25 |
| F6 | Wire an eval-time assertion: top-1 must not be `severity_fallback` for any labeled query with `failure_codes != []` | M | rag-eval |

---

## Verdict

**YELLOW.** Tokenization layer is structurally sound — W8-G8's short-token
allow-list is doing its job, the synonym map covers the canonical MLGG-X01
public interface in three forms each, and off-scope queries are correctly
rejected. Two micro-bugs (`id` dropped, `or` over-preserved) and ~10
unmapped gate codes are the main outstanding work; none of these block
production but each one quietly degrades precision on a subset of queries.

No code changes recommended in this wave (audit only). F1–F5 are XS/S
candidates for a follow-up wave; F6 is the structural guard that would
make this audit redundant going forward.
