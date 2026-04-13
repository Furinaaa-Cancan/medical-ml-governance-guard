# Metadata Validation Rules

**Version**: 1.0
**Date**: 2026-03-27
**Applies to**: `papers/<journal>/<disease>/<paper>/metadata.json`

---

## 1. Overview

本文档定义 `metadata.json` 字段的**验证规则**，用于在评分前检测不一致、超范围和逻辑矛盾。这些规则不影响评分计算（评分逻辑见 `scoring-methodology.md`），但应在导入新论文时执行，以避免 garbage-in-garbage-out。

验证分为三个级别：

| 级别 | 含义 | 处理 |
|------|------|------|
| ERROR | 数据逻辑矛盾，评分结果不可信 | 必须修复后才能评分 |
| WARNING | 异常值或可疑数据，可能是填写错误 | 标记并人工确认 |
| INFO | 建议补充但不影响评分 | 可选修复 |

---

## 2. 字段范围约束

### 2.1 数值范围

| 字段路径 | 类型 | 有效范围 | 级别 | 说明 |
|---------|------|---------|------|------|
| `dataset.n_patients_total` | int | > 0 | ERROR | 样本量必须为正整数 |
| `dataset.n_events_positive` | int | ≥ 0 | ERROR | 阳性事件数不可为负 |
| `dataset.n_events_negative` | int | ≥ 0 | ERROR | 阴性事件数不可为负 |
| `dataset.prevalence_pct` | float | 0.0 – 100.0 | ERROR | 百分比范围 |
| `dataset.train_n` | int | > 0 | ERROR | 训练集大小必须为正 |
| `dataset.valid_n` | int | ≥ 0 | WARNING | 验证集可为 0（若用 CV 替代） |
| `dataset.test_n` | int | > 0 | ERROR | 测试集大小必须为正 |
| `dataset.features_n` | int | > 0 | ERROR | 特征数必须为正 |
| `performance_metrics.test_auroc` | float | 0.0 – 1.0 | ERROR | AUROC 范围 |
| `performance_metrics.test_auroc_ci_lower` | float | 0.0 – 1.0 | ERROR | CI 下界范围 |
| `performance_metrics.test_auroc_ci_upper` | float | 0.0 – 1.0 | ERROR | CI 上界范围 |
| `performance_metrics.test_auprc` | float | 0.0 – 1.0 | ERROR | AUPRC 范围 |
| `performance_metrics.test_sensitivity` | float | 0.0 – 1.0 | ERROR | 灵敏度范围 |
| `performance_metrics.test_specificity` | float | 0.0 – 1.0 | ERROR | 特异度范围 |
| `performance_metrics.test_ppv` | float | 0.0 – 1.0 | ERROR | PPV 范围 |
| `performance_metrics.test_npv` | float | 0.0 – 1.0 | ERROR | NPV 范围 |
| `performance_metrics.test_f1` | float | 0.0 – 1.0 | ERROR | F1 范围 |
| `performance_metrics.test_brier_score` | float | 0.0 – 1.0 | ERROR | Brier 范围（0=完美，1=最差） |
| `performance_metrics.external_auroc` | float | 0.0 – 1.0 | ERROR | 外部验证 AUROC 范围 |
| `performance_metrics.external_auroc_ci_lower` | float | 0.0 – 1.0 | ERROR | 外部 CI 下界 |
| `performance_metrics.external_auroc_ci_upper` | float | 0.0 – 1.0 | ERROR | 外部 CI 上界 |
| `performance_metrics.n_bootstrap_resamples` | int | > 0 | WARNING | Bootstrap 次数应为正 |
| `bibliographic.year` | int | 1990 – 2030 | WARNING | 合理发表年份范围 |
| `model.n_candidate_models` | int | ≥ 1 | WARNING | 至少 1 个模型 |

### 2.2 枚举约束

