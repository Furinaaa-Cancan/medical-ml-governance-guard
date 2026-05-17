# W23-A5: NCPR v2 extra-candidate scan (reviewer reports outside KB)

Read-only audit. Question: how many peer-review PDFs sit on disk but are NOT in
`peer-review-kb.json` (335 entries, 331 unique pdfs referenced)? Could KB
expansion unblock multi-journal NCPR v2 stratification?

## Inventory: PDFs on disk vs KB

| Journal             | Reviewer PDFs on disk | Already in KB | **Gap (uncurated)** |
|---------------------|----------------------:|--------------:|--------------------:|
| nature_communications |                 286 |           248 |              **38** |
| communications_medicine |               82 |            82 |               **0** |
| nature_medicine       |                   0 |             0 |                   0 |
| npj_digital_medicine  |                   0 |             0 |                   0 |
| jama                  |                   0 |             0 |                   0 |
| lancet_digital_health |                   0 |             0 |                   0 |
| bmj                   |                   0 |             0 |                   0 |
| specialist_journals   |                   0 |             0 |                   0 |
| **Total**             |             **368** |       **330** |              **38** |

Method: match basename + strip `^PR-\d+_` prefix used by KB rename pass. Cross
checked: 1 KB-referenced PDF is missing from disk (`s43856-026-01417-9_peer_review.pdf`).

## Domain breakdown of the 38 NC gap PDFs

| Domain              | Count | Sample papers                                            |
|---------------------|------:|----------------------------------------------------------|
| Oncology            |    12 | NC_pancreatic_cfDNA, NC_NSCLC_immunotherapy, NC_melanoma_XAI, 105_cancer_early_diagnosis |
| Sepsis/ICU          |     4 | 04_AI_sepsis, 17_ICU_acuity, NC_sepsis_XAI_coagulation, NC_sepsis_management |
| Cardio              |     4 | NC_HFpEF_AI_validation, NC_AF_biomarker, NC_cardiac_CT_mortality, 18_cardiac_signals_DL |
| Neuro / AD          |     4 | NC_AD_tau_prediction, NC_gait_freezing, NC_microbiome_parkinson, CM_dementia_mortality |
| Infection           |     4 | NC_COVID_auto_updating, NC_HBV_liver_failure, NC_ILD_diagnosis, NC_mpox_ML |
| Metabolic / repro   |     5 | NC_gestational_diabetes, NC_IVF_live_birth, NC_drug_efficacy_organoid, NC_plasma_future_health, NC_wearable_frailty |
| Kidney/Liver        |     1 | NC_CKD_retinal_screening                                 |
| Wearables           |     1 | 110_wearable_deterioration                               |
| Multimodal / other  |     3 | 107_InfEHR, NC_microbiome_disease, CM_ML_clinical_usefulness |

Median size 1985 KB, range 76 KB - 6716 KB. None are placeholder stubs;
all carry real reviewer content. Full list at `/tmp/W23_A5_true_gap.txt`.

## Multi-journal stratification unblock check

NCPR v2 target: ≥5 BOTH-quality candidates per journal across 6 journals
(NC, CM, NM, npjDM, JAMA, LDH) for stratification.

Extracting all 38 gap PDFs would change the picture by exactly ZERO journals.
The gap is 100% inside Nature Communications — the journal where KB is
already strongest (248 entries, more than enough for v2). The 6 underrepresented
journals all sit at 0 PDFs on disk; KB extraction cannot manufacture them.

What unblocks 6-journal stratification is **PDF acquisition**, not extraction.

## Effort estimate

| Path                                                  | Estimate                       |
|-------------------------------------------------------|--------------------------------|
| Manual extraction (clinician-reviewed), per paper     | ~30 min                        |
| 38 NC papers, manual                                  | ~19 h                          |
| Extraction-agent wave (cf. W22 wave: 49 papers, 368 concerns, 98.5% QC pass) | ~3-4 h orchestration + 1 audit pass |
| PDF acquisition for NM/npjDM/JAMA/LDH/BMJ/specialist  | open-ended; reviewer PDFs are journal-paywalled and not uniformly available |

## Verdict

**W24 should NOT do KB expansion before NCPR v2.** The 38 extractable papers
are all in NC, the one journal already saturated. They would deepen, not widen,
KB coverage. Multi-journal v3 is gated on PDF acquisition (an outside-the-repo
sourcing task), not on extraction throughput.

Recommendation:
1. Ship **NC-only NCPR v2** (per ADR-0006 staged in working tree) — the
   honest scope given disk reality.
2. Run a small (~10-paper) extraction wave on the 38 NC gap PDFs only if
   power analysis shows we need it; otherwise defer.
3. Treat the 0-PDF journals as a separate **acquisition workstream** with its
   own ADR — extraction agents cannot help here.
