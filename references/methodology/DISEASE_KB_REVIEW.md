# Disease KB Clinician Review Checklist

**Purpose**: `references/methodology/disease-definition-knowledge-base.json` is consumed by `cohort_definition_gate`, `definition_variable_guard`, and `feature_lineage_gate` as ground truth for flagging definition-variable leakage. The per-disease variable lists were LLM-compiled against the Torralbo 2025 / Eastwood 2016 methodology; they have **not** been individually clinician-verified for this KB version.

Each disease entry now carries a `provenance` block with `clinician_review_status: "pending"`. Downstream gates emit `[KB entry is LLM-compiled and not yet clinician-reviewed]` in issue messages so users can arbitrate false positives. Flipping `clinician_review_status` to `"clinician_reviewed"` (see bottom) removes the hint.

## Checklist per disease

For each of the 11 diseases, a clinician should verify:

1. **ICD-10 codes** — complete for diagnosis? Any subtypes missing?
2. **ICD-9-CM codes** (if present) — still relevant for the target EHR era?
3. **Lab criteria** — thresholds match current ADA / KDIGO / ACC-AHA guidelines? Units correct?
4. **Medications** — at least one agent per drug class? Any recently-approved drugs missing (e.g., semaglutide, empagliflozin for diabetes)?
5. **ATC codes** — correct hierarchy level?
6. **Self-report fields** — plausible for a typical EHR / biobank?
7. **Exclusions** — secondary / atypical forms correctly excluded?
8. **`definition_variables_to_exclude`** — the **most safety-critical field**. These are exactly the columns that, if present as features, constitute definition-variable leakage. Missing an entry here causes a false-negative (leakage not caught). Adding a clinically irrelevant entry causes false positives.

## Review log template

When a clinician reviews an entry, edit the disease's `provenance` block in `disease-definition-knowledge-base.json`:

```json
"provenance": {
  "source": "clinician_reviewed",
  "description": "Reviewed against ADA 2024 Standards of Care and KDIGO 2024 CKD guideline.",
  "clinician_review_status": "clinician_reviewed",
  "last_reviewed": "2026-MM-DD",
  "reviewer": "Dr. <name>, MD, <specialty>",
  "review_checklist": "references/methodology/DISEASE_KB_REVIEW.md"
}
```

Additionally, append a short note to this file under the appropriate disease section below.

---

## Diseases to review

### 1. type_2_diabetes
- Status: pending
- Notes: —

### 2. hypertension
- Status: pending
- Notes: —

### 3. coronary_heart_disease
- Status: pending
- Notes: —

### 4. chronic_kidney_disease
- Status: pending
- Notes: —

### 5. heart_failure
- Status: pending
- Notes: —

### 6. stroke
- Status: pending
- Notes: —

### 7. copd
- Status: pending
- Notes: —

### 8. major_depressive_disorder
- Status: pending
- Notes: —

### 9. cancer_any
- Status: pending
- Notes: —

### 10. atrial_fibrillation
- Status: pending
- Notes: —

### 11. readmission_30day
- Status: pending
- Notes: —
