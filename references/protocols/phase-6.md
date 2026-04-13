# Phase 6: 评估

> **Pipeline 模式 (路径 A)**：Phase 3-6 由 `mlgg.py train` 一条命令自动完成，本文件仅在 Research 模式下需要。
> Pipeline 模式用户在 A-3 完成后直接进入 A-4（SHAP），评估 gate 在 A-6（workflow --strict）中统一运行。

## 目标
在测试集上执行单次最终评估，生成完整 5 域指标面板 + Bootstrap CI。

## 前置条件
- Phase 5 评审通过：`evidence/tuning_leakage_report.json` 和 `evidence/model_selection_audit_report.json` 存在且 status=pass
- 最优模型和阈值已确定
- `evidence/evaluation_report.json` 已由 `train_select_evaluate.py` 生成

## 5 域指标面板（Riley et al., Lancet Digital Health 2025; doi:10.1016/S2589-7500(25)00021-4）

| 域 | 指标 |
|----|------|
| 区分度 | AUROC, AUPRC |
| 校准 | 截距→0, 斜率→1, O:E→1, ECE, HL χ², per-bin CI |
| 整体 | Brier, Brier Skill Score |
| 分类 | MCC, LR+/LR-, Sens/Spec/PPV/NPV/F1 |
| 临床 | DCA 净效用, NRI, IDI |

## 关键要求

- **单次测试集评估**: 测试集在整个 Pipeline 中只被评估一次
- **Bootstrap CI ≥ 1000**: 所有主要指标（MLGG-E01）
- **多种子稳定性**: ≥ 5 seeds, std < 0.02（MLGG-R02）
- **Platt scaling**: 如果训练时用了 `class_weight='balanced'`，必须做事后校准（MLGG-E05）

## Gate 检查

**本阶段有 5 个 Gate。一次性全部运行，汇总所有报告后统一评审**（见 `review-protocol.md` 多 Gate 策略），不需要逐个跑逐个修。

```bash
# 1. 评估质量
python3 scripts/gates/evaluation_quality_gate.py \
  --evaluation-report evidence/evaluation_report.json \
  --metric-name pr_auc \
  [--ci-matrix-report evidence/ci_matrix_report.json] \
  --report evidence/evaluation_quality_report.json --strict

# 2. 校准 + DCA
python3 scripts/gates/calibration_dca_gate.py \
  --prediction-trace evidence/prediction_trace.json \
  --evaluation-report evidence/evaluation_report.json \
  [--external-validation-report evidence/external_validation_report.json] \
  --report evidence/calibration_dca_report.json --strict

# 3. CI 矩阵
python3 scripts/gates/ci_matrix_gate.py \
  --evaluation-report evidence/evaluation_report.json \
  --prediction-trace evidence/prediction_trace.json \
  --ci-matrix-report evidence/ci_matrix_report.json \
  [--external-validation-report evidence/external_validation_report.json] \
  --report evidence/ci_matrix_gate_report.json --strict

# 4. 指标一致性
python3 scripts/gates/metric_consistency_gate.py \
  --evaluation-report evidence/evaluation_report.json \
  --metric-name pr_auc \
  --report evidence/metric_consistency_report.json --strict

# 5. 置换检验（需要训练时加 --permutation-null-out）
python3 scripts/gates/permutation_significance_gate.py \
  --null-metrics-file evidence/permutation_null_metrics.json \
  --metric-name pr_auc \
  --actual <实际PR-AUC值> \
  --report evidence/permutation_report.json --strict
```

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| E01 | CRITICAL | 所有主要指标 95% CI（Bootstrap ≥ 1000） |
| E02 | CRITICAL | 完整指标面板（AUROC + 校准 + MCC + DCA） |
| E05 | WARNING | balanced 权重需事后 Platt 校准 |
| R02 | WARNING | 多种子稳定性 |

## 常见陷阱

- 只报 AUROC 不报校准 → NC 审稿人最常见的要求
- 校准斜率偏离 1.0 较大 → 过拟合信号
- CI 宽度过大 → 样本量不足的证据
- 小样本 (n<500) 报告过多小数位 → 过度精确

## 附加分析（推荐）

- `baseline_comparisons()` — 对比随机基线
- `feature_ablation()` — 特征消融实验
- `export_model_coefficients()` — 系数导出
- `compute_resource_report()` — 训练资源报告

## 完成后告诉用户

```
Phase 6 评估完成:
- AUROC: X.XX (95% CI: X.XX-X.XX)
- AUPRC: X.XX (95% CI: X.XX-X.XX)
- 校准斜率: X.XX, 截距: X.XX
- MCC: X.XX, Brier: X.XX
- DCA: 在阈值 X%-X% 范围内优于 treat-all
- 置换检验 p-value: X.XXX
[如校准不佳] 建议做 Platt scaling 校准。
```
