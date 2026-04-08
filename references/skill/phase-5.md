# Phase 5: 模型训练

> **Pipeline 模式 (路径 A)**：Phase 3-6 由 `mlgg.py train` 一条命令自动完成，本文件不适用。
> **Research 模式 (路径 B)**：用户自己写训练代码时，按以下规则审查。

## Research 模式说明

用户有两种选择：
1. **用 MLGG 工具训练**：运行下方的 `train_select_evaluate.py` 命令（自动满足所有 gate 的 JSON 格式要求）
2. **审查用户自己的训练代码**：Agent 按本文件的规则逐项审查用户代码，然后用 `mlgg lint check` 扫描。Gate 验证可能需要用户手动生成兼容格式的 JSON 报告，或跳过特定 gate。

## 目标
训练 ≥3 模型族，在验证集/CV 上选模型和阈值，测试集零接触。

## 前置条件
- Phase 4 评审通过：`evidence/lineage_report.json` 存在且 status=pass
- 特征集已确定，EPV 充足

## 执行命令

```bash
# 标准模式（有 test.csv）
python3 scripts/tools/train_select_evaluate.py \
  --train data/train.csv \
  --test data/test.csv \
  [--valid data/valid.csv] \
  --target-col y \
  --patient-id-col <ID> \
  --output-dir evidence/ \
  --model-pool "lr,rf,xgboost" \
  [--include-optional-models] \
  [--max-trials-per-family 20] \
  [--n-jobs 1]

# CV-only 模式（无 test.csv，n < 1000）
python3 scripts/tools/train_select_evaluate.py \
  --train data/train.csv \
  --selection-data cv_inner \
  --target-col y \
  --patient-id-col <ID> \
  --output-dir evidence/ \
  --model-pool "lr,rf,xgboost" \
  [--n-jobs 1]
# CV-only 模式下：评估用 Bootstrap optimism correction，不产出独立测试集指标
```

## 关键约束

- **≥ 3 模型族**: LR / RF / XGBoost / LightGBM / CatBoost / SVM / MLP
- **调参**: 在 valid 或 CV 上，绝不碰 test（MLGG-M01）
- **选择标准**: valid PR-AUC + One-SE rule（MLGG-M04, Yang KDD 2023）
- **阈值**: Youden's J on valid（MLGG-M02）
- **预期耗时**: 5-30 分钟（取决于数据量和模型数）→ 必须提前告知用户

## Gate 检查

```bash
# 如果 configs/tuning-protocol.json 不存在，先从模板创建:
#   cp references/tuning-protocol.example.json configs/tuning-protocol.json
#   然后根据实际调参策略编辑

# 1. 调优泄漏
python3 scripts/gates/tuning_leakage_gate.py \
  --protocol configs/tuning-protocol.json \
  --report evidence/tuning_leakage_report.json --strict

# 2. 模型选择审计
python3 scripts/gates/model_selection_audit_gate.py \
  --selection-report evidence/model_selection_report.json \
  --report evidence/model_selection_audit_report.json --strict
```

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| M01 | CRITICAL | 禁止在 test 调参 |
| M02 | CRITICAL | 阈值在 valid 选择 |
| M04 | CRITICAL | 选模型用 valid 性能，不用 train-test gap |

## 训练后建议（非阻断，但推荐）

- `bootstrap_optimism_correction()` — 估计乐观偏差（Steyerberg 2019）
- `learning_curve_data()` — 检查性能是否随数据量收敛
- `robustness_stress_test()` — 噪声/异常值稳定性

## 常见陷阱

- 候选模型 < 3 个 → `candidate_pool_too_small`
- Early stopping 使用了测试集 → 调优泄漏
- 只用 AUROC 选模型而非 PR-AUC（不平衡数据下 AUROC 过于乐观）

## 完成后告诉用户

```
Phase 5 训练完成:
- 训练了 N 个模型族 × M 个超参组合
- 最优模型: [模型名] (valid PR-AUC = X.XXX)
- 阈值: X.XX (Youden's J on valid)
- 调优泄漏检查: ✓ 测试集未参与
- 候选池大小: XX（满足 ≥3 要求）
建议运行鲁棒性压力测试以检查稳定性。
```
