# mlgg-lint audit on 92-repo cohort-binary corpus (v1)

Generated: 2026-05-10T06:45:14.480635+00:00
Source corpus: `paper/code-repos-cohort-binary.json` (125 papers, 92 GitHub/GitLab targets after filter).

## Headline numbers

| Metric | Count |
|---|---:|
| Repos targeted (host ∈ github/gitlab) | 92 |
| Successfully cloned | 88 |
| Repos with Python or notebook files | 71 |
| Repos with ≥1 mlgg-lint finding | 48 |
| Total findings across corpus | 448 |

### Findings by severity

| Severity | Count |
|---|---:|
| warning | 215 |
| info | 123 |
| error | 110 |

## Top 15 most common rules (by paper count, ie how many papers fired)

| Rule | Papers | Total findings |
|---|---:|---:|
| `R009` | 26 | 83 |
| `R022` | 21 | 125 |
| `E000` | 15 | 56 |
| `R013` | 12 | 30 |
| `R016` | 11 | 31 |
| `R021` | 7 | 23 |
| `R008` | 7 | 13 |
| `R007` | 6 | 14 |
| `R019` | 5 | 6 |
| `R002` | 4 | 4 |
| `R004` | 3 | 5 |
| `R001` | 3 | 11 |
| `R018` | 3 | 3 |
| `R027` | 2 | 7 |
| `R020` | 2 | 7 |

## Per-paper detail

