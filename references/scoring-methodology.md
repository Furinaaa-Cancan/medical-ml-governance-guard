# MLGG Paper Scoring Methodology

**Version**: 1.0
**Date**: 2026-03-27
**Source of truth**: `scripts/score_paper_metadata.py` + `scripts/_audit_shared.py`

---

## 1. Overview

MLGG 论文评分系统对发表论文的**报告方法学**进行量化评估。评分基于作者在 `metadata.json` 中报告的信息（即"作者声称做了什么"），不涉及代码审查（代码审查由 `scan_published_repos.py` 和 lint 规则 R001-R020 独立执行）。

**核心公式**：

```
total_score = Σ (dimension_fraction_i × weight_i)     对所有 i ∈ {1..12}

其中:
  dimension_fraction_i = passed_checks_i / total_checks_i    (0.0 ~ 1.0)
  dimension_score_i    = dimension_fraction_i × weight_i     (0.0 ~ weight_i)
  total_score          = Σ dimension_score_i                  (0.0 ~ 100.0)
```

**没有 cap 规则**：即使 Leakage Prevention 得分为 0，总分仍然是各维度加权和，不会被强制压到 <60。
**没有 floor 规则**：不存在最低保障分。
**缺失字段处理**：如果 metadata 中某字段为 `null` 或空字符串，对应 check 判定为 **failed**（fail-closed 原则）。

---

## 2. 评分等级

| 总分 | 等级（EN） | 等级（ZH） | 含义 |
|------|-----------|-----------|------|
| ≥ 90 | Publication-grade | 顶刊级 | 方法论无重大缺陷，满足 L3 合规 |
| 75 – 89 | Solid but gaps remain | 需补充 | 存在可修复缺口，L2 合规可达 |
| 60 – 74 | Major issues | 重大缺陷 | 重大方法论问题，仅 L1 |
| < 60 | Not publishable | 不可发表 | 基础方法学失败 |

---

## 3. 12 维度定义与权重

| # | 维度 ID | 名称 | 权重 | 权重占比 |
|---|---------|------|------|---------|
| 1 | `data_integrity` | 数据完整性 | 12 | 12% |
| 2 | `leakage_prevention` | 防泄漏 | 15 | 15% |
| 3 | `pipeline_isolation` | 流水线隔离 | 12 | 12% |
| 4 | `model_selection_rigor` | 模型选择严谨性 | 10 | 10% |
| 5 | `statistical_validity` | 统计有效性 | 12 | 12% |
| 6 | `generalization_evidence` | 泛化证据 | 10 | 10% |
| 7 | `clinical_completeness` | 临床完整性 | 7 | 7% |
| 8 | `reporting_standards` | 报告标准 | 7 | 7% |
| 9 | `reproducibility` | 可重复性 | 6 | 6% |
| 10 | `security_provenance` | 安全与溯源 | 3 | 3% |
| 11 | `fairness_equity` | 公平性 | 3 | 3% |
| 12 | `sample_size_adequacy` | 样本量充足性 | 3 | 3% |
| | | **合计** | **100** | **100%** |

### 权重设计依据

权重分配基于以下原则（非 Delphi 共识，属项目设计决策）：

1. **泄漏相关维度（D2 + D3 = 27%）权重最高**：这是本项目的核心使命——数据泄漏是医学 ML 可重复性危机的首要原因（Kapoor & Narayanan 2023, LIT-009）。
2. **数据+统计（D1 + D5 = 24%）次之**：数据完整性和统计效力是任何预测模型的基石（TRIPOD+AI 2024, LIT-001）。
3. **模型+泛化（D4 + D6 = 20%）**：模型选择和外部验证是顶刊审稿人最关注的方法学问题。
4. **临床+报告（D7 + D8 = 14%）**：报告完整性影响可复现性但不直接影响结果正确性。
5. **辅助维度（D9-D12 = 15%）**：重要但不是方法学致命缺陷。

