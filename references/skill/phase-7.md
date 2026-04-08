# Phase 7: SHAP 可解释性

## 目标
多模型 SHAP 集成，验证特征重要性一致性，生成个案解释。

## 前置条件
- Phase 6 评审通过：`evidence/evaluation_quality_report.json` 和 `evidence/calibration_dca_report.json` 存在且 status=pass
- `evidence/model_pool.pkl` 和 `data/train.csv`, `data/test.csv` 存在

## 执行命令

```bash
python3 scripts/gates/shap_interpretability_gate.py \
  --model-pool evidence/model_pool.pkl \
  --train-data data/train.csv \
  --test-data data/test.csv \
  --target-col y \
  --report evidence/shap_report.json
```

预期耗时: 2-10 分钟（KernelExplainer 可能较慢）。
大数据 (>100K) → 跳过 KernelExplainer，用 TreeExplainer。

## 方法

1. 每个模型族独立计算 SHAP 值
2. L1 归一化 → 消除模型间尺度差异
3. 等权平均 → 集成排名
4. Kendall τ 一致性 + Top-N Jaccard → 验证多模型是否"看到"同样的信号

## 产出（4 张 CSV）

| 文件 | 内容 |
|------|------|
| A | 集成特征排名 |
| B | 逐模型 SHAP 值 |
| C | 一致性矩阵（Kendall τ, Jaccard） |
| D | 个案解释（高概率/低概率样本） |

## 评审要点

- Kendall τ < 0.5 → 模型间不一致，结论不稳定，WARNING
- Top-5 特征跨模型一致 → 结论稳健
- 泄漏检查：SHAP top-1 如果是 Phase 1 黑名单变量 → CRITICAL
- 校准斜率偏离 1.0 → 可能过拟合

## 完成后告诉用户

```
Phase 7 SHAP 可解释性完成:
- 集成 Top-5 特征: [feature_1, feature_2, ...]
- 模型间一致性: Kendall τ = X.XX
- Top-5 Jaccard: X.XX
- [一致性评估: 高/中/低]
```
