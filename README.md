<p align="center">
  <br>
  <strong style="font-size: 2em;">ML Leakage Guard</strong>
  <br>
  <em>Publication-Grade Integrity Standard for Medical Prediction Models</em>
  <br><br>
  <a href="https://polyformproject.org/licenses/noncommercial/1.0.0/"><img src="https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/tests-3400%2B%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/gates-33%20fail--closed-critical" alt="Gates">
  <img src="https://img.shields.io/badge/MLGG%20Standard-v1.0-orange" alt="Standard">
  <a href="https://doi.org/10.1136/bmj-2023-078378"><img src="https://img.shields.io/badge/TRIPOD%2BAI-2024-blue" alt="TRIPOD+AI"></a>
  <a href="https://doi.org/10.1136/bmj-2024-082505"><img src="https://img.shields.io/badge/PROBAST%2BAI-2025-blue" alt="PROBAST+AI"></a>
</p>

<p align="center">
  <strong>33 道 fail-closed 门控 &middot; 9 阶段工作流 &middot; 12 维量化评分 &middot; 3 级合规认证</strong>
  <br>
  从原始数据到 TRIPOD+AI 合规发表的完整防泄漏管线
</p>

---

## Why MLGG

医学 ML 论文中数据泄漏的发生率远超预期：

| 常见错误 | 后果 | MLGG 如何阻止 |
|:---------|:-----|:-------------|
| 全数据上标准化后再划分 | 性能虚抬，审稿人看不出来 | **P01 gate**: 所有 fit() 仅在训练集 |
| 死亡患者纳入再入院预测 | 结局结构性不可能，AUROC 被污染 | **C01 gate**: 队列定义审查 |
| 名义变量用 OrdinalEncoder | LR 系数失去临床意义 | **P05 gate**: 强制 OneHot |
| 只报 AUROC 不报 MCC | AUROC 0.65 看起来可以，MCC 0.12 近乎随机 | **E02 gate**: 完整 14 指标面板 |
| 用 train-test gap 选模型 | 可能选到次优模型 | **M04 gate**: 验证集 PR-AUC + one-SE 规则 |

**MLGG 的每一条规则都来自实际踩坑，每一个阈值都有文献引用。**

---

## The Pipeline

```
                            ML Leakage Guard
                     Complete 9-Phase Pipeline

    Raw Data
        |
        v
  +-----------+     +---------------+     +---------------+
  |  Phase 1  | --> |   Phase 2     | --> |   Phase 3     |
  |  Cohort   |     |   Splitting   |     | Preprocessing |
  | Definition|     |               |     |               |
  +-----------+     +---------------+     +---------------+
        |                  |                      |
   EPV check          Patient-ID            Fit on train
   Riley 2019        disjoint split           only
   Missingness       Temporal order        OneHot encode
        |                  |                      |
        v                  v                      v
  +-----------+     +---------------+     +---------------+
  |  Phase 4  | --> |   Phase 5     | --> |   Phase 6     |
  |  Feature  |     |   Training    |     |  Evaluation   |
  | Selection |     |  & Selection  |     | & Calibration |
  +-----------+     +---------------+     +---------------+
        |                  |                      |
   Elastic Net        >=3 families          14 metrics
   Stability Sel      One-SE rule           Bootstrap CI
   Ridge control      Optimism corr         DCA + NRI/IDI
        |                  |                      |
        v                  v                      v
  +-----------+     +---------------+     +---------------+
  |  Phase 7  | --> |   Phase 8     | --> |   Phase 9     |
  | Interpret-|     |   Fairness    |     |   Reporting   |
  |  ability  |     |   & Equity    |     |  & Compliance |
  +-----------+     +---------------+     +---------------+
        |                  |                      |
   Multi-model        Equalized odds       TRIPOD+AI 2024
   SHAP ensemble      Disparate impact     PROBAST+AI 2025
   Kendall tau         Subgroup DCA        L1/L2/L3 cert
        |                  |                      |
        +------------------+----------------------+
                           |
                           v
                  +------------------+
                  | 33 Gate DAG      |
                  | Compliance       |
                  | Certificate      |
                  +------------------+
```

---

## Phase 1 &mdash; Cohort Definition & Sample Size

> **Gate**: `cohort_definition_gate` &nbsp;|&nbsp; **Rules**: C01, F05, Z01

**队列定义 (C01)** &mdash; 排除结局结构性不可能的记录。死亡患者纳入再入院预测会虚抬 AUROC（实测 +0.004）。排除规则必须在分析前确定。

**Riley 三准则 (Riley 2019, Stat Med)** &mdash; 替代传统 EPV >= 10：