> **注意**：当前权重未经外部专家 Delphi 共识验证。未来版本计划通过结构化专家调查校准权重。

---

## 4. 维度→字段→检查项完整映射

### D1: Data Integrity（数据完整性） — 权重 12，6 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `split_reported` | `dataset.split_strategy` | 非 null、非空、非 `"not_reported"` | 论文是否报告了分割策略 |
| `train_test_sizes` | `dataset.train_n` | 非 null 且 > 0 | 训练集样本量是否报告 |
| `test_size` | `dataset.test_n` | 非 null 且 > 0 | 测试集样本量是否报告 |
| `total_n_reported` | `dataset.n_patients_total` | 非 null 且 > 0 | 总样本量是否报告 |
| `prevalence_reported` | `dataset.prevalence_pct` | 非 null | 事件率是否报告 |
| `temporal_split` | `dataset.split_strategy` | 值等于 `"temporal"` | 是否使用时间分割（非随机） |

**得分计算**：fraction = passed / 6，score = fraction × 12

---

### D2: Leakage Prevention（防泄漏） — 权重 15，6 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `patient_level_split` | `leakage_risk_assessment.patient_level_split_confirmed` | `true` | 患者级别分割已确认 |
| `temporal_split_confirmed` | `leakage_risk_assessment.temporal_split_confirmed` | `true` | 时间分割已确认 |
| `preprocess_train_only` | `leakage_risk_assessment.preprocessing_fit_on_train_only` | `true` | 预处理仅在训练集 fit |
| `no_test_tuning` | `leakage_risk_assessment.tuning_used_test_data` | `false` | 调参未使用测试集 |
| `low_target_leakage` | `leakage_risk_assessment.target_leakage_risk` | `"low"` | 目标泄漏风险低 |
| `low_post_index_risk` | `leakage_risk_assessment.post_index_feature_risk` | `"low"` | 索引后特征风险低 |

**得分计算**：fraction = passed / 6，score = fraction × 15

---

### D3: Pipeline Isolation（流水线隔离） — 权重 12，3 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `preprocess_isolated` | `leakage_risk_assessment.preprocessing_fit_on_train_only` | `true` | 预处理隔离（与 D2 共享字段） |
| `tuning_set_valid_only` | `model.tuning_set` | `"validation_only"` 或 `"train_validation"` | 调参集不包含测试集 |
| `missing_data_handled` | `dataset.missing_data_strategy` | 非 null 且非空 | 缺失值策略已报告 |

**得分计算**：fraction = passed / 3，score = fraction × 12

> **注意**：`preprocess_isolated` 与 D2 的 `preprocess_train_only` 读取**同一字段**，相当于双倍权重。这是设计决策：预处理隔离同时属于"防泄漏"和"流水线隔离"两个维度。

---

### D4: Model Selection Rigor（模型选择严谨性） — 权重 10，4 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `multiple_candidates` | `model.n_candidate_models` | 非 null 且 ≥ 3 | 候选模型 ≥ 3 个 |
| `hyperparameter_tuning` | `model.hyperparameter_tuning` | 非 null 且非空 | 调参方法已报告 |
| `tuning_not_on_test` | `model.tuning_set` | 不等于 `"test_used"` | 调参未用测试集 |
| `feature_selection_described` | `model.feature_selection_method` | 非 null 且非空 | 特征选择方法已描述 |

**得分计算**：fraction = passed / 4，score = fraction × 10

---

### D5: Statistical Validity（统计有效性） — 权重 12，5 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `ci_reported` | `performance_metrics.bootstrap_ci_reported` | `true` | Bootstrap CI 已报告 |
| `ci_bounds` | `performance_metrics.test_auroc_ci_lower` | 非 null | CI 下界有值 |
| `calibration_reported` | `performance_metrics.calibration_reported` | `true` | 校准已报告 |
| `dca_reported` | `performance_metrics.dca_reported` | `true` | 决策曲线分析已报告 |
| `brier_reported` | `performance_metrics.test_brier_score` | 非 null | Brier score 已报告 |

