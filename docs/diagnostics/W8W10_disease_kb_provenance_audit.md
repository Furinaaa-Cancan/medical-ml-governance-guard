# W8-W10: Disease KB provenance audit

**Agent**: Wave8-W10 (diagnostic-only, no commits, no KB writes)
**Date**: 2026-05-17
**Scope**: `references/methodology/disease-definition-knowledge-base.json` (+ companion review checklist)
**Trigger**: project memory `project_disease_kb_provenance.md` — "Disease-KB is LLM-generated, needs clinical review + guideline citations before publication-grade claims."

---

## Files inspected

| File | Size | Lines | Role |
|---|---:|---:|---|
| `references/methodology/disease-definition-knowledge-base.json` | 36,968 B | 1,194 | Primary disease KB (11 diseases) |
| `references/methodology/DISEASE_KB_REVIEW.md` | 2,975 B | 83 | Clinician review checklist + per-disease review log |
| `references/methodology/medical-disease-leakage.md` | 3,958 B | 90 | Narrative methodology (not a KB) |
| `references/methodology/literature-knowledge-base.json` | 69,394 B | 1,748 | Out of scope (literature, not disease defs) |

No other `*disease*` / `*clinical*` KB JSON files exist under `references/` (case-studies dir contains peer-review PDFs, not KB data).

KB version: **1.1** (change-log entry dated 2026-04-17, "P0-2: added per-disease provenance field"). Only one change-log entry exists.

---

## Provenance state

### Top-level (KB-wide)

| Field | Present? | Value |
|---|---|---|
| `methodology_reference.framework` | YES | Torralbo 2025 (Sci Rep) — full citation + DOI |
| `methodology_reference.diabetes_specific` | YES | Eastwood 2016 (PLOS ONE) — full citation |
| `methodology_reference.principle` | YES | Multi-source adjudication rationale |
| `change_log` | YES | 1 entry (v1.1) |
| Top-level `clinical_reviewer` / `kb_approver` | NO | Absent |
| Top-level `evidence_layers` / `adjudication_strategies` | YES | Mirrors UKB methodology |

### Per-disease (11/11 entries)

| Disease | `provenance` block | `source` | `clinician_review_status` | `reviewer` | `last_reviewed` | Inline guideline citation |
|---|---|---|---|---|---|---|
| type_2_diabetes | YES | llm_compiled | pending | null | null | NO (`ukb_validation` quotes Eastwood 2016) |
| hypertension | YES | llm_compiled | pending | null | null | NO |
| coronary_heart_disease | YES | llm_compiled | pending | null | null | NO |
| chronic_kidney_disease | YES | llm_compiled | pending | null | null | NO |
| heart_failure | YES | llm_compiled | pending | null | null | NO |
| stroke | YES | llm_compiled | pending | null | null | NO |
| copd | YES | llm_compiled | pending | null | null | NO |
| major_depressive_disorder | YES | llm_compiled | pending | null | null | NO |
| cancer_any | YES | llm_compiled | pending | null | null | NO |
| atrial_fibrillation | YES | llm_compiled | pending | null | null | NO |
| readmission_30day | YES | llm_compiled | pending | null | null | NO |

**Summary:**
- Provenance block coverage: **11 / 11 = 100%**
- `source == "llm_compiled"`: **11 / 11 = 100%**
- `clinician_review_status == "pending"`: **11 / 11 = 100%**
- Entries with a named clinician reviewer: **0 / 11 = 0%**
- Entries with disease-specific guideline citation field (e.g., ADA/KDIGO/ACC-AHA): **0 / 11 = 0%**
- Entries with `last_reviewed` timestamp: **0 / 11 = 0%**

### Downstream surfacing (confirmed working)

`scripts/codebooks/_kb_provenance.py` defines a shared helper used by `cohort_definition_gate`, `definition_variable_guard`, `feature_lineage_gate`, and codebook lookups. For any disease entry where `clinician_review_status != "clinician_reviewed"`, gate issue messages are post-fixed with:

```
[KB entry is LLM-compiled and not yet clinician-reviewed.]
```

So end-users *are* warned at gate-output time. The hint is asserted by `tests/test_disease_kb_provenance.py`. Good — the failure mode is "warn loud", not "silent claim of clinical authority".

---

## Critical findings (block publication-grade claims)