| 准则 | 含义 | 约束 |
|:-----|:-----|:-----|
| C1 收缩因子 | 预测系数收缩 <= 10% | S >= 0.9 |
| C2 Optimism | R^2 表观值与调整值之差 | <= 0.05 |
| C3 精度 | 总体风险估计 95% CI 半宽 | <= 0.05 |

取三者最大值。EPV < 5 直接 FAIL，5-10 WARNING。

**自动检测** &mdash; 数据类型分类（numeric / binary / categorical / constant / id_or_text），缺失值概况，纵向/横截面判定。

---

## Phase 2 &mdash; Data Splitting

> **Gate**: `split_protocol_gate` + `leakage_gate` &nbsp;|&nbsp; **Rules**: S01, S02

**核心约束** &mdash; 同一患者的所有记录必须归入同一 split（S01），测试集时间必须晚于训练集（S02）。

| 策略 | 适用场景 | 原理 |
|:-----|:---------|:-----|
| `grouped_temporal` | 纵向 EHR / 队列 | 按首次事件时间排序，保证 train < valid < test |
| `grouped_random` | 横截面调查 (NHANES) | 患者级随机打乱 |
| `stratified_grouped` | 横截面 + 保证正类比例一致 | 分层内随机分配 |

**安全门控** &mdash; 每 split 最少 20 行 / 10 正例 / 10 负例 / 5 独立患者。任何患者 ID 跨 split 重叠 -> 立即 FAIL。

---

## Phase 3 &mdash; Preprocessing

> **Rules**: P01-P06

**铁律** &mdash; 所有 `fit()` 仅在训练集。验证集和测试集只调用 `transform()`。管道结构：`Imputer -> Scaler -> Classifier`。

| 特征类型 | 编码方法 | OOD 安全性 |
|:---------|:---------|:-----------|
| Binary (2 值) | 按 train 映射 0/1 | 未见类别 -> 0.0 |
| Categorical (3-15 值) | OneHot (train 类别决定 dummy 列) | 未见类别 -> 全零行 |
| Numeric (> 15 值) | 保持原值 | N/A |

**分层缺失策略 (Madley-Dowd 2019)** &mdash; 按缺失率分 4 层处理，不用固定阈值丢弃。

**SMOTE 立场** &mdash; 默认不使用。van den Goorbergh 2022 (JAMIA) 证明 SMOTE 严重损害校准。改用 `class_weight="balanced"` + 事后 Platt scaling。

---

## Phase 4 &mdash; Feature Selection

> **Rules**: F01-F06

**Elastic Net CV (Zou & Hastie 2005)** &mdash; alpha x C 联合调优，5 折内部 CV，PR-AUC 最优。OneHot dummy 列按原始变量分组选择（Group LASSO 思想）。

**稳定性选择 (Meinshausen & Buhlmann 2010)** &mdash; 100 次子采样，入选概率 > 0.6 的特征保留。

**Ridge 对照 (Harrell 2015)** &mdash; 始终与不做筛选的 Ridge 全量模型比较。Elastic Net 后 PR-AUC 损失 > 0.005 则回退到全量 Ridge。

**禁止单因素筛选** &mdash; Heinze 2018 明确反对，MLGG 将单因素分析仅作诊断工具。

---

## Phase 5 &mdash; Training & Model Selection

> **Gate**: `model_selection_audit_gate` &nbsp;|&nbsp; **Rules**: M01-M04

**20 个模型族** &mdash; LR (L1/L2/ElasticNet) | SVM (linear/rbf) | RF | XGBoost | CatBoost | LightGBM | KNN | MLP | TabPFN | Ensemble (soft voting / weighted / stacking)

**模型选择 (M04)** &mdash; 不使用 train-test gap。在验证集上选 PR-AUC 最优模型，one-SE 规则破平局（1 个标准误内选最简单模型）。

**阈值选择 (M02)** &mdash; 在验证集上通过 F-beta 最大化 + 临床约束（sensitivity >= 0.85, NPV >= 0.90）确定最优阈值。绝不碰测试集。

**Bootstrap Optimism Correction (Steyerberg 2019)** &mdash; 估计性能的"乐观偏差"：

```
corrected = apparent - mean(boot_train_score - boot_original_score)
```

**学习曲线** &mdash; 递增训练集比例（10%-100%），检测模型是否收敛（尾部相对 std < 2%）。

---

## Phase 6 &mdash; Evaluation & Calibration

> **Gates**: 13 道统计门控 &nbsp;|&nbsp; **Rules**: E01-E06

**14 指标面板** &mdash; 测试集一次性使用，覆盖 5 域：