**得分计算**：fraction = passed / 5，score = fraction × 12

---

### D6: Generalization Evidence（泛化证据） — 权重 10，3 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `external_validation` | `study_design.has_external_validation` | `true` | 有外部验证 |
| `external_auroc` | `performance_metrics.external_auroc` | 非 null | 外部验证 AUROC 已报告 |
| `multicenter` | `study_design.is_multicenter` | `true` | 多中心研究 |

**得分计算**：fraction = passed / 3，score = fraction × 10

---

### D7: Clinical Completeness（临床完整性） — 权重 7，5 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `auroc_reported` | `performance_metrics.test_auroc` | 非 null | AUROC 已报告 |
| `sensitivity_reported` | `performance_metrics.test_sensitivity` | 非 null | 灵敏度已报告 |
| `specificity_reported` | `performance_metrics.test_specificity` | 非 null | 特异度已报告 |
| `ppv_npv_reported` | `performance_metrics.test_ppv` | 非 null | PPV 已报告 |
| `primary_metric_named` | `performance_metrics.primary_metric` | 非 null 且非空 | 主指标已命名 |

**得分计算**：fraction = passed / 5，score = fraction × 7

---

### D8: Reporting Standards（报告标准） — 权重 7，3 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `tripod_claimed` | `reporting_standards.tripod_ai_claimed` | `true` | 声称遵循 TRIPOD+AI |
| `limitation_section` | `reporting_standards.limitation_section` | `true` | 有局限性讨论 |
| `equator_cited` | `reporting_standards.equator_guideline_cited` | 非 null 且非空 | 引用了 EQUATOR 指南 |

**得分计算**：fraction = passed / 3，score = fraction × 7

---

### D9: Reproducibility（可重复性） — 权重 6，2 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `code_available` | `reporting_standards.code_availability` | `"public_github"` | 代码公开在 GitHub |
| `data_available` | `reporting_standards.data_availability` | `"public"` 或 `"on_request"` | 数据可获取 |

**得分计算**：fraction = passed / 2，score = fraction × 6

---

### D10: Security & Provenance（安全与溯源） — 权重 3，1 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `code_or_data_shared` | `reporting_standards.code_availability` | 非 `"not_mentioned"` 且非 null | 至少提及了代码可用性 |

**得分计算**：fraction = passed / 1，score = fraction × 3

---

### D11: Fairness & Equity（公平性） — 权重 3，1 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `multicenter_or_subgroup` | `study_design.is_multicenter` | `true` | 多中心（代理公平性指标） |

**得分计算**：fraction = passed / 1，score = fraction × 3

---

### D12: Sample Size Adequacy（样本量充足性） — 权重 3，2 项检查

| 检查名 | metadata 路径 | 通过条件 | 检测目标 |
|--------|-------------|---------|---------|
| `events_reported` | `dataset.n_events_positive` | 非 null 且 ≥ 100 | 阳性事件 ≥ 100 |
| `epv_adequate` | *计算字段* | `n_events_positive / features_n ≥ 10` | EPV ≥ 10（Riley et al. 2020） |

**得分计算**：fraction = passed / 2，score = fraction × 3

> **EPV 计算**：如果 `n_events_positive` 或 `features_n` 任一为 null 或 features_n ≤ 0，EPV 检查判定为 failed。

---

## 5. 字段交叉引用与重复使用

以下 metadata 字段在多个维度中被重复引用：

| metadata 路径 | 使用维度 | 检查名 |
|-------------|---------|--------|
| `leakage_risk_assessment.preprocessing_fit_on_train_only` | D2, D3 | `preprocess_train_only`, `preprocess_isolated` |
| `model.tuning_set` | D3, D4 | `tuning_set_valid_only`, `tuning_not_on_test` |
| `study_design.is_multicenter` | D6, D11 | `multicenter`, `multicenter_or_subgroup` |
| `reporting_standards.code_availability` | D9, D10 | `code_available`, `code_or_data_shared` |

