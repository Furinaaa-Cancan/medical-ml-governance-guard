# Corpus Statistics: peer-review-kb.json

**Source file:** `references/case-studies/peer-review-kb.json`
**Contract:** `peer_review_kb.v1`
**Computed:** 2026-05-10
**Note:** All counts are computed live from the KB. Frequency tables and IDs only — no titles, abstracts, or reviewer text.

---

## 1. Top-Line Counts

| Field | Value |
|---|---|
| total_papers (header) | 335 |
| total_concerns (header) | 449 |
| active entries (live count) | 335 |
| quarantined | 1 (`PR-040`) |

### 1.1 By source layer

| Layer | ID pattern | Count |
|---|---|---|
| Original manually curated | `PR-NNN` (excl. PR-040) | 111 |
| Reporting-summary-only | `PR-RO-NN` | 7 |
| OpenAlex-discovered | `PR-EXP-NNNN` | 217 |
| Quarantined (excluded) | `PR-040` | 1 |
| **Active total** | | **335** |

Manually curated layer total: 111 + 7 = **118**.

---

## 2. By Journal

| Journal | Count | Year range | n_with_sample_size | Median sample_size |
|---|---:|---|---:|---:|
| Nature Communications | 248 | 2020–2026 | 116 | 5,183 |
| Communications Medicine | 87 | 2021–2026 | 35 | 1,033 |

Only two journals are present. The OpenAlex discovery pass did not retrieve papers from BMJ EBM, Lancet Digital Health, npj Digital Medicine, JAMA, or Nature Medicine despite directory scaffolding existing for these venues.

### 2.1 Sample-size summary (all entries with sample_size > 0)

| Statistic | Value |
|---|---:|
| n filled | 151 / 335 (45%) |
| min | 19 |
| p25 | 511 |
| median | 4,645 |
| p75 | 40,643 |
| max | 37,000,000 |

---

## 3. By Year of Publication

### 3.1 Distribution

| Year | Count |
|---:|---:|
| 2020 | 24 |
| 2021 | 39 |
| 2022 | 26 |
| 2023 | 50 |
| 2024 | 71 |
| 2025 | 101 |
| 2026 | 24 |
| **Total** | **335** |

### 3.2 Per-year split by source layer

| Year | PR-orig | PR-RO | PR-EXP | Total |
|---:|---:|---:|---:|---:|
| 2020 | 2 | 0 | 22 | 24 |
| 2021 | 1 | 0 | 38 | 39 |
| 2022 | 5 | 0 | 21 | 26 |
| 2023 | 19 | 0 | 31 | 50 |
| 2024 | 28 | 0 | 43 | 71 |
| 2025 | 53 | 6 | 42 | 101 |
| 2026 | 3 | 1 | 20 | 24 |

The OpenAlex discovery pass back-filled the 2020–2022 era (where original curation was sparse), giving the corpus more uniform temporal coverage. 2025 is the modal year (101 papers).

---

## 4. By data_type

### 4.1 Top-15 data_type labels (whole corpus)

| Rank | data_type | Count |
|---:|---|---:|
| 1 | clinical_tabular | 59 |
| 2 | pending_metadata_extraction | 21 |
| 3 | histopathology_wsi | 17 |
| 4 | ct_imaging_plus_clinical | 11 |
| 5 | clinical_notes_nlp | 10 |
| 6 | mri_multiparametric | 9 |
| 7 | ehr_tabular_clinical | 8 |
| 8 | transcriptomic_plus_clinical | 7 |
| 9 | gwas_summary_statistics | 6 |
| 10 | ehr_tabular | 6 |
| 11 | genomic_amr | 6 |
| 12 | histopathology_wsi_plus_clinical | 5 |
| 13 | genetic_plus_clinical_biomarkers | 5 |
| 14 | ehr | 5 |
| 15 | tabular_clinical_multiomics | 4 |

### 4.2 Cardinality (unique label count)

| Source | Unique labels | Entries |
|---|---:|---:|
| PR-orig | 97 | 111 |
| PR-RO | 6 | 7 |
| PR-EXP | 61 | 217 |
| Combined | 110 | 335 |