| 域 | 指标 |
|:---|:-----|
| **区分度** | AUROC, PR-AUC |
| **校准** | 校准截距(->0), 斜率(->1), O:E 比(->1), ECE, Brier |
| **分类** | Sensitivity, Specificity, PPV, NPV, F1, **MCC**, Accuracy |
| **临床效用** | **LR+, LR-**, DCA 净效用, NRI, IDI |
| **统计** | Bootstrap 95% CI (B >= 1000), 置换检验 |

> MCC 是不平衡数据下唯一可靠的单一分类指标 (Chicco 2020)。LR+ > 5 有临床价值，LR- < 0.2 可排除 (Deeks 2004)。

**校准三件套 (Van Calster 2019)** &mdash; 通过 logistic recalibration 验证 `logit(y) ~ a + b * logit(y_hat)`，要求 a -> 0, b -> 1, O:E -> 1。

**多种子稳定性 (R02)** &mdash; >= 5 个随机种子训练同一模型，PR-AUC std > 0.03 视为不稳定。

---

## Phase 7 &mdash; Multi-Model SHAP Interpretability

> **Gate**: `shap_interpretability_gate` &nbsp;|&nbsp; Kendall tau >= 0.3 (fail), >= 0.5 (warn)

**为什么多模型** &mdash; 不同模型族有不同归纳偏差。单模型 SHAP 反映模型"世界观"而非数据真相 (Rashomon 效应, Breiman 2001)。

**计算流程** &mdash;

```
For each model family m in {RF, XGB, CatBoost, LGBM, LR, ...}:
    1. Compute SHAP values (TreeExplainer / LinearExplainer / KernelExplainer)
    2. abs_importance_m = mean(|SHAP_m|)
    3. proportion_m = L1-normalize (sum = 1)

Ensemble: proportion = mean(proportion_m for all m)
```

**输出 4 张发表级 CSV**

| 表 | 内容 | 用途 |
|:---|:-----|:-----|
| **Table A** | Ensemble feature importance + direction | 论文主表 |
| **Table B** | Per-model SHAP detail | 审稿人补充表 |
| **Table C** | Cross-model Kendall tau + Jaccard | 方法学证据 |
| **Table D** | Individual case explanations | 临床叙事 |

---

## Phase 8 &mdash; Fairness & Equity

> **Gate**: `fairness_equity_gate` &nbsp;|&nbsp; **Rules**: Q01, Q02

| 检查 | 失败阈值 | 警告阈值 |
|:-----|:---------|:---------|
| Equalized odds gap (sensitivity) | > 0.15 | > 0.10 |
| Disparate impact ratio (80% rule) | < 0.80 | < 0.85 |
| PR-AUC per subgroup minimum | < 0.40 | < 0.50 |
| FPR / FNR gap (HEAL framework) | > 0.15 | > 0.10 |

n < 200 的亚组标记为"估计不可靠"，不作为比较依据。

---

## Phase 9 &mdash; Reporting & Compliance

> **Gates**: `publication_gate` + `self_critique_gate` &nbsp;|&nbsp; **Rule**: T01

**TRIPOD+AI 2024** (Collins, BMJ) &mdash; 27 项逐项核对，机器验证每项有对应证据文件。

**PROBAST+AI 2025** (Moons, BMJ) &mdash; 4 域评估：Participants -> Predictors -> Outcome -> Analysis。16 个信号问题。

**L1/L2/L3 三级合规**

| 等级 | 门控数 | 适用场景 |
|:-----|:-------|:---------|
| **L1** 泄漏审计 | 12 门 | 会议论文、初步报告 |
| **L2** 统计有效 | 25 门 | 专业期刊 (JAMIA, npj Digital Medicine) |
| **L3** 发布级 | **全部 33 门** | Nature Medicine, Lancet, JAMA, BMJ |

---

## The 33-Gate DAG

33 道门控按有向无环图 (DAG) 分 9 层执行。同层可并行，全部通过才能声称 L3 Publication-Grade。

```
Layer 0  CONTRACT        cohort_definition  |  request_contract
   |
Layer 1  MANIFEST        manifest_lock
   |
Layer 2  ATTESTATION     execution_attestation
   |
Layer 3  DATA            leakage  |  split_protocol  |  covariate_shift  |  reporting_bias
   |
Layer 4  POLICY          definition_guard  |  feature_lineage  |  imbalance  |  missingness  |  tuning
   |
Layer 5  MODEL           model_selection_audit  |  feature_engineering  |  clinical_metrics  |  shap
   |
Layer 6  STATISTICS      calibration_dca  |  ci_matrix  |  distribution  |  eval_quality
                         external_validation  |  fairness  |  gap  |  metric_consistency
                         permutation  |  prediction_replay  |  robustness  |  sample_size  |  seed
   |
Layer 7  AGGREGATION     publication_gate
   |
Layer 8  FINAL           self_critique  |  security_audit
```

