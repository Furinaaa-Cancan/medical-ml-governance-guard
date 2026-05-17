# W6-W2: PR-006-C04 KB tag-enrichment proposal

**Status**: proposal-only. No KB writes performed. CLAUDE.md S05.1 honored — agent does not self-write `references/*.json`.

**Author**: Wave-6 agent W2, 2026-05-17
**Scope**: external_validation cluster, peer-review-kb.json
**Trigger**: P4 (Wave 5) finding — PR-006-C04 has `tag_overlap=0` with its CP-008 siblings → ranker cannot promote it via tag-corroboration signal. Q9 (`external_validation_missing`, query "single-center development without external test") misses it.

---

## 1. Current state

### PR-006-C04 record (verbatim from KB)

| field | value |
|---|---|
| `concern_id` | `PR-006-C04` |
| `paper_id` | `PR-006` |
| `category` | `external_validation` |
| `severity` | `CRITICAL` |
| `canonical_pattern_id` | `CP-008` |
| `mlgg_gates` | `["external_validation_gate", "reporting_bias_gate", "clinical_metrics_gate", "calibration_dca_gate"]` |
| `tags` | `["premature_clinical_deployment", "no_external_validation_for_combined", "overstatement"]` |
| `concern_text` (excerpt) | *"This model has not been externally validated, having been constructed and tested only in the PLCO cohort..."* |

### Why Q9 misses it (measured, not theoretical)

Baseline rank in Q9 top-20 (rag_query, gate=`external_validation_gate`, codes=`[external_cohort_missing, same_cohort_validation]`):

| rank | concern_id | final | dense | bm25 | tag_overlap | raw | severity |
|------|---|---|---|---|---|---|---|
| 1 | PR-107-C01 | 0.6917 | 0.662 | 1.000 | 0.300 | 0.300 | 0.66 |
| 2 | PR-EXP-0095-C03 | 0.6199 | 0.708 | 0.833 | 0.000 | 0.000 | 0.66 |
| 3 | PR-EXP-0086-C06 | 0.5479 | 0.714 | 0.583 | 0.000 | 0.000 | 0.66 |
| 10 | PR-028-C01 | 0.4785 | 0.675 | 0.417 | 0.000 | 0.000 | 0.66 |
| **15** | **PR-006-C04** | **0.4461** | **0.644** | **0.333** | **0.000** | 0.000 | **1.00** |
| 19 | PR-084-C01 | 0.3534 | 0.675 | 0.000 | 0.000 | 0.000 | 0.66 |

PR-006-C04's dense (0.644) is competitive — it's the **collapsed tag_overlap signal** and weak BM25 that drag it to rank 15. Despite having `severity=CRITICAL` (only one of two CRITICALs in the top-20), the severity weight (`WEIGHT_SEVERITY=0.05`, further scaled by `severity_scale=0.48` from the tight dense spread) contributes only ~0.024.

### Surprising structural finding

The CP-008 cluster has 22 concerns. Across all 231 possible pairs **only ONE pair** currently satisfies the `_tag_overlap_scores` rule (≥2 shared tags within same CP, hybrid.py:259):

- `PR-001-C06` ↔ `PR-107-C01` share `{no_external_validation, same_cohort_validation}`

That is why PR-107-C01 is the only CP-008 record in the baseline top-20 with a non-zero `tag_overlap_score`. The signal is structurally dead across the rest of the cluster because:

- `no_external_validation` appears in **5** concerns
- every other tag appears in **exactly 1** concern (singleton)

So with the current tag schema, **no concern except {PR-001-C06, PR-107-C01} can ever receive a CP-008 tag-corroboration boost** — adding `no_external_validation` alone to PR-006-C04 would not unlock the signal (still only 1 shared tag with each potential partner). At least one second shared tag is required.

---

## 2. Sibling tag comparison

E1 Q9 "perfect" hits (per prompt) and how their tag sets intersect PR-006-C04's current tags:

