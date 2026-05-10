# 10-agent wave KB merge — DRY RUN report

Generated: 2026-05-10T07:02:00+00:00

KB entries: 335

Entries to be modified: 59
Entries referenced but missing in KB: 0

## A1 — chunk 1 cohort-binary flips

| ID | from | to | evidence |
|---|---|---|---|
| PR-EXP-0001 | `False` | `True` | PDF p.1-2 describes retrospective VHA EHR analysis with cases (AD-onset) vs controls; bina |
| PR-EXP-0004 | `False` | `True` | PDF p.1 describes wearable PPG-based binary CVD screening in PWH (CVD vs non-CVD reference |
| PR-EXP-0010 | `False` | `True` | PDF p.1 explicitly states binary classification (benign vs malignant) on retrospective mul |
| PR-EXP-0012 | `False` | `True` | PDF p.2 explicitly raises binary class outcome (rejection vs no rejection) for kidney fail |
| PR-EXP-0020 | `False` | `True` | PDF p.1-2 describes pretrained EHR transformer for binary ADE prediction (event vs no even |
| PR-EXP-0026 | `False` | `True` | PDF p.1-2 describes binary classification of acute vs chronic TMD using LR vs MLP on cohor |
| PR-EXP-0027 | `False` | `True` | PDF p.1-2 describes update of POSS prediction model for postoperative shoulder stiffness y |
| PR-EXP-0028 | `False` | `True` | PDF p.1 describes AutoML on preoperative CT for binary classification of inverted papillom |
| PR-EXP-0029 | `False` | `True` | PDF p.1-2 describes 10-year MI risk prediction (binary endpoint) using LR/NN with PRS+EHR  |
| PR-EXP-0031 | `False` | `True` | PDF p.1-2 describes binary classifier (post-screening positive vs negative oral exam) via  |
| PR-EXP-0033 | `False` | `True` | PDF p.1-2 describes AI model on H&E WSI biopsies producing cancer probability score (cance |
| PR-EXP-0035 | `False` | `True` | PDF p.1 describes CNN with adversarial ancestry adjustment for binary T2D case-control cla |

## A8 — clear title_does_not_match_pdf flag

| ID | evidence |
|---|---|
| PR-EXP-0134 | DOI suffix matches PDF filename; 10 of 10 distinctive title tokens appear in first 5 PDF p |
| PR-EXP-0136 | DOI suffix matches PDF filename; 10 of 10 distinctive title tokens appear in first 5 PDF p |
| PR-EXP-0137 | DOI suffix matches PDF filename; 7 of 7 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0139 | DOI suffix matches PDF filename; 10 of 10 distinctive title tokens appear in first 5 PDF p |
| PR-EXP-0140 | DOI suffix matches PDF filename; 7 of 7 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0151 | DOI suffix matches PDF filename; 12 of 12 distinctive title tokens appear in first 5 PDF p |
| PR-EXP-0153 | DOI suffix matches PDF filename; 9 of 9 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0154 | DOI suffix matches PDF filename; 9 of 9 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0155 | DOI suffix matches PDF filename; 12 of 12 distinctive title tokens appear in first 5 PDF p |
| PR-EXP-0156 | DOI suffix matches PDF filename; 8 of 8 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0157 | DOI suffix matches PDF filename; 9 of 9 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0158 | DOI suffix matches PDF filename; 8 of 8 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0159 | DOI suffix matches PDF filename; 12 of 12 distinctive title tokens appear in first 5 PDF p |
| PR-EXP-0162 | DOI suffix matches PDF filename; 7 of 7 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0163 | DOI suffix matches PDF filename; 8 of 8 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0164 | DOI suffix matches PDF filename; 10 of 11 distinctive title tokens appear in first 5 PDF p |
| PR-EXP-0165 | DOI suffix matches PDF filename; 7 of 7 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0166 | DOI suffix matches PDF filename; 7 of 8 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0167 | DOI suffix matches PDF filename; 6 of 9 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0168 | DOI suffix matches PDF filename; 7 of 10 distinctive title tokens appear in first 5 PDF pa |
| PR-EXP-0169 | DOI suffix matches PDF filename; 7 of 9 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0170 | DOI suffix matches PDF filename; 8 of 10 distinctive title tokens appear in first 5 PDF pa |
| PR-EXP-0173 | DOI suffix matches PDF filename; 5 of 11 distinctive title tokens appear in first 5 PDF pa |
| PR-EXP-0174 | DOI suffix matches PDF filename; 9 of 9 distinctive title tokens appear in first 5 PDF pag |
| PR-EXP-0175 | DOI suffix matches PDF filename; 7 of 8 distinctive title tokens appear in first 5 PDF pag |

## A9 — backfill (data_type / prediction_task / confidence)


### PR-EXP-0007
- **data_type**: `clinical_tabular` → `mri_plus_clinical_plus_neuropsych`
- **prediction_task**: `neurocognitive score inference` → `Neurocognitive testing score inference for adolescents and young adults with con`
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0044
- **data_type**: `clinical_tabular` → `ecg_time_series_plus_clinical`
- **prediction_task**: `arrhythmia classification` → `Multi-label arrhythmia classification from 12-lead ECG recordings`
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0080
- **prediction_task**: `Interpretable all-cause mortality prediction from clinical features` → `All-cause mortality prediction over 1-, 3-, 5-, and 10-year horizons from popula`
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0091
- **data_type**: `pending_metadata_extraction` → `molecular_crystal_structure` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Crystal structure prediction for small molecule drug development` → `Polymorph crystal-structure prediction for small-molecule pharmaceutical compoun`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0133
- **data_type**: `pending_metadata_extraction` → `protein_3d_structure` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Protein-protein binding interface prediction from 3D protein structure` → `Per-residue protein binding-interface prediction from 3D atomic coordinates`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0134
- **data_type**: `pending_metadata_extraction` → `protein_sequence` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Antibody 3D structure prediction from sequence using deep learning` → `Antibody backbone 3D structure prediction from amino-acid sequence`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0136
- **data_type**: `pending_metadata_extraction` → `industrial_time_series` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Lithium-ion battery state-of-health estimation from operational data` → `Lithium-ion battery state-of-health estimation from operational cycling time-ser`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0137
- **data_type**: `spatial_transcriptomics_plus_he` → `single_cell_rnaseq_plus_imaging_mass_cytometry` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Cancer-associated fibroblast cell-type classification from single-cell and spati` → `Cancer-associated fibroblast phenotype classification from single-cell RNA-seq w`
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0138
- **data_type**: `pending_metadata_extraction` → `variant_pathogenicity_features` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Pathogenicity prediction of mitochondrial missense variants` → `Pathogenicity classification of mitochondrial missense variants from sequence/st`
- **audit_findings.confidence**: `medium` → `high`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0140
- **data_type**: `pending_metadata_extraction` → `small_molecule_chemical_descriptors` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Benchmarking of molecular property prediction models on small-molecule datasets` → `Benchmarking molecular property prediction across MoleculeNet, opioid, and liter`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0141
- **prediction_task**: `Fairness improvement methodology for image-based computer-aided diagnosis models` → `Group-fairness improvement methodology for image-based computer-aided diagnosis `
- **audit_findings.confidence**: `low` → `medium`

### PR-EXP-0142
- **data_type**: `imaging_plus_clinical` → `chest_xray_imaging`
- **prediction_task**: `Methodology for correcting acquisition-shift performance drift in medical image ` → `Unsupervised prediction-alignment correction for acquisition-shift drift in imag`
- **audit_findings.confidence**: `low` → `medium`

### PR-EXP-0143
- **data_type**: `histopathology_wsi` → `biomedical_microscopy_segmentation` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Biomedical image segmentation algorithm design via evolutionary computation` → `Few-shot biomedical image segmentation pipeline design via Cartesian genetic pro`
- **audit_findings.confidence**: `low` → `high`
- **out_of_scope_reason**: `None` → `non_cohort_binary_modality`

### PR-EXP-0150
- **data_type**: `pending_metadata_extraction` → `transcriptomic_plus_clinical`
- **prediction_task**: `Immunotherapy response prediction in cancer patients via network-based machine l` → `Immune-checkpoint-inhibitor response prediction across cancer types from tumor t`
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0151
- **data_type**: `genomic_amr` → `wgs_somatic_mutations` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Tissue-of-origin classification for cancer of unknown primary from genome-wide s` → `Tissue-of-origin classification for cancer of unknown primary from whole-genome `
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0156
- **data_type**: `pending_metadata_extraction` → `epidemiological_modeling`
- **prediction_task**: `Cancer etiology and risk evaluation via a tumor-evolution mathematical model` → `Mathematical-model-based estimation of cancer incidence variation across tissues`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0162
- **data_type**: `pending_metadata_extraction` → `rna_sequence` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `RNA secondary structure prediction with deep learning and thermodynamic priors` → `RNA secondary structure prediction from sequence using deep learning with thermo`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0163
- **prediction_task**: `Drug-repurposing candidate identification for Alzheimer's disease via machine le` → `Drug-repurposing candidate ranking for Alzheimer's disease via transcriptomic si`
- **audit_findings.confidence**: `low` → `medium`
- **out_of_scope_reason**: `None` → `non_cohort_binary_modality`

### PR-EXP-0165
- **data_type**: `mri_multiparametric` → `fmri_brain_networks` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Stimulus-independent and task-unrelated thought prediction from functional MRI b` → `Trial-by-trial stimulus-independent task-unrelated thought prediction from resti`
- **audit_findings.confidence**: `low` → `high`
- **out_of_scope_reason**: `None` → `non_cohort_binary_modality`

### PR-EXP-0169
- **data_type**: `biomarker_panel` → `methodology_multimodal_omics` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Permutation-based biomarker importance ranking for complex disease classificatio` → `Permutation-based feature-importance testing for biomarker discovery across mult`
- **audit_findings.confidence**: `low` → `medium`

### PR-EXP-0174
- **data_type**: `ehr_tabular_clinical` → `clinical_tabular`
- **prediction_task**: `Actionable treatment-plan recommendation from a surrogate Bayesian health-improv` → `Individualized treatment-plan recommendation to lower systolic blood pressure an`
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0177
- **data_type**: `pending_metadata_extraction` → `small_molecule_chemical_descriptors` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Molecular property prediction from chemical structure (drug discovery, non-cohor` → `Molecular property prediction from 3D-aware algebraic-graph and bidirectional tr`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0180
- **data_type**: `pending_metadata_extraction` → `preclinical_basic_biology` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Preclinical organoid model characterization for CNTNAP2-associated autism (basic` → `Mechanistic characterization of cortical overgrowth in CNTNAP2 forebrain organoi`
- **out_of_scope_reason**: `not_medical_ml` → `preclinical_basic_biology`

### PR-EXP-0183
- **data_type**: `pending_metadata_extraction` → `protein_sequence` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Per-residue intrinsic disorder and disorder-function prediction from protein seq` → `Per-residue intrinsic-disorder and disorder-function prediction from amino-acid `
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0184
- **data_type**: `pending_metadata_extraction` → `tcr_repertoire_sequence` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `TCR repertoire clustering and multi-disease repertoire classification by isometr` → `TCR repertoire clustering and multi-disease (cancer/infection/autoimmune) repert`
- **audit_findings.confidence**: `medium` → `high`

### PR-EXP-0188
- **data_type**: `pending_metadata_extraction` → `preclinical_basic_biology` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `pending_metadata_extraction` → `Self-assembling human heart organoid model for cardiac development and congenita`
- **audit_findings.confidence**: `low` → `high`
- **out_of_scope_reason**: `None` → `preclinical_basic_biology`

### PR-EXP-0190
- **data_type**: `pending_metadata_extraction` → `chest_xray_imaging`
- **prediction_task**: `pending_metadata_extraction` → `Bone mineral density estimation and FRAX-style fracture-risk assessment from pel`
- **audit_findings.confidence**: `low` → `high`

### PR-EXP-0195
- **data_type**: `pending_metadata_extraction` → `knowledge_graph_drug_target` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Drug-target interaction prediction from knowledge-graph and recommendation-syste` → `Drug-target interaction prediction via knowledge-graph embeddings combined with `
- **audit_findings.confidence**: `medium` → `high`
- **out_of_scope_reason**: `None` → `non_cohort_binary_modality`

### PR-EXP-0196
- **data_type**: `pending_metadata_extraction` → `wgs_somatic_mutations` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Classification of primary vs metastatic cancers using passenger mutation pattern` → `Primary vs metastatic cancer-type classification from genome-wide passenger muta`
- **audit_findings.confidence**: `medium` → `high`

### PR-EXP-0199
- **data_type**: `pending_metadata_extraction` → `mass_spectrometry_proteomics` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Spectral-library prediction for DIA mass spectrometry with empirically corrected` → `DIA mass-spectrometry spectral-library generation via predicted-then-empirically`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0213
- **data_type**: `pending_metadata_extraction` → `imaging_plus_clinical`
- **prediction_task**: `Confounder-free deep-learning training method evaluated on medical-imaging appli` → `Confounder-free deep-learning training methodology evaluated on HIV brain MRI, a`

### PR-EXP-0215
- **data_type**: `pending_metadata_extraction` → `transcriptomic_pharmacogenomic`
- **prediction_task**: `Pre-clinical drug combination dose-response prediction using a 5th-order tensor ` → `Drug-combination dose-response prediction in cancer cell lines via 5th-order ten`
- **out_of_scope_reason**: `not_medical_ml` → `non_cohort_binary_modality`

### PR-EXP-0217
- **data_type**: `pending_metadata_extraction` → `preclinical_basic_biology` ⚠️[NEW label]
- **_data_type_vocab_status**: `None` → `new_unreviewed`
- **prediction_task**: `Mechanistic biology of HSF1-dependent ECM remodeling in chronic-inflammation to ` → `Mechanistic study of HSF1-dependent ECM remodeling in mouse colitis-associated c`
- **audit_findings.confidence**: `low` → `high`
- **out_of_scope_reason**: `not_medical_ml` → `preclinical_basic_biology`

## ⚠️ Borderline — needs human ruling

| ID | issue |
|---|---|
| PR-EXP-0151 | A9 relabels data_type → `wgs_somatic_mutations` (omics) but keeps cohort_binary=true. Per CLAUDE.md mlgg does NOT cover omics regardless of classification head — recommend forcing cohort=false + out_of_scope=`omics_modality`. **DRY-RUN does NOT do this; needs human ruling.** |

## A9 — out-of-mlgg-scope marking

Entries with `is_cohort_retrospective_binary=false`. Per CLAUDE.md, mlgg covers retrospective cohort binary classification only — these do **not** drop from the KB but are marked for cohort-only analyses.

| ID | reason | data_type |
|---|---|---|
| PR-EXP-0091 | non_cohort_binary_modality | `molecular_crystal_structure` |
| PR-EXP-0133 | non_cohort_binary_modality | `protein_3d_structure` |
| PR-EXP-0134 | non_cohort_binary_modality | `protein_sequence` |
| PR-EXP-0136 | non_cohort_binary_modality | `industrial_time_series` |
| PR-EXP-0138 | non_cohort_binary_modality | `variant_pathogenicity_features` |
| PR-EXP-0140 | non_cohort_binary_modality | `small_molecule_chemical_descriptors` |
| PR-EXP-0143 | non_cohort_binary_modality | `biomedical_microscopy_segmentation` |
| PR-EXP-0156 | non_cohort_binary_modality | `epidemiological_modeling` |
| PR-EXP-0162 | non_cohort_binary_modality | `rna_sequence` |
| PR-EXP-0163 | non_cohort_binary_modality | `transcriptomic_pharmacogenomic` |
| PR-EXP-0165 | non_cohort_binary_modality | `fmri_brain_networks` |
| PR-EXP-0177 | non_cohort_binary_modality | `small_molecule_chemical_descriptors` |
| PR-EXP-0180 | preclinical_basic_biology | `preclinical_basic_biology` |
| PR-EXP-0183 | non_cohort_binary_modality | `protein_sequence` |
| PR-EXP-0188 | preclinical_basic_biology | `preclinical_basic_biology` |
| PR-EXP-0195 | non_cohort_binary_modality | `knowledge_graph_drug_target` |
| PR-EXP-0199 | non_cohort_binary_modality | `mass_spectrometry_proteomics` |
| PR-EXP-0215 | non_cohort_binary_modality | `transcriptomic_pharmacogenomic` |
| PR-EXP-0217 | preclinical_basic_biology | `preclinical_basic_biology` |

## Missing IDs (referenced by an agent but absent in KB)

_(none — all referenced IDs found in KB)_