<details>
<summary><strong>33 Gate Detail Table</strong></summary>

| # | Layer | Gate | What It Checks |
|:--|:------|:-----|:---------------|
| 1 | 0 | `cohort_definition_gate` | EPV adequacy, data types, missingness profile |
| 2 | 0 | `request_contract_gate` | Request schema, file paths, anti-downgrade |
| 3 | 1 | `manifest_lock` | SHA-256 fingerprint of all artifacts |
| 4 | 2 | `execution_attestation_gate` | Cryptographic signatures, timestamps, witnesses |
| 5 | 3 | `leakage_gate` | Row/ID/temporal overlap, suspicious feature names |
| 6 | 3 | `split_protocol_gate` | Patient-disjoint splits, temporal ordering |
| 7 | 3 | `covariate_shift_gate` | Jensen-Shannon divergence, prevalence drift |
| 8 | 3 | `reporting_bias_gate` | TRIPOD+AI / PROBAST+AI / STARD-AI checklists |
| 9 | 4 | `definition_variable_guard` | Block outcome-definition variables as features |
| 10 | 4 | `feature_lineage_gate` | Block post-index-time derived features |
| 11 | 4 | `imbalance_policy_gate` | Class imbalance strategy, train-only resampling |
| 12 | 4 | `missingness_policy_gate` | Missing data strategy, imputer isolation |
| 13 | 4 | `tuning_leakage_gate` | Hyperparameter tuning protocol, test isolation |
| 14 | 5 | `model_selection_audit_gate` | One-SE rule replay, >= 3 candidates, logistic baseline |
| 15 | 5 | `feature_engineering_audit_gate` | Feature group provenance, stability evidence |
| 16 | 5 | `clinical_metrics_gate` | 14-metric panel, confusion matrix consistency, clinical floors |
| 17 | 5 | `shap_interpretability_gate` | Multi-model SHAP, Kendall tau, 4 CSV tables |
| 18 | 6 | `calibration_dca_gate` | ECE, slope/intercept, O:E ratio, DCA net benefit |
| 19 | 6 | `ci_matrix_gate` | Bootstrap CI matrix across all splits |
| 20 | 6 | `distribution_generalization_gate` | Cross-split distribution shift assessment |
| 21 | 6 | `evaluation_quality_gate` | CI width, baseline delta, resampling adequacy |
| 22 | 6 | `external_validation_gate` | External cohort metric validation |
| 23 | 6 | `fairness_equity_gate` | Equalized odds, disparate impact, subgroup floors |
| 24 | 6 | `generalization_gap_gate` | Train-valid-test performance gaps |
| 25 | 6 | `metric_consistency_gate` | Metric value consistency across reports |
| 26 | 6 | `permutation_significance_gate` | Permutation null distribution significance |
| 27 | 6 | `prediction_replay_gate` | Row-level prediction trace metric replay |
| 28 | 6 | `robustness_gate` | Time-slice and subgroup robustness |
| 29 | 6 | `sample_size_gate` | EPV, shrinkage factor, Riley criteria |
| 30 | 6 | `seed_stability_gate` | Multi-seed variance (>= 5 seeds) |
| 31 | 7 | `publication_gate` | Aggregate L1/L2/L3 compliance determination |
| 32 | 8 | `self_critique_gate` | 12-dimension quality score + recommendations |
| 33 | 8 | `security_audit_gate` | HMAC signatures, evidence integrity, sensitive data |

</details>

---

## 12-Dimension Scoring

每个维度独立评分，加权求和得出总分（0-100）：

| # | Dimension | Weight | What It Measures |
|:--|:----------|:-------|:-----------------|
| 1 | Data Integrity | 12 | Split isolation, patient non-overlap, temporal correctness |
| 2 | Leakage Prevention | 15 | Target leakage, definition variables, post-index features |
| 3 | Pipeline Isolation | 12 | Train-only preprocessing, imputer/scaler/resampling scope |
| 4 | Model Selection Rigor | 10 | Candidate pool, one-SE rule, test isolation |
| 5 | Statistical Validity | 12 | Bootstrap CI, permutation tests, calibration, DCA |
| 6 | Generalization Evidence | 10 | Train-test gap, external cohorts, seed stability |
| 7 | Clinical Completeness | 7 | Full metric panel (MCC, LR+/LR-), confusion matrix |
| 8 | Reporting Standards | 7 | TRIPOD+AI, PROBAST+AI, limitations disclosure |
| 9 | Reproducibility | 6 | Seed locking, version tracking, execution attestation |
| 10 | Security & Provenance | 3 | HMAC-SHA256 signing, AES-256-GCM, audit chain |
| 11 | Fairness & Equity | 3 | Subgroup analysis, equalized odds, disparate impact |
| 12 | Sample Size Adequacy | 3 | EPV, Riley criteria, shrinkage factor |