| 字段路径 | 允许值 | 级别 |
|---------|-------|------|
| `study_design.prediction_type` | `"binary_classification"` | ERROR（v1.0 仅支持二分类） |
| `dataset.source_type` | `"EHR_single_center"`, `"EHR_multicenter"`, `"public_dataset"`, `"registry"`, `"biobank"`, `"claims_data"`, `"mixed"` | WARNING |
| `dataset.split_strategy` | `"random"`, `"temporal"`, `"site_based"`, `"not_reported"` | WARNING |
| `model.tuning_set` | `"validation_only"`, `"train_validation"`, `"test_used"`, `"not_reported"` | WARNING |
| `leakage_risk_assessment.target_leakage_risk` | `"low"`, `"medium"`, `"high"`, `"cannot_assess"` | WARNING |
| `leakage_risk_assessment.post_index_feature_risk` | `"low"`, `"medium"`, `"high"`, `"cannot_assess"` | WARNING |
| `leakage_risk_assessment.phenotype_definition_overlap_risk` | `"low"`, `"medium"`, `"high"`, `"cannot_assess"` | WARNING |
| `reporting_standards.code_availability` | `"public_github"`, `"on_request"`, `"not_available"`, `"not_mentioned"` | WARNING |
| `reporting_standards.data_availability` | `"public"`, `"on_request"`, `"restricted"`, `"not_available"`, `"not_mentioned"` | WARNING |

---

## 3. 字段间一致性规则

### 3.1 样本量一致性

| 规则 ID | 条件 | 级别 | 说明 |
|---------|------|------|------|
| C-001 | `n_events_positive + n_events_negative == n_patients_total` | ERROR | 正例 + 反例 = 总数（允许 ±1% 容差，因四舍五入） |
| C-002 | `train_n + valid_n + test_n` ≈ `n_patients_total` | WARNING | 各分割之和应约等于总数（允许 ±5% 容差，因部分样本可能被排除） |
| C-003 | `prevalence_pct` ≈ `n_events_positive / n_patients_total × 100` | WARNING | 事件率应与事件数/总数一致（允许 ±2% 绝对误差） |
| C-004 | `test_n / n_patients_total` ≥ 0.05 | WARNING | 测试集至少占 5%（过小不稳定） |

### 3.2 性能指标一致性

| 规则 ID | 条件 | 级别 | 说明 |
|---------|------|------|------|
| P-001 | `test_auroc_ci_lower ≤ test_auroc ≤ test_auroc_ci_upper` | ERROR | AUROC 必须在 CI 内 |
| P-002 | `external_auroc_ci_lower ≤ external_auroc ≤ external_auroc_ci_upper` | ERROR | 外部 AUROC 必须在 CI 内 |
| P-003 | 若 `test_auroc > 0.99`，触发 WARNING | WARNING | AUROC > 0.99 极度可疑，可能存在泄漏 |
| P-004 | 若 `test_auroc > 0.95` 且 `prevalence_pct < 5`，触发 WARNING | WARNING | 罕见事件 + 极高 AUC 组合可疑 |
| P-005 | 若 `external_auroc` 存在且 `has_external_validation == false`，触发 ERROR | ERROR | 逻辑矛盾 |
| P-006 | 若 `has_external_validation == true` 且 `external_auroc` 为 null，触发 WARNING | WARNING | 声称有外部验证但未报告 AUROC |

### 3.3 泄漏评估一致性

| 规则 ID | 条件 | 级别 | 说明 |
|---------|------|------|------|
| L-001 | 若 `tuning_used_test_data == true` 且 `tuning_set != "test_used"`，触发 ERROR | ERROR | 两个字段矛盾 |
| L-002 | 若 `tuning_set == "test_used"` 且 `tuning_used_test_data != true`，触发 ERROR | ERROR | 两个字段矛盾（反向） |
| L-003 | 若 `split_strategy == "temporal"` 且 `temporal_split_confirmed == false`，触发 WARNING | WARNING | 分割策略与确认标志矛盾 |
| L-004 | 若 `split_strategy == "random"` 且 `temporal_split_confirmed == true`，触发 ERROR | ERROR | 随机分割不可能是时间分割 |
| L-005 | 若 `target_leakage_risk == "high"` 且 `test_auroc > 0.95`，触发 INFO | INFO | 高泄漏风险 + 高性能 = 强泄漏嫌疑 |

