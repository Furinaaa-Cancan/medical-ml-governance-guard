# Gate Strictness Profiles

**Version**: 1.0
**Date**: 2026-03-28
**Purpose**: 定义不同研究场景下的阈值预设，避免一刀切导致合理研究被误杀。

---

## 1. 问题

33-gate 流水线的默认阈值针对"大样本 + 常见病 + 多中心"场景设计。对于小样本、罕见病、单中心研究，多个 gate 会产生**不可避免的失败**，不是因为研究有缺陷，而是因为数据量不足以满足统计要求。

**估计的误杀率**：

| 场景 | 样本量 | 患病率 | L3 误杀率 |
|------|--------|--------|----------|
| 罕见病单中心 | N=200 | 5% | ~80% |
| 常见病多中心 | N=2000 | 20% | ~15% |
| 中等多点 | N=1000 | 10% | ~35% |

---

## 2. 解决方案：场景感知阈值预设

在 `request.json` 的 `thresholds` 中加入 `profile` 字段：

```json
{
  "thresholds": {
    "profile": "rare_disease",
    "alpha": 0.05,
    "...": "..."
  }
}
```

### 2.1 预设 Profile 定义

#### `standard`（默认，当前行为）

适用于：常见病（患病率 ≥ 10%）、多中心、N ≥ 1000

```json
{
  "profile": "standard",
  "epv_minimum": 10,
  "epv_recommended": 20,
  "min_total_events": 100,
  "min_test_events": 50,
  "seed_count_minimum": 5,
  "seed_count_warning": 3,
  "pr_auc_std_max": 0.03,
  "alpha": 0.01,
  "equalized_odds_gap_fail": 0.15,
  "equalized_odds_gap_warn": 0.10,
  "ext_val_min_events": 100,
  "covariate_shift_jsd_max": 0.35
}
```

#### `small_cohort`

适用于：N = 200-1000，单中心，患病率 5-20%

```json
{
  "profile": "small_cohort",
  "epv_minimum": 7,
  "epv_recommended": 10,
  "min_total_events": 50,
  "min_test_events": 25,
  "seed_count_minimum": 3,
  "seed_count_warning": 2,
  "pr_auc_std_max": 0.05,
  "alpha": 0.05,
  "equalized_odds_gap_fail": 0.20,
  "equalized_odds_gap_warn": 0.15,
  "ext_val_min_events": 50,
  "covariate_shift_jsd_max": 0.45,
  "_note": "Relaxed thresholds for small cohorts. Studies using this profile should explicitly report the relaxation in their methods section."
}
```

#### `rare_disease`

适用于：N < 200，患病率 < 5%，罕见疾病/儿科

```json
{
  "profile": "rare_disease",
  "epv_minimum": 5,
  "epv_recommended": 7,
  "min_total_events": 20,
  "min_test_events": 10,
  "seed_count_minimum": 3,
  "seed_count_warning": 2,
  "pr_auc_std_max": 0.08,
  "alpha": 0.05,
  "equalized_odds_gap_fail": 0.25,
  "equalized_odds_gap_warn": 0.20,
  "ext_val_min_events": 20,
  "covariate_shift_jsd_max": 0.50,
  "_note": "Minimum viable thresholds for rare disease research. External validation may use pooled multicenter data. Fairness gate accepts 'not assessed due to homogeneous cohort' with justification."
}
```

#### `exploratory`

适用于：可行性研究、方法学探索、非临床部署目标

```json
{
  "profile": "exploratory",
  "epv_minimum": 5,
  "epv_recommended": 10,
  "min_total_events": 20,
  "min_test_events": 10,
  "seed_count_minimum": 2,
  "seed_count_warning": 1,
  "pr_auc_std_max": 0.10,
  "alpha": 0.05,
  "equalized_odds_gap_fail": 0.30,
  "equalized_odds_gap_warn": 0.20,
  "ext_val_min_events": null,
  "covariate_shift_jsd_max": 0.60,
  "_note": "Maximum relaxation. Studies MUST clearly state exploratory nature. L3 conformance not achievable with this profile."
}
```

---

## 3. Profile 与 Conformance Level 的关系

| Profile | L1 可达？ | L2 可达？ | L3 可达？ |
|---------|----------|----------|----------|
| `standard` | ✅ | ✅ | ✅ |
| `small_cohort` | ✅ | ✅ | ⚠️ 需在 compliance certificate 中注明 |
| `rare_disease` | ✅ | ⚠️ 需注明 | ❌ L3 不可用此 profile |
| `exploratory` | ✅ | ❌ L2 不可用 | ❌ |

**关键原则**：
- Profile 放宽阈值，但**不跳过任何 gate**（所有 gate 仍然执行）
- Profile 信息会被写入 compliance certificate，审稿人可见
- `rare_disease` 和 `exploratory` profile 的 certificate 会有醒目标注

---

## 4. 各 Gate 受 Profile 影响的阈值

| Gate | 受影响参数 | standard | small_cohort | rare_disease |
|------|-----------|----------|-------------|-------------|
| sample_size_gate | epv_minimum | 10 | 7 | 5 |
| sample_size_gate | min_total_events | 100 | 50 | 20 |
| seed_stability_gate | seed_count_minimum (strict) | 5 | 3 | 3 |
| seed_stability_gate | pr_auc_std_max | 0.03 | 0.05 | 0.08 |
| permutation_significance_gate | alpha | 0.01 | 0.05 | 0.05 |
| fairness_equity_gate | equalized_odds_gap_fail | 0.15 | 0.20 | 0.25 |
| external_validation_gate | min_events | 100 | 50 | 20 |
| covariate_shift_gate | jsd_max | 0.35 | 0.45 | 0.50 |
| calibration_dca_gate | ece_max | 0.06 | 0.08 | 0.10 |

**不受 Profile 影响的 Gate**（硬约束，任何场景都不应违反）：
- leakage_gate（数据泄漏）
- split_protocol_gate（分割完整性）
- definition_variable_guard（定义变量泄漏）
- feature_lineage_gate（特征来源）
- tuning_leakage_gate（调参泄漏）
- metric_consistency_gate（指标一致性）
- execution_attestation_gate（执行证明）
- manifest_lock（完整性校验）

---

## 5. fairness_equity_gate 的特殊处理

当前问题：如果队列 95% 是同一种族，`subgroup_performance` 缺失直接 FAIL。

建议修改：允许在 evaluation_report.json 中声明：

```json
{
  "fairness_assessment": {
    "status": "not_assessed",
    "justification": "Single-ethnicity cohort (>90% Han Chinese). Subgroup analysis not feasible.",
    "plan": "Will assess in future multi-site validation including diverse populations."
  }
}
```

当 `status == "not_assessed"` 且有 `justification` 时：
- `standard` profile：WARNING（需在论文中报告为限制）
- `small_cohort` / `rare_disease` profile：INFO（记录但不影响评分）

---

## 6. 实施路径

### Phase 1：文档和配置（当前）
- ✅ 本文档定义了 4 个 profile
- TODO：在 `request-schema.example.json` 中添加 `profile` 字段
- TODO：在 SKILL.md 的 Quick Dispatch 表中添加 profile 选择指引

### Phase 2：代码实施
- TODO：在 `request_contract_gate.py` 中解析 `profile`，生成对应的 thresholds dict
- TODO：各 gate 从 request.json 读取覆盖后的阈值
- TODO：compliance certificate 标注使用的 profile

### Phase 3：验证
- TODO：在 6 个 UCI 数据集上分别用 4 个 profile 跑一遍，验证 L1/L2/L3 达标率