**Interpretation**: >= 90 top-tier journal / 75-89 needs supplementation / 60-74 major defects / < 60 unpublishable

---

## Quick Start

### With Claude Code (Recommended)

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard.git
cd medical-ml-leakage-guard

# Open Claude Code and say:
#   "Help me predict diabetes with this CSV"
#   "Review my code for data leakage"
#   "My model AUC is 0.85, what do I need for Nature Medicine?"
#
# Or type /mlgg to activate full methodology guidance mode.
```

### Command Line

```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Interactive pixel-art terminal UI (5 min full experience)
python3 scripts/orchestration/mlgg.py play

# Guided onboarding from scratch
python3 scripts/orchestration/mlgg.py onboarding --project-root /tmp/demo --mode guided --yes

# Audit any existing ML project (no config needed)
python3 scripts/tools/generate_audit_report.py --project-dir /path/to/your/project

# Publication-grade strict pipeline
python3 scripts/orchestration/mlgg.py workflow --request configs/request.json --strict
```

---

## Project Structure

```
scripts/
  core/             Framework internals (_gate_framework, _gate_utils, _security, ...)
  gates/            33 fail-closed gate scripts
  orchestration/    CLI entrypoints (mlgg.py, run_dag_pipeline, ...)
  tools/            Reports, training, splitting, utilities
tests/              4000+ pytest tests
examples/           14 medical datasets + reference implementation
experiments/        E2E benchmark suite (4 UCI datasets)
references/         60+ JSON knowledge bases, TRIPOD/PROBAST templates
plugin/             Static analysis lint rules R001-R020
```

---

## Security Layer

| Component | Implementation |
|:----------|:---------------|
| Model signing | HMAC-SHA256, timing-safe verification |
| Evidence encryption | AES-256-GCM (fail-closed, no fallback) |
| Audit chain | Append-only JSONL with chained HMAC hashes |
| Deserialization | Restricted unpickler with module allowlist |
| Path traversal | Symlink-safe sandbox enforcement |
| Attestation | OpenSSL detached signatures + witness quorum |

---

## Literature Foundation

Every methodology decision has peer-reviewed backing:

| Phase | Key References |
|:------|:---------------|
| 1. Sample Size | Riley 2019 (Stat Med), Peduzzi 1996 (J Clin Epidemiol) |
| 2. Splitting | Steyerberg 2019 (Springer), Futoma 2020 (Lancet Digit Health) |
| 3. Preprocessing | Kaufman 2012 (ACM TKDD), van den Goorbergh 2022 (JAMIA), Madley-Dowd 2019 |
| 4. Feature Selection | Zou & Hastie 2005 (JRSS-B), Meinshausen 2010, Heinze 2018, Harrell 2015 |
| 5. Training | Yang 2023 (KDD), Steyerberg 2019 Ch.17 |
| 6. Evaluation | Van Calster 2019 (BMC Med), Chicco 2020 (BMC Genomics), Deeks 2004 (BMJ) |
| 7. Interpretability | Lundberg 2017 (NeurIPS), PMC11513550, Breiman 2001 |
| 8. Fairness | TRIPOD+AI 2024 Item 16b, Steyerberg 2019 Ch.25 |
| 9. Reporting | Collins 2024 (BMJ), Moons 2025 (BMJ), Kapoor 2023 (Patterns) |

---

## License & Citation

**PolyForm Noncommercial License 1.0.0** &mdash; See [LICENSE](./LICENSE).

Academic use **requires citation**:

```bibtex
@software{mlgg2026,
  title   = {ML Leakage Guard (MLGG): Publication-Grade Integrity Standard
             for Medical Prediction Models},
  author  = {Weng, Can},
  year    = {2026},
  version = {1.0},
  url     = {https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard},
  note    = {33 fail-closed audit gates, 9-phase workflow,
             TRIPOD+AI 2024 / PROBAST+AI 2025 compliant}
}
```

Commercial use is **strictly prohibited**. Uncited reproduction of MLGG methodology constitutes academic misconduct. See LICENSE for full terms.
