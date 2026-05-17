# Agent H — Schema Consistency Audit of `peer-review-kb.json`

**Date**: 2026-05-17
**KB version**: `peer_review_kb.v1.4` (335 entries, 817 concerns)
**Validator**: `/tmp/audit_agent_H_schema_check.py`
**Raw violations dump**: `/tmp/audit_agent_H_violations.jsonl` (1588 records)
**Prior audit context**: `references/case-studies/peer-review-kb-audit-2026-04.md`
(prior audit covered 106 papers / 375 concerns and focused on category labelling
+ `mlgg_gates` retrieval-index health; this audit is about *schema shape*, which
the prior audit explicitly did **not** cover, so no overlap.)

---

## 1. Schema discovery (empirical)

Field intersection over the first 20 entries returned 19 fields present in 20/20
(see §1 of the validator). Across **all** 817 concerns, 12 sub-fields appear in
100% (required) and `canonical_pattern_id` in 84.8% (recommended, not strict).

But mid-validation it became obvious that the KB carries **two entry
sub-schemas** distinguished by the `metadata_source` field:

| Class | Count | Marker | Required-field set |
|---|---|---|---|
| `FULL_SCHEMA` | 160 | no `metadata_source`, OR has it but `reviewer_concerns` populated | 19 fields (DOI, year, domain, model_types, sample_size, review_rounds, reviewer_concerns, reviewer_strengths, outcome, key_methodology_issues/strengths, …) |
| `META_ONLY` | 175 | has `metadata_source` AND empty/missing `reviewer_concerns` | 11 fields (DOI, title, journal, year, data_type, prediction_task, peer_review_pdf_path, pdf_verification, metadata_source, is_cohort_retrospective_binary, id) |

This distinction is baked into the validator — without it, the validator emits
~1500 false positives on `PR-EXP-*` entries that were never meant to carry full
fields. Final counts below use the two-class schema.

---

## 2. Violation counts by severity

| Severity | Count |
|---|---:|
| CRITICAL | 239 |
| MAJOR | 1224 |
| MINOR | 125 |
| **Total** | **1588** |

### By rule

| Severity | Count | Rule |
|---|---:|---|
| MAJOR | 1068 | `concern_tag_unknown` — tag not in `peer-review-kb-tags.json` index |
| CRITICAL | 233 | `missing_required_entry_field` |
| MAJOR | 150 | `strength_not_dict` — `reviewer_strengths` element is a string |
| MINOR | 124 | `missing_recommended_concern_field` (always `canonical_pattern_id`) |
| CRITICAL | 6 | `reviewer_concerns_empty` (full-schema entries with empty concerns) |
| MAJOR | 6 | `review_rounds_dtype_or_range` (value 0 in PR-RO-01..06) |
| MINOR | 1 | `kb_total_concerns_drift` (top-level claim 449 vs actual 817) |

**Caveat on the MAJOR-tag count**: `peer-review-kb-tags.json` mtime is
2026-04-22 — **25 days older than the KB** (mtime 2026-05-17). The tags JSON is
auto-generated from the KB by `parse_peer_reviews.py --stats`, so the 1068
"unknown tag" hits really mean "the tags index is 25 days stale and missing
1027 distinct tag values that have been added to the KB since". This is a
**stale-index drift problem**, not a vocabulary-discipline problem.

---

## 3. Worst entries

| Entry ID | Total | CRIT | MAJ | MIN |
|---|---:|---:|---:|---:|
| `PR-EXP-0160` | **59** | 5 | 48 | 6 |
| `PR-EXP-0084` | 52 | 4 | 44 | 4 |
| `PR-EXP-0097` | 50 | 5 | 43 | 2 |
| `PR-EXP-0212` | 50 | 5 | 40 | 5 |
| `PR-EXP-0109` | 48 | 5 | 43 | 0 |

`PR-EXP-0160` is a **hybrid**: it has `metadata_source` (so it was originally
an OpenAlex auto-discovery stub) **but** it has been promoted with 15
reviewer_concerns and 14 reviewer_strengths — yet it never had its full
metadata back-filled. It is missing `domain`, `model_types`, `sample_size`,
`outcome`, `key_methodology_issues`, `key_methodology_strengths`, and its
`reviewer_strengths` are stored as bare strings rather than dicts. The other
four "worst" entries follow the same pattern.

The pattern of partially-promoted META→FULL entries is the single largest real
schema-integrity issue uncovered.

---

## 4. First 10 violations of each severity

### CRITICAL

| Entry | Rule | Detail |
|---|---|---|
| PR-046 | `reviewer_concerns_empty` | |
| PR-047 | `reviewer_concerns_empty` | |
| PR-060 | `reviewer_concerns_empty` | |
| PR-061 | `reviewer_concerns_empty` | |
| PR-068 | `reviewer_concerns_empty` | |
| PR-097 | `reviewer_concerns_empty` | |
| PR-EXP-0084 | `missing_required_entry_field` | `domain [FULL_SCHEMA]` |
| PR-EXP-0084 | `missing_required_entry_field` | `key_methodology_issues [FULL_SCHEMA]` |
| PR-EXP-0084 | `missing_required_entry_field` | `key_methodology_strengths [FULL_SCHEMA]` |
| PR-EXP-0084 | `missing_required_entry_field` | `model_types [FULL_SCHEMA]` |

(The 6 `PR-NNN` entries with empty concerns are the real `FULL_SCHEMA` entries
that need parsing or removal. The rest of the 233 CRITICAL hits are
promoted-from-meta entries missing fields they ought to have.)