1. **F-01 [CRITICAL] Zero clinician sign-off across 11 / 11 diseases.** Every entry self-declares as LLM-compiled and pending. Any paper or audit report that cites these `definition_variables_to_exclude` lists as authoritative for leakage detection inherits an un-arbitrated LLM provenance chain. The framework's safety-critical field per the review checklist (Section "Checklist per disease", item 8) is exactly the field with no human verification.

2. **F-02 [HIGH] No per-disease guideline citation field.** Top-level `methodology_reference` cites Torralbo 2025 + Eastwood 2016 for the *structure* (5 evidence layers, multi-source adjudication). But the *content* — ICD-10 ranges, ATC codes, lab thresholds, exclusion sets — has no per-disease provenance. e.g., the `chronic_kidney_disease` entry has no field pointing to KDIGO 2024; `coronary_heart_disease` has no ACC/AHA citation; `major_depressive_disorder` has no DSM-5 / ICD-11 anchor. `provenance.description` is a *boilerplate string identical across all 11 entries* — it does not name the guideline a clinician should benchmark against.

3. **F-03 [HIGH] Lab-threshold versioning gap.** Thresholds (e.g., HbA1c ≥6.5%) are present but un-dated and un-versioned. Guidelines drift (ADA updates yearly; KDIGO revised CKD staging in 2024). No `guideline_version` / `effective_date` per threshold means stale-threshold drift is undetectable.

4. **F-04 [MEDIUM] No `change_log` for content edits.** The change_log has a single entry recording the addition of the provenance block itself. Any future variable additions/removals will be invisible in the log → undermines reproducibility claims (which the framework otherwise enforces via TRIPOD+AI / PROBAST+AI gates).

5. **F-05 [MEDIUM] `ukb_validation` only on `type_2_diabetes`.** 1 / 11 has any quantitative validation snippet (Eastwood 75% PPV). The other 10 have no validation evidence — neither sensitivity, specificity, nor PPV against any reference standard.

6. **F-06 [LOW] `DISEASE_KB_REVIEW.md` review log is empty.** All 11 sections still say "Status: pending — Notes: —". The review workflow is documented but un-exercised. No clinician has been assigned, and there is no due date or escalation path.

7. **F-07 [LOW] No top-level KB-wide sign-off block.** Even if individual diseases are reviewed, there's no top-level `kb_governance` field for the KB-as-a-whole approver, version-approval date, or clinical-board attestation. Standards files (`standards/journal-rigor-standards.json` etc.) likely have a similar gap (out of scope for this audit but worth a follow-up).

---

## Recommendation: backlog ticket scope

**Title**: `disease-kb-v1.2: per-disease guideline anchors + clinical sign-off workflow`

**Acceptance criteria**:

1. Add a per-disease field `clinical_guideline_anchor` (object, not string), e.g. for T2D:
   ```json
   "clinical_guideline_anchor": {
     "primary": "ADA Standards of Care in Diabetes 2024",
     "doi": "10.2337/dc24-Srev",
     "guideline_version": "2024",
     "thresholds_dated_to": "2024-01-01"
   }
   ```
2. Add per-threshold `effective_date` + `source_guideline_id` for every lab criterion.
3. Add `kb_governance` top-level block with `kb_approver`, `approval_date`, `next_review_due`.
4. Recruit / contract one clinician per disease cluster (cardio-metabolic / renal / pulm / psych / onc / general); track in `DISEASE_KB_REVIEW.md`.
5. Define a CI check that fails the publication-grade gate (PROBAST+AI or a new `publication_grade_gate`) if any disease used in a paper has `clinician_review_status == "pending"`. Today the hint is surfaced but is not fail-closed for publication-grade outputs.
6. Backfill `ukb_validation` (or generalized `external_validation`) for the 10 missing diseases.
7. Promote `change_log` to require an entry for every content delta (CI lint).

**Estimated effort**: 1 clinician-week per disease cluster (5 clusters → 5 weeks) + 2 dev-weeks for schema/CI.

**Risk if deferred**: any external user citing MLGG's leakage findings as authoritative for a published model definition inherits an un-arbitrated LLM-compiled artifact — falsifiable under peer review.

---

## CLAUDE.md compliance

- No KB writes performed. All access read-only (`Read`, `Bash` for `python3 -c json.load`, no `Edit`/`Write` on `references/**`).
- No commits, no git operations.
- No data files opened beyond the JSON KB itself.
- Per CLAUDE.md NEVER-rule 1 ("不自行写入 `references/*.json`"): respected. Recommendations are scope-only; user must confirm before any v1.2 schema migration.
- Output written to `/tmp/W8W10_disease_kb_provenance_audit.md` (outside project tree).