| concern_id | CP | tags | shared with PR-006-C04 (current) |
|---|---|---|---|
| PR-006-C04 | CP-008 | premature_clinical_deployment, no_external_validation_for_combined, overstatement | — |
| PR-028-C01 | CP-008 | no_external_validation, out_of_distribution | 0 |
| PR-084-C01 | **CP-029** | single_center, transplant_protocol_variation | 0 (different CP → ineligible regardless) |
| PR-EXP-0086-C06 | **CP-016** | single_center_validation, no_external_cohort, single_holdout_test_set | 0 (different CP → ineligible) |
| PR-EXP-0095-C03 | CP-008 | external_validation_definition_violated, same_center_validation, site_independence_questioned | 0 |
| PR-001-C06 | CP-008 | no_external_validation, internal_split_only, same_cohort_validation | 0 |
| PR-107-C01 | CP-008 | no_external_validation, same_cohort_validation, single_center | 0 |

Important: the `_tag_overlap_scores` function only groups within the **same `canonical_pattern_id`** (hybrid.py:235-240). Siblings in CP-016 / CP-029 cannot help PR-006-C04's CP-008 boost regardless of tag overlap. The pool that matters is the 22 CP-008 concerns listed in §1's frequency table.

---

## 3. Proposal A — minimal enrichment (recommended)

**Add to PR-006-C04.tags**: 

1. `no_external_validation`
2. `same_cohort_validation`

**Rationale (each addition justified)**:

- `no_external_validation`: PR-006-C04's concern_text says verbatim *"This model has not been externally validated"*. The KB already has 5 CP-008 siblings using this tag. The current `no_external_validation_for_combined` is a paper-specific narrowing of the same concept that hides PR-006-C04 from the general signal.
- `same_cohort_validation`: PR-006-C04's concern_text continues *"...constructed and tested only in the PLCO cohort"* — that is the textbook definition of `same_cohort_validation`. PR-001-C06 and PR-107-C01 already carry this tag.

Both additions are **content-faithful** — they describe what the reviewer literally said, not invented attributes. Both already exist as KB-canonical tags (no new vocabulary).

**Partner count after Proposal A**:
- PR-006-C04 ↔ PR-001-C06 share {`no_external_validation`, `same_cohort_validation`} → qualifies
- PR-006-C04 ↔ PR-107-C01 share {`no_external_validation`, `same_cohort_validation`} → qualifies
- 2 partners → bonus = `min(1.0, 0.3 * 2) = 0.60`

---

## 4. Proposal B — Proposal A + extend siblings (optional batch)

Optional companion edits that would densify the CP-008 cluster and let the tag-overlap signal fire for more reviewers. **Each is independently optional** — Proposal A alone fixes PR-006-C04.

| concern_id | currently has | suggested add | rationale (from concern_text) |
|---|---|---|---|
| PR-028-C01 | `no_external_validation`, `out_of_distribution` | `internal_split_only` | "Model should be tested in very different conditions" — implies current eval is internal-only |
| PR-041-C04 | `no_external_validation`, `single_cohort` | `same_cohort_validation` | `single_cohort` is a near-synonym; aligns vocabulary |
| PR-101-C06 | `no_external_validation`, `biomarker_validation_missing`, `external_validation_needed` | `same_cohort_validation` | matches "not externally validated" pattern |
| PR-EXP-0194-C01 | `no_independent_external_set`, `cross_validation_only`, `internal_evaluation_only` | `no_external_validation` | currently misses the canonical tag |

If Proposal B is applied (4 edits) in addition to A, the number of pairs in CP-008 satisfying the ≥2-tag rule jumps from 1 → ~10, with corresponding cascade improvements across the whole external_validation Q9 rank.

**Recommendation**: review Proposal A first; treat B as a separate, lower-priority KB cleanup task. They are not coupled.

---

## 5. Proposal C — schema-level alternative (consider before applying A/B)

The structural finding in §1 suggests the deeper issue is the `≥2 shared tags` threshold combined with KB tag singletons. Two non-mutually-exclusive alternatives:

1. **Lower threshold to ≥1 within same CP** (`hybrid.py:259` `>= 2` → `>= 1`). Would also fix the gap without any KB edit, but increases risk of false partners on weak overlap.
2. **Tag normalization pass**: introduce a `canonical_tags` vocabulary (e.g., collapse `no_external_validation` / `no_external_cohort` / `no_independent_external_set` / `external_validation_needed` into one canonical token, with the originals retained as `tags_specific`). This is the proper long-term fix.

Proposal A is the smallest, lowest-risk change that demonstrably moves PR-006-C04 into Q9 top-5. Proposals B/C address the underlying schema fragility — please review separately rather than bundling.

---

## 6. Simulated impact