### MAJOR

| Entry | Rule | Detail |
|---|---|---|
| PR-010 | `concern_tag_unknown` | `PR-010-C04: 'auprc_missing'` |
| PR-107 | `strength_not_dict` | `index 0: str` |
| PR-107 | `strength_not_dict` | `index 1: str` |
| PR-107 | `strength_not_dict` | `index 2: str` |
| PR-108 | `strength_not_dict` | `index 0: str` |
| PR-108 | `strength_not_dict` | `index 1: str` |
| PR-108 | `strength_not_dict` | `index 2: str` |
| PR-109 | `strength_not_dict` | `index 0: str` |
| PR-109 | `strength_not_dict` | `index 1: str` |
| PR-110 | `strength_not_dict` | `index 0: str` |

Entries `PR-107` through ~`PR-130` use a flat-string form for
`reviewer_strengths` instead of the dict-with-`strength_id`/`reviewer`/`text`/`tags`
form used everywhere else. This is a **second schema variant** that the rest of
the codebase will not handle consistently.

### MINOR

| Entry | Rule | Detail |
|---|---|---|
| PR-001 | `missing_recommended_concern_field` | `PR-001-C02: canonical_pattern_id` |
| PR-001 | `missing_recommended_concern_field` | `PR-001-C03: canonical_pattern_id` |
| PR-001 | `missing_recommended_concern_field` | `PR-001-C04: canonical_pattern_id` |
| PR-003 | `missing_recommended_concern_field` | `PR-003-C01: canonical_pattern_id` |
| PR-004 | `missing_recommended_concern_field` | `PR-004-C04: canonical_pattern_id` |
| PR-005 | `missing_recommended_concern_field` | `PR-005-C03: canonical_pattern_id` |
| PR-006 | `missing_recommended_concern_field` | `PR-006-C01: canonical_pattern_id` |
| PR-007 | `missing_recommended_concern_field` | `PR-007-C04: canonical_pattern_id` |
| PR-010 | `missing_recommended_concern_field` | `PR-010-C01: canonical_pattern_id` |
| PR-024 | `missing_recommended_concern_field` | `PR-024-C04: canonical_pattern_id` |

Plus 1 top-level drift: `kb_total_concerns_drift: claimed=449 actual=817`
(see §5).

---

## 5. Stats / index drift

### `peer-review-kb-stats.json` — almost in sync

Computed actual values vs claimed:

| Field | Stats claims | Actual |
|---|---:|---:|
| `total_papers` | 335 | 335 (✓) |
| `total_concerns` | 817 | 817 (✓) |
| `total_strengths` | 239 | 239 (✓) |
| `concerns_by_category` (all 13 keys) | matches | matches (✓) |
| `concerns_by_severity` (all 4 keys) | matches | matches (✓) |
| `concerns_by_gate` (29 keys) | matches except 2 | **2 keys mismatch** |
| `top_30_tags` | matches | matches (✓) |

Stats is **97% in sync**. The two `concerns_by_gate` mismatches are minor count
drift (re-run `--stats` will fix).

### `peer-review-kb.json` top-level fields — drifted

- `total_concerns: 449` is wrong — true value is **817** (off by 368).
  The top-level metadata at the start of `peer-review-kb.json` was last updated
  when the KB had 449 concerns and has not been bumped on subsequent ingestion
  rounds. `total_papers: 335` is correct.

### `peer-review-kb-tags.json` — substantially stale

- File mtime is **25 days older** than the KB itself.
- 1027 distinct tag values appear in current KB concerns but are absent from
  the index. Total reference count of these unknown tags: 1068 (so most are
  fresh additions, not legacy renames).
- Re-running `parse_peer_reviews.py --stats` (which regenerates the tag index
  as a side effect — see `cmd_stats` lines 142-151) will rebuild it.

---

## 6. Recommended follow-ups (not part of this audit, do not auto-apply)

1. **Regenerate `peer-review-kb-tags.json` and `peer-review-kb-stats.json`** by
   re-running `python3 parse_peer_reviews.py --stats`. Eliminates 1068 MAJOR
   "unknown tag" hits and the 2 gate mismatches.
2. **Patch the top-level `total_concerns: 449` → 817** in `peer-review-kb.json`
   (one-line metadata fix; needs user approval per project rule "do not modify
   `references/*.json`").
3. **Decide on the second-form `reviewer_strengths`** in PR-107..~PR-130. Either
   migrate them to the dict form, or declare the flat-string form a supported
   variant and update consumers.
4. **Back-fill the 6 empty-concerns FULL_SCHEMA entries** (PR-046, -047, -060,
   -061, -068, -097) or move them to META_ONLY by adding a `metadata_source`
   field.
5. **Fix the 24 promoted-META entries** (PR-EXP-0084, -0097, -0109, -0160,
   -0212, …) that have concerns but are missing `domain`, `model_types`,
   `sample_size`, etc. Either back-fill those fields or formally mark them as
   `_validation_status: "partial_promotion"` so the validator can downgrade
   them to a third sub-schema.
6. **Set `review_rounds` for PR-RO-01..06** — currently 0, should be >=1.

---

## 7. Reproducibility

```sh
/Volumes/Seagate/Skill/.venv/bin/python /tmp/audit_agent_H_schema_check.py
```

Outputs a JSON summary + first-10-of-each-severity to stdout and writes the
full violations list to `/tmp/audit_agent_H_violations.jsonl`. The script is
read-only and touches no `references/*.json` files.