The PR-orig layer is highly heterogeneous (97 unique labels across 111 entries — most are one-of-a-kind). The PR-EXP layer is more concentrated (top label `clinical_tabular` covers 26% of PR-EXP).

### 4.3 Special metadata states

| State | Count | IDs (sample) |
|---|---:|---|
| `data_type == 'pending_metadata_extraction'` | 21 | All in PR-EXP layer |
| `metadata_source == 'abstract_only'` | 2 | PR-RO-01, PR-RO-02 |
| `_pdf_status == 'corrupt_needs_redownload'` | 4 | PR-EXP-0007, PR-EXP-0044, PR-EXP-0080, PR-EXP-0150 |
| `out_of_scope_reason == 'not_medical_ml'` | 15 | (see §6.3) |

The `pending_metadata_extraction` count of 21 is the residual after the audit; these are PR-EXP entries the audit could not classify.

---

## 5. mlgg Scope Filter

The `is_cohort_retrospective_binary` field was added by the 5-agent audit and only populated for the 217 PR-EXP entries. PR-orig and PR-RO layers do not yet have this field.

### 5.1 Field coverage

| Layer | Field present | true | false | missing |
|---|---:|---:|---:|---:|
| PR-orig | 0 | – | – | 111 |
| PR-RO | 0 | – | – | 7 |
| PR-EXP | 217 | 125 | 92 | 0 |
| **Total** | **217** | **125** | **92** | **118** |

### 5.2 In-scope filter chain (PR-EXP only)

| Filter | Count |
|---|---:|
| `is_cohort_retrospective_binary == true` | 125 |
| AND `peer_review_pdf_path` set | 125 |
| AND `primary_repo` populated | pending Agent B output |

All 125 in-scope PR-EXP entries have a peer-review PDF path (no PDF gaps within the in-scope subset).

---

## 6. Audit Findings (PR-EXP, n=217)

### 6.1 Confidence distribution

| confidence | Count | % |
|---|---:|---:|
| high | 144 | 66.4% |
| medium | 57 | 26.3% |
| low | 16 | 7.4% |

### 6.2 Anomaly-flag distribution

| anomaly_flag | Count |
|---|---:|
| title_does_not_match_pdf | 26 |
| topic_not_medical_ml | 15 |
| pdf_corrupt_or_empty | 6 |
| pdf_not_peer_review | 1 |
| paper_already_in_kb_under_other_id | 0 |

Number of flags per entry:

| flags per entry | Count |
|---:|---:|
| 0 | 175 |
| 1 | 36 |
| 2 | 6 |

The 6 doubly-flagged entries: PR-EXP-0134, -0136, -0140, -0156, -0162 (`topic_not_medical_ml` + `title_does_not_match_pdf`); PR-EXP-0217 (`pdf_not_peer_review` + `topic_not_medical_ml`).

### 6.3 Corrupt-PDF IDs (n=6)

`PR-EXP-0007`, `PR-EXP-0044`, `PR-EXP-0080`, `PR-EXP-0150`, `PR-EXP-0188`, `PR-EXP-0190`

(Note: only 4 of these have `_pdf_status == 'corrupt_needs_redownload'` set as a top-level field; the other 2 are flagged via `audit_findings.anomaly_flags` only. The two markers are inconsistent.)

### 6.4 Out-of-scope (`topic_not_medical_ml`) IDs (n=15)

`PR-EXP-0091`, `PR-EXP-0133`, `PR-EXP-0134`, `PR-EXP-0136`, `PR-EXP-0138`, `PR-EXP-0140`, `PR-EXP-0156`, `PR-EXP-0162`, `PR-EXP-0177`, `PR-EXP-0180`, `PR-EXP-0183`, `PR-EXP-0199`, `PR-EXP-0215`, `PR-EXP-0216`, `PR-EXP-0217`

These match the 15 entries with `out_of_scope_reason == 'not_medical_ml'` (consistent).

