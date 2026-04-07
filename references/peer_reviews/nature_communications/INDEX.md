# Transparent Peer Review Files — Medical ML Prediction

32 篇经验证的同行评审文件，来自 Nature Communications 和 Communications Medicine。
每篇已自动验证：(1) 确实含审稿人意见 (2) 论文是医学/临床 ML 预测。

## 文件列表

### Nature Communications — 临床预测模型（EHR / 结构化数据）

| 文件 | 论文 | DOI |
|------|------|-----|
| `02_osteoarthritis_risk_ML` | Predictive risk biomarkers for osteoarthritis (UK Biobank, SHAP) | s41467-024-46663-4 |
| `03_TransformEHR` | Transformer for disease outcome prediction from EHR | s41467-023-43715-z |
| `04_AI_sepsis_prediction` | AI in sepsis early prediction using unstructured data | s41467-021-20910-4 |
| `17_ICU_acuity_realtime` | Real-time ICU patient acuity prediction (state-space) | s41467-025-62121-1 |
| `23_AKI_outcomes_prediction` | Predicting in-hospital outcomes in acute kidney injury | s41467-023-39474-6 |
| `26_CAD_ML_diagnosis` | ML enhancing coronary artery disease functional diagnosis | s41467-024-49390-y |
| `43_synthetic_EHR_HALO` | Synthesize longitudinal EHR via hierarchical autoregressive model | s41467-023-41093-0 |
| `NC_cancer_diagnosis_prediction` | Prediction algorithms for early diagnosis of 15 cancer types | s41467-025-57990-5 |
| `NC_CKD_retinal_screening` | CKD screening and pathological type identification from retinal images | s41467-025-62273-0 |
| `NC_prehospital_trauma_AI` | Prehospital real-time AI trauma mortality (multi-national validation) | s41467-025-68198-y |

### Nature Communications — 癌症预后 / 诊断

| 文件 | 论文 | DOI |
|------|------|-----|
| `08_biology_guided_DL_cancer` | Biology-guided DL predicts prognosis and immunotherapy response | s41467-023-40890-x |
| `09_colorectal_cancer_survival` | Pathologic + genetic + lifestyle integration for CRC survival | s41467-024-47204-9 |
| `11_ovarian_cancer_interpretable` | Interpretable multimodal model for ovarian cancer diagnosis | s41467-024-46700-2 |
| `42_cancer_NLP_EHR` | Shareable AI to extract cancer outcomes from EHR | s41467-024-54071-x |
| `53_radiogenomics_breast` | Radiogenomic signatures for breast cancer heterogeneity | s41467-020-18703-2 |
| `64_thyroid_multimodal_DL` | Explainable multimodal DL for thyroid cancer LN metastasis | s41467-025-62042-z |
| `65_lung_cancer_multimodal` | Multimodal multitask foundation model for lung cancer screening | s41467-025-56822-w |
| `66_breast_cancer_multimodal` | Multimodal histopathologic models stratify HR+ breast cancer | s41467-025-57283-x |

### Nature Communications — COVID-19 / 感染 / 其他疾病

| 文件 | 论文 | DOI |
|------|------|-----|
| `27_COVID_mortality_ML` | ML model for COVID-19 in-hospital mortality (15 centers) | s41467-024-47557-1 |
| `38_COVID_immunophenotype_ML` | COVID-19 stratification by immuno-phenotyping and ML | s41467-022-28621-0 |
| `12_plasma_proteomics_AIDS` | Targeted plasma proteomics for organ damage in HIV | s41467-025-59242-y |
| `18_cardiac_signals_DL` | Clinical DL framework for continually learning from cardiac signals | s41467-021-24483-0 |
| `41_ALS_wearable_ML` | At-home wearables and ML capture ALS disease progression | s41467-023-40917-3 |

### Nature Communications — 多基因风险评分 / 基础模型

| 文件 | 论文 | DOI |
|------|------|-----|
| `56_multi_ancestry_PRS` | Ensemble penalized regression for multi-ancestry PRS | s41467-024-47357-7 |
| `57_PRS_tuning_GWAS` | Tuning PRS parameters using GWAS summary statistics | s41467-023-44009-0 |
| `58_PRS_utility_hospital` | Utility of polygenic scores across diverse diseases | s41467-024-47472-5 |
| `69_cross_ancestry_PRS` | Quantifying portable genetic effects, cross-ancestry prediction | s41467-023-36544-7 |
| `61_pathology_foundation_benchmark` | Clinical benchmark of self-supervised pathology foundation models | s41467-025-58796-1 |

### Communications Medicine — 临床 ML 预测

| 文件 | 论文 | DOI |
|------|------|-----|
| `CM_dementia_mortality_ML` | ML models identify predictive features of patient mortality across dementia types | s43856-024-00437-7 |
| `CM_ICU_48h_mortality_ML` | Interpretable ML for dynamic 48-hour mortality prediction during ICU stay | s43856-025-01192-z |
| `CM_stroke_outcome_ML` | ML for early dynamic prediction of functional outcome after stroke | s43856-024-00666-w |
| `CM_ML_clinical_usefulness` | Methodological choices and clinical usefulness for ML outcome predictions | s43856-024-00626-4 |

## 验证方法

每个 PDF 经过自动化两步验证：
1. 提取前 2 页文本，确认含 "Reviewer" / "Remarks to the Author" / "Peer Review File"
2. 确认文本同时包含医学关键词（clinical/patient/disease/mortality/...）和 ML 关键词（prediction/model/training/AUROC/...）

不合格文件（supplementary data、reporting summary、非医学、非 ML）已删除。

## 来源

- **Nature Communications**: 2016 年起强制透明同行评审
- **Communications Medicine**: 全部文章公开 peer review
- **Nature Medicine / Nature Machine Intelligence / Nature 主刊**: 2025 年 6 月起才开始，之前的论文没有公开 peer review file