### 3.4 研究设计一致性

| 规则 ID | 条件 | 级别 | 说明 |
|---------|------|------|------|
| S-001 | 若 `is_multicenter == true` 且 `source_type == "EHR_single_center"`，触发 ERROR | ERROR | 多中心与单中心矛盾 |
| S-002 | 若 `has_external_validation == true` 且 `external_cohort_description` 为空，触发 WARNING | WARNING | 声称外部验证但未描述外部队列 |

---

## 4. 必填字段（评分所需最小集）

以下字段如果为 null，对应维度的检查将判定为 failed。标记为 **REQUIRED** 的字段如果缺失，整篇论文评分的可信度降低。

| 优先级 | 字段路径 | 影响维度 | 说明 |
|--------|---------|---------|------|
| REQUIRED | `bibliographic.title` | — | 论文标识（批量模式跳过无标题的模板） |
| REQUIRED | `bibliographic.year` | — | 时间趋势分析 |
| REQUIRED | `bibliographic.doi` | — | 论文唯一标识 |
| REQUIRED | `dataset.n_patients_total` | D1 | 样本量 |
| REQUIRED | `dataset.split_strategy` | D1 | 分割策略 |
| REQUIRED | `performance_metrics.test_auroc` | D7 | 主要性能指标 |
| HIGH | `dataset.n_events_positive` | D12 | EPV 计算 |
| HIGH | `dataset.features_n` | D12 | EPV 计算 |
| HIGH | `leakage_risk_assessment.patient_level_split_confirmed` | D2 | 核心泄漏评估 |
| HIGH | `leakage_risk_assessment.preprocessing_fit_on_train_only` | D2, D3 | 核心泄漏评估 |
| MEDIUM | `study_design.has_external_validation` | D6 | 泛化证据 |
| MEDIUM | `model.n_candidate_models` | D4 | 模型选择 |

---

## 5. 缺失值处理策略

| 字段类型 | null 值处理 | 空字符串处理 |
|---------|-----------|------------|
| 布尔字段（`*_confirmed`, `*_reported`, `*_claimed`） | 判定为 failed（fail-closed） | 不适用（布尔字段不应为字符串） |
| 数值字段（`*_n`, `*_pct`, `*_auroc`） | 判定为 failed | 不适用 |
| 字符串字段（`split_strategy`, `model_type`） | 判定为 failed | 判定为 failed |
| 枚举字段（`tuning_set`, `target_leakage_risk`） | 判定为 failed | 判定为 failed |

**原则**：在 MLGG 评分体系中，"未报告"等同于"未做"。这与 PROBAST+AI 的处理方式一致——无法评估的项目在风险评估中视为"unclear"而非"low risk"。

---

## 6. 实施建议

### 6.1 当前状态

`score_paper_metadata.py` **目前不执行这些验证规则**。它直接对 metadata 字段运行 check lambdas，不检查范围或一致性。

### 6.2 建议的实施方式

```python
# 在 score_metadata() 之前调用
def validate_metadata(metadata: dict) -> list[dict]:
    """返回验证问题列表 [{rule_id, level, message, field}]"""
    issues = []
    # Range checks (§2.1)
    auroc = _get_nested(metadata, "performance_metrics.test_auroc")
    if auroc is not None and not (0.0 <= auroc <= 1.0):
        issues.append({"rule_id": "R-AUROC", "level": "ERROR", ...})
    # Consistency checks (§3)
    ...
    return issues
```

### 6.3 优先级

1. **Phase 1**（立即）：手工填写 metadata 时参照本文档核对
2. **Phase 2**（短期）：在 `score_paper_metadata.py` 中添加 `--validate` 选项
3. **Phase 3**（中期）：在 `extract_paper_metadata.py`（LLM 提取）的输出上自动执行验证