**影响**：这些字段的失败会导致多个维度同时扣分，实际权重高于表面值。例如 `preprocessing_fit_on_train_only = false` 同时影响 D2（15 分中的 1/6 = 2.5 分）和 D3（12 分中的 1/3 = 4 分），总影响 6.5 分。

---

## 6. 评分系统的已知局限性

1. **仅评估报告完整性**：metadata 评分基于作者声称做了什么，不验证代码是否一致。需配合 R001-R020 lint 扫描交叉验证。
2. **等权 check**：同一维度内所有 check 权重相同（1/N），但实际上 `patient_level_split` 的重要性远高于 `prevalence_reported`。
3. **无 cap 机制**：理论上一篇有严重泄漏（D2 = 0）但其他方面完美的论文可以得到 85 分，这可能高估了论文质量。
4. **D10、D11 各只有 1 个 check**：这些维度的评估粒度不足。
5. **二值判定**：每个 check 只有 pass/fail，无中间状态（如 `target_leakage_risk = "medium"` 判定为 fail）。

---

## 7. 与代码审查路径的关系

```
┌──────────────────────────────────────────┐
│  路径 A: score_paper_metadata.py         │
│  输入: metadata.json（人工填写）          │
│  评估: 作者声称做了什么（12 维 × 41 项） │
│  输出: paper_score.v1 JSON               │
└───────────────────┬──────────────────────┘
                    │
                    │  两者独立执行，结果应交叉比对
                    │
┌───────────────────┴──────────────────────┐
│  路径 C: scan_published_repos.py         │
│  输入: GitHub 代码仓库                    │
│  评估: 代码实际做了什么（R001-R020）      │
│  输出: code_audit JSON                   │
└──────────────────────────────────────────┘
```

**路径 A** 和 **路径 C** 的结论可能矛盾（例如作者声称 `preprocessing_fit_on_train_only = true`，但代码中检测到 R001 fit-before-split）。这种矛盾本身就是有价值的发现——说明论文存在报告不一致。

---

## 8. 计算示例

以 QRISK3（Hippisley-Cox et al. 2017, BMJ）为例：

| 维度 | 检查数 | 通过数 | fraction | 权重 | 得分 |
|------|--------|--------|----------|------|------|
| D1 data_integrity | 6 | 6 | 1.0000 | 12 | 12.00 |
| D2 leakage_prevention | 6 | 4 | 0.6667 | 15 | 10.00 |
| D3 pipeline_isolation | 3 | 3 | 1.0000 | 12 | 12.00 |
| D4 model_selection_rigor | 4 | 2 | 0.5000 | 10 | 5.00 |
| D5 statistical_validity | 5 | 3 | 0.6000 | 12 | 7.20 |
| D6 generalization_evidence | 3 | 3 | 1.0000 | 10 | 10.00 |
| D7 clinical_completeness | 5 | 5 | 1.0000 | 7 | 7.00 |
| D8 reporting_standards | 3 | 3 | 1.0000 | 7 | 7.00 |
| D9 reproducibility | 2 | 1 | 0.5000 | 6 | 3.00 |
| D10 security_provenance | 1 | 1 | 1.0000 | 3 | 3.00 |
| D11 fairness_equity | 1 | 1 | 1.0000 | 3 | 3.00 |
| D12 sample_size_adequacy | 2 | 2 | 1.0000 | 3 | 3.00 |
| **合计** | **41** | **34** | | **100** | **82.20** |

等级：**Solid but gaps remain**（需补充）
主要扣分点：D2 缺少 temporal split 确认 + post-index 风险非 low；D4 仅 1 个候选模型；D5 缺少 DCA 和 Brier score。