### 6.5 Title-mismatch IDs (n=26)

`PR-EXP-0124`, `PR-EXP-0134`, `PR-EXP-0136`, `PR-EXP-0137`, `PR-EXP-0139`, `PR-EXP-0140`, `PR-EXP-0151`, `PR-EXP-0153`, `PR-EXP-0154`, `PR-EXP-0155`, `PR-EXP-0156`, `PR-EXP-0157`, `PR-EXP-0158`, `PR-EXP-0159`, `PR-EXP-0162`, `PR-EXP-0163`, `PR-EXP-0164`, `PR-EXP-0165`, `PR-EXP-0166`, `PR-EXP-0167`, `PR-EXP-0168`, `PR-EXP-0169`, `PR-EXP-0170`, `PR-EXP-0173`, `PR-EXP-0174`, `PR-EXP-0175`

24 of 26 fall in the PR-EXP-0151..0175 range (chunk 4) — a localized PDF/title-mapping problem.

---

## 7. Cross-Chunk Consistency Check

The 5 audit agents each handled ~44 PR-EXP entries. We test whether their `is_cohort_retrospective_binary` decisions are mutually consistent.

### 7.1 Per-chunk summary

| Chunk | ID range | n | true | false | %true | Journal mix | Year range |
|---|---|---:|---:|---:|---:|---|---|
| 1 | 0001–0044 | 44 | 4 | 40 | **9.1%** | CommMed only | 2024–2026 |
| 2 | 0045–0088 | 44 | 33 | 11 | 75.0% | CommMed 39 / NC 5 | 2021–2026 |
| 3 | 0089–0132 | 44 | 39 | 5 | 88.6% | NC only | 2023–2025 |
| 4 | 0133–0176 | 44 | 26 | 18 | 59.1% | NC only | 2021–2023 |
| 5 | 0177–0217 | 41 | 23 | 18 | 56.1% | NC only | 2020–2021 |

Range: **9.1% – 88.6% (gap = 79.5 percentage points)** — exceeds the 30-pp audit-quality threshold.

### 7.2 Year-controlled comparison (2025 only)

| Chunk | 2025 n | 2025 true | 2025 %true |
|---|---:|---:|---:|
| 1 | 23 | 1 | 4.3% |
| 2 | 1 | 0 | 0.0% |
| 3 | 18 | 13 | 72.2% |

Restricting to a single publication year, chunk 1 still labels only 4.3% true vs chunk 3's 72.2%. The skew is not explained by year drift alone — it points to a **labeling-rubric divergence between agents** (or a journal-driven content shift between CommMed and NC). See §10 for discussion.

### 7.3 Audit confidence by chunk

| Chunk | high | medium | low |
|---|---:|---:|---:|
| 1 | 42 | 0 | 2 |
| 2 | 39 | 4 | 1 |
| 3 | 33 | 11 | 0 |
| 4 | 19 | 15 | 10 |
| 5 | 11 | 27 | 3 |

Chunks 4 and 5 (NC 2020–2023) have substantially more medium/low confidence calls — older PDFs with less consistent peer-review formatting.

### 7.4 PR-EXP cohort=true rate by year

| Year | n | true | %true |
|---:|---:|---:|---:|
| 2020 | 22 | 15 | 68.2% |
| 2021 | 38 | 20 | 52.6% |
| 2022 | 21 | 17 | 81.0% |
| 2023 | 31 | 22 | 71.0% |
| 2024 | 43 | 32 | 74.4% |
| 2025 | 42 | 14 | 33.3% |
| 2026 | 20 | 5 | 25.0% |

A sharp drop in cohort_retrospective rate at 2025–2026 (25–33% vs ~70% prior) is partially confounded with chunk 1 (which holds most of the 2025–26 CommMed papers).

---

## 8. TRIPOD+AI / PROBAST+AI Trustable Subset

The "Fig 4 confusion matrix" subset = `is_cohort_retrospective_binary == true` AND `len(reviewer_concerns) > 0`.