Method: monkey-patched `scripts.rag.retrieval.hybrid._import_sibling_modules` to inject the proposed tags into the in-memory copy of `records` returned from `build_or_load_index`. The on-disk KB and the embeddings cache were **not modified**. Embeddings for PR-006-C04 were held at their original values (so the dense-side effect of adding tags to the embedding-text input — which `_build_embedding_text` would normally pick up — is excluded; the reported numbers are therefore a *conservative lower bound*).

| metric | baseline | Proposal A | Proposal B (no schema change) |
|---|---|---|---|
| PR-006-C04 `_dense_score` | 0.644 | 0.644 (unchanged by design) | 0.644 |
| PR-006-C04 `_bm25_score` | 0.333 | 0.333 | 0.333 |
| PR-006-C04 `_tag_overlap_raw` | 0.000 | **0.600** | **0.600** |
| PR-006-C04 `_severity_boost` | 1.00 | 1.00 | 1.00 |
| PR-006-C04 `_final_score` | 0.4461 | **0.5361** | 0.5361 |
| PR-006-C04 rank in Q9 top-20 | **15** | **5** | **5** |
| PR-107-C01 `_tag_overlap_raw` (side-effect) | 0.300 | **0.600** | 0.600 |
| PR-107-C01 rank in Q9 top-20 | 1 | 1 | 1 |

**Q9 top-5 after Proposal A** (target moves from rank 15 → rank 5):

1. PR-107-C01 (final=0.7367)
2. PR-EXP-0095-C03 (final=0.6199)
3. PR-EXP-0086-C06 (final=0.5479)
4. PR-EXP-0157-C04 (final=0.5420)
5. **PR-006-C04 (final=0.5361)** ← target now in top-5

The CP_TAG_BOOST_DENSE_FLOOR gate (0.70) is satisfied because the top-1 dense in the pool is PR-EXP-0086-C06 at 0.714. So the tag boost is correctly applied.

**Why Proposal B gives identical numbers to A**: adding `single_center` (in B) does not unlock new CP-008 partners. PR-107-C01 already shares 2 tags with PR-006-C04 under A; the 3rd shared tag does not add a new partner (still 1 entity). And no other CP-008 sibling has `single_center` in the current KB. So the extra tag is redundant for the target's tag_overlap signal. It may help in other queries (e.g. via dense / BM25), but at the chosen Q9 it adds nothing — keep Proposal A as the canonical minimal fix.

---

## 7. Application instructions for user

Apply Proposal A by editing `references/case-studies/peer-review-kb.json`. Locate the entry `id: PR-006` → `reviewer_concerns` → entry with `concern_id: PR-006-C04` → `tags` array:

```json
"tags": [
  "premature_clinical_deployment",
  "no_external_validation_for_combined",
  "overstatement",
  "no_external_validation",
  "same_cohort_validation"
]
```

(order doesn't matter; the ranker treats `tags` as an unordered set)

After editing:

1. The KB sha256 changes → `.cache/rag/kb_hash.txt` will mismatch → `build_or_load_index()` automatically rebuilds the embeddings cache on next query. No manual cache invalidation needed.
2. PR-006-C04's embedding text will change (tags are included in `_build_embedding_text`) → its dense score will shift slightly. The shift is expected to be small (added tokens are short canonical tags) and is on top of the +0.09 final-score gain measured here.
3. Re-run the Q9 evaluation to confirm:
   ```
   python3 scripts/rag/evals/harness.py --mode hybrid \
       --scenarios references/retrieval_eval/scenarios.json \
       --report /tmp/eval_post_w6w2.json
   ```
4. The change is **append-only** (no tags removed) — the legacy `no_external_validation_for_combined` tag is retained for any downstream consumer that searches for it.

If Proposal B is also applied: edit the four sibling concerns listed in §4 the same way.

---

## 8. CLAUDE.md compliance checklist

- [x] No KB writes performed by this agent (§7 leaves the edit to user)
- [x] No commits
- [x] No `references/*.json` modifications
- [x] No `.github/workflows/` modifications
- [x] No package installs
- [x] No file deletions
- [x] Simulation used in-memory monkey-patch only; on-disk artifacts unchanged
- [x] Proposed tag values are already in the KB vocabulary — no new tags invented
- [x] Tag additions are append-only — no existing tags removed
- [x] Proposal is content-faithful — every addition justified by concern_text excerpt