| ID | Repo (host/path) | Clone | Py | Nb | Findings | Top rules |
|---|---|---|---:|---:|---:|---|
| PR-EXP-0005 | `Kepler1647b/G-NECNet` | cloned | 38 | 0 | 1 | R022 |
| PR-EXP-0042 | `ecg-net/scd-oregon` | cloned | 16 | 0 | 0 |  |
| PR-EXP-0046 | `AIM-Harvard/DeepHeart` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0047 | `LARS-research/KnowDDI` | cloned | 24 | 0 | 2 | R009 |
| PR-EXP-0051 | `calvin-zcx/pasc_phenotype/tree/master/prediction` | cloned | 626 | 0 | 100 | R022, R009, R021 |
| PR-EXP-0057 | `ayin0510/JH-EPICS` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0058 | `Koinoue/bcf_hsct` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0059 | `ngiesa/TRAPOD` | cloned | 36 | 0 | 0 |  |
| PR-EXP-0060 | `shachar5020/TransformerMIL4ReceptorPrediction` | cloned | 32 | 0 | 2 | R022, R013 |
| PR-EXP-0061 | `akhilvaid/LeftHeartValvularDisease` | cloned | 6 | 0 | 9 | R027, R020, R009, R022 |
| PR-EXP-0063 | `xzhouai/NNP` | cloned | 0 | 2 | 0 |  |
| PR-EXP-0064 | `igormintz/cipro` | cloned | 10 | 0 | 8 | R021, R022, R016, R019 |
| PR-EXP-0065 | `gevaertlab/MultiModalBrainSurvival` | cloned | 44 | 0 | 4 | R009, R022 |
| PR-EXP-0066 | `ecg-net/CKDscreening` | cloned | 48 | 0 | 8 | R009, R022 |
| PR-EXP-0068 | `Google-Health/google-health/tree/master/colorectal_lymp` | cloned | 72 | 10 | 13 | R022, R009, R002, E000 |
| PR-EXP-0069 | `mensenyat/TNBC-ICI` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0071 | `Hongyang449/covid19_perception/tree/main/data` | cloned | 20 | 0 | 2 | E000 |
| PR-EXP-0072 | `lanagarmire/BC_imaging` | cloned | 16 | 44 | 8 | E000, R001 |
| PR-EXP-0073 | `kjakobse/risk-factors-associated-with-long-term-sick-le` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0079 | `hawaii-ai/tbdxa_mortality` | cloned | 20 | 8 | 1 | R022 |
| PR-EXP-0080 | `suinleelab/IMPACT` | cloned | 2 | 6 | 3 | R021, R009 |
| PR-EXP-0081 | `pirocv/xray_age` | cloned | 2 | 0 | 0 |  |
| PR-EXP-0084 | `Tongyue1999/Chinese-DDrtree` | cloned | 4 | 2 | 1 | E000 |
| PR-EXP-0085 | `andyvng/amr-gnn` | cloned | 24 | 0 | 0 |  |
| PR-EXP-0095 | `Rujinyu/HEROVision/tree/main` | cloned | 10 | 0 | 4 | R009, R022 |
| PR-EXP-0096 | `saraskim/abcd_otr` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0098 | `handeaydogan/slope-models-adpkd` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0099 | `aalto-ics-kepaco/survivalfm-analysis` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0100 | `chaoyi-wu/RadFM` | cloned | 76 | 0 | 0 |  |
| PR-EXP-0101 | `MonsterTea/MDKG` | cloned | 56 | 0 | 2 | E000, R008 |
| PR-EXP-0102 | `YixinChen-AI/MPUM` | cloned | 580 | 0 | 5 | R013, R016 |
| PR-EXP-0104 | `gingerbread000/LCTfound` | cloned | 82 | 0 | 1 | E000 |
| PR-EXP-0105 | `zocskl/RNFLTmetabolic-states-predict-CMD-outcomes` | clone_failed: Clon | 0 | 0 | 0 |  |
| PR-EXP-0107 | `fangdai-dear/QuasiParetoImprovement` | cloned | 26 | 0 | 3 | R022, E000 |
| PR-EXP-0108 | `CamDavidsonPilon/lifelines` | cloned | 138 | 32 | 10 | R007, R002, R021 |
| PR-EXP-0109 | `shuaih720/CHDdECG` | cloned | 22 | 0 | 0 |  |
| PR-EXP-0110 | `obi-ml-public/ECG-LV-Dysfunction` | cloned | 2 | 0 | 0 |  |
| PR-EXP-0111 | `tayebiarasteh/LLMmed` | cloned | 8 | 0 | 18 | R020, R014, R016, R013 |
| PR-EXP-0112 | `flatironhealth/SUDO` | cloned | 24 | 0 | 26 | R014, R022, R009, R013 |
| PR-EXP-0113 | `chenhcs/FRoGS` | cloned | 22 | 0 | 0 |  |
| PR-EXP-0114 | `mattrosenblatt7/leakage_neuroimaging` | cloned | 8 | 2 | 7 | R021, R016, E000 |
| PR-EXP-0116 | `dmmoon/PathoRICH` | cloned | 28 | 0 | 1 | R013 |
| PR-EXP-0117 | `dimiboeckaerts/PhageRBPdetection` | cloned | 18 | 10 | 20 | R013, R009, R016, R001 |
| PR-EXP-0118 | `jkznst/RetinaNet-mxnet` | cloned | 94 | 0 | 0 |  |
| PR-EXP-0119 | `JoshuaChou2018/SkinGPT-4` | cloned | 80 | 0 | 0 |  |
| PR-EXP-0121 | `yjdeng9/DeepMSProfiler` | cloned | 34 | 2 | 6 | R008, R009, R022 |
| PR-EXP-0122 | `Dyke-F/GPT-4V-In-Context-Learning` | cloned | 48 | 16 | 2 | R009 |
| PR-EXP-0123 | `google/bayesnf` | cloned | 24 | 4 | 2 | R016 |
| PR-EXP-0124 | `cykwilliams/GPT-3.5-Clinical-Recommendations-in-Emergen` | cloned | 10 | 0 | 3 | R009 |
| PR-EXP-0125 | `ncbi-nlp/TrialGPT/10.5281/zenodo.13270780` | clone_failed: Clon | 0 | 0 | 0 |  |
| PR-EXP-0127 | `yawwG/MRP` | cloned | 34 | 0 | 7 | R013, R022, R009 |
| PR-EXP-0128 | `arantir123/MCGLPPI` | cloned | 362 | 0 | 16 | R009, R016, E000, R007 |
| PR-EXP-0129 | `thidoiSanren/CNN_liver-cancer_Raman` | cloned | 8 | 0 | 0 |  |
| PR-EXP-0130 | `cjh-lab/NCOMMS_NSCLC_scFibs.git` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0131 | `shaankhurshid/lvmass_gwas` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0135 | `Artinto/Sample-to-answer_COVID-19` | clone_failed: Clon | 0 | 0 | 0 |  |
| PR-EXP-0139 | `gherrgo/eLB-Random-Forests.git` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0142 | `biomedia-mira/upa` | cloned | 8 | 4 | 10 | R016, R022, R009, R008 |
| PR-EXP-0144 | `zhongthoracic/DLNMS` | cloned | 10 | 0 | 0 |  |
| PR-EXP-0145 | `sdw95927/Ceograph` | cloned | 2 | 6 | 1 | E000 |
| PR-EXP-0146 | `sorgerlab/cycif` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0147 | `zhengjiewhu/MNALCI` | cloned | 16 | 0 | 0 |  |
| PR-EXP-0148 | `aetherAI/hms2` | cloned | 80 | 0 | 5 | R009, R022 |
| PR-EXP-0150 | `SBIlab/NetBio` | cloned | 30 | 0 | 25 | R021, R001, R016, R009 |
| PR-EXP-0151 | `UMCUGenetics/mutSigExtractor` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0152 | `papaemmelab/Tazi_NatureC_AML` | cloned | 0 | 10 | 4 | E000 |
| PR-EXP-0153 | `jamesdolezal/slideflow` | cloned | 384 | 0 | 3 | R013, R009 |
| PR-EXP-0155 | `amirlivne/PD-L1_predictor` | cloned | 6 | 0 | 0 |  |
| PR-EXP-0157 | `tensorflow/models/tree/master/research/object_detection` | cloned | 5000 | 138 | 40 | E000, R009, R013, R007 |
| PR-EXP-0159 | `owkin/scancovia` | cloned | 34 | 0 | 0 |  |
| PR-EXP-0160 | `d909b/CovEWS` | cloned | 66 | 0 | 4 | R002, R009, R022, R013 |
| PR-EXP-0164 | `aetherAI/tensorflow-huge-model-support` | cloned | 12 | 0 | 0 |  |
| PR-EXP-0166 | `Heng14/3D_RP-Net` | cloned | 74 | 4 | 13 | R005, R009, E000 |
| PR-EXP-0168 | `sialindskrog/classifyNMIBC` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0171 | `cgps/pathogenwatch/publications/-/tree/master/styphi` | clone_failed: Clon | 0 | 0 | 0 |  |
| PR-EXP-0172 | `DIAL-RPI/CVD-Risk-Estimator` | cloned | 26 | 4 | 1 | E000 |
| PR-EXP-0185 | `linchundan88/fundus_multiple_diseases_web` | cloned | 42 | 0 | 1 | R029 |
| PR-EXP-0187 | `ShenghuaCheng/Aided-Diagnosis-System-for-Cervical-Cance` | cloned | 96 | 0 | 2 | R009, R022 |
| PR-EXP-0189 | `antonior92/ecg-age-prediction` | cloned | 12 | 0 | 0 |  |
| PR-EXP-0192 | `zhijian-yang/SmileGAN` | cloned | 22 | 0 | 2 | R007 |
| PR-EXP-0193 | `LinLu1912/CNN-RNN-paper.git` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0194 | `cancer-oncogenomics/ctDNA-dynamic-prediction-lung-cance` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0197 | `RA19/clltim` | cloned | 2 | 0 | 4 | R013 |
| PR-EXP-0200 | `antonior92/automatic-ecg-diagnosis` | cloned | 10 | 0 | 0 |  |
| PR-EXP-0201 | `cojocchen/covid19_critically_ill` | cloned | 6 | 0 | 1 | R022 |
| PR-EXP-0203 | `albermax/innvestigate` | cloned | 114 | 16 | 2 | E000 |
| PR-EXP-0204 | `ThoroughImages/PathologyGo` | cloned | 14 | 0 | 0 |  |
| PR-EXP-0205 | `clalitresearch/COVID-19-Model` | cloned | 0 | 0 | 0 |  |
| PR-EXP-0207 | `ChenWWWeixiang/diagnosis_covid19` | cloned | 132 | 0 | 35 | R016, R009, R022, R010 |
| PR-EXP-0210 | `AMLab-Amsterdam/AttentionDeepMIL` | cloned | 10 | 0 | 0 |  |
| PR-EXP-0211 | `deepwise-code/DLIA` | cloned | 80 | 2 | 0 |  |
| PR-EXP-0212 | `kumc-bmi/AKI_CDM` | cloned | 0 | 2 | 0 |  |