| Filter | Count |
|---|---:|
| `is_cohort_retrospective_binary == true` (PR-EXP only) | 125 |
| `len(reviewer_concerns) > 0` (PR-orig only) | 105 |
| **Intersection** | **0** |

The two attributes have **disjoint coverage by design**: only PR-EXP have the binary scope tag; only PR-orig have reviewer-concern records. To populate Fig 4, one of the following must happen:

1. Back-port `is_cohort_retrospective_binary` to the 105 PR-orig entries with reviewer_concerns (recommended; cheap).
2. Forward-port reviewer_concern extraction to the 125 in-scope PR-EXP entries (expensive; full-PDF re-parse).

### 8.1 Reviewer concerns / strengths counts by source

| Source | Entries with concerns | Total concerns | Total strengths |
|---|---:|---:|---:|
| PR-orig | 105 | 449 | 97 |
| PR-RO | 0 | 0 | 0 |
| PR-EXP | 0 | 0 | 0 |
| **Total** | **105** | **449** | **97** |

---

## 9. Quarantine Record

| field | value |
|---|---|
| removed_id | PR-040 |
| reason summary | Title contained explicit `(inferred from PDF content)` marker; DOI resolved to an unrelated genome paper. Title appears fabricated. |
| pdf path | `references/case-studies/_quarantine/PR-040_sepsis_management_prediction_model_infer_peer_review.pdf` |
| removed_at_utc | 2026-05-10T01:50:31Z |

---

## 10. Findings Worth a Discussion Bullet in the Paper

1. **Chunk 1 vs Chunk 3 cohort-rate gap is a real audit-rubric divergence, not just sample skew.** Year-controlled (2025-only): chunk 1 = 4.3% true, chunk 3 = 72.2% true. The two chunks differ in journal (CommMed vs NC) and in agent worker. Either (a) CommMed 2025 papers genuinely lean prospective/cross-sectional, or (b) the chunk-1 agent applied a stricter "retrospective cohort" definition than chunk 3. Recommend re-spotting ~10 chunk-1 false-labels by hand before publishing the 125-entry in-scope number.

2. **Two different markers for "corrupt PDF" disagree (4 vs 6).** `_pdf_status == 'corrupt_needs_redownload'` is set on 4 entries (0007, 0044, 0080, 0150), but `audit_findings.anomaly_flags` includes `pdf_corrupt_or_empty` for 6 entries (adds 0188, 0190). Recommend reconciling so one canonical field is used.

3. **OpenAlex discovery did not reach the planned non-Nature venues.** Despite directory scaffolding for BMJ, Lancet Digital Health, npj Digital Medicine, JAMA, and Nature Medicine, the 217-entry PR-EXP layer is 100% Nature Communications (143) + Communications Medicine (74). This is a coverage limitation worth disclosing in Methods.

4. **Title-mismatch flags are localized to chunk 4 (PR-EXP-0151..0175).** 24 of 26 `title_does_not_match_pdf` flags are in this 25-entry range — suggests a systematic OpenAlex-to-PDF-filename mapping bug for that batch, not a general data-quality issue.

5. **Fig 4 confusion matrix is currently empty.** PR-orig has reviewer concerns but no scope tag; PR-EXP has scope tag but no reviewer concerns. Need to back-port `is_cohort_retrospective_binary` to the 105 PR-orig-with-concerns (cheap) before Fig 4 can be computed.

6. **2025–2026 cohort-rate drop (33% / 25%) is partially confounded by chunk 1.** The apparent year trend may dissolve after the chunk-1 re-audit recommended in finding #1.

7. **PR-orig data_type vocabulary is highly heterogeneous (97 unique labels for 111 entries).** Most labels are one-of-a-kind. A controlled vocabulary or hierarchical schema would make cross-cutting analyses (e.g., "all imaging papers", "all genomic papers") tractable.

8. **The 21 `pending_metadata_extraction` entries are a known-known.** They are PR-EXP entries the audit could not classify (likely PDF parse failures or non-English content). They should either be re-attempted with a fresh extraction pass or marked excluded.
