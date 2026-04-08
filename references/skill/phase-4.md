# Phase 4: 特征选择

> **Pipeline 模式 (路径 A)**：Phase 3-6 由 `mlgg.py train` 一条命令自动完成，本文件不适用。
> **Research 模式 (路径 B)**：用户自己写特征选择代码时，按以下规则审查。

## 目标
在训练集内筛选稳定特征，排除共线性和泄漏来源。

## 前置条件
- Phase 3 评审通过：lint 无 ERROR + Agent 代码审查无 CRITICAL
- Pipeline 已确认编码/插补正确

## 执行步骤（内嵌在 train_select_evaluate.py）

1. **过滤**: 缺失率 + 方差阈值 → `select_features_by_filter()`
2. **稳定性频率**: L1 LogisticRegression bootstrap（50 次子采样）→ `feature_stability_frequency()`
3. **分组排序**: (相关性 × 稳定性) 排序，每组保留 top-K → `group_preselect_features()`
4. **VIF 共线性**: `compute_vif()` — >10 → CRITICAL
5. **非线性检验**: `check_nonlinearity()` — LR test

## Gate 检查

```bash
# 如果 configs/feature-lineage.json 不存在，先从模板创建:
#   cp references/feature-lineage.example.json configs/feature-lineage.json
#   然后根据实际特征来源编辑（记录每个特征的来源和时间归属）
python3 scripts/gates/feature_lineage_gate.py \
  --lineage configs/feature-lineage.json \
  --report evidence/lineage_report.json \
  --strict
```

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| F01 | CRITICAL | 禁止标签作特征 |
| F02 | CRITICAL | 禁止使用预测时间点后的信息 |
| F03 | CRITICAL | 特征选择只在训练集内 |
| F05 | CRITICAL | 必须定义预测时间点 |

## 常见陷阱

- 在全量数据上做特征选择 → 信息泄漏到测试集
- VIF > 10 的特征对未被标记
- 选择后 EPV 降到阈值以下（特征减少但正类数不变）
- 稳定性选择的子采样次数太少（< 30 不可靠）

## ⚠️ 文档与代码差异

- README 中"Elastic Net CV 联合调 α/λ"是推荐方法论，代码用 L1 bootstrap 稳定性
- "Meinshausen 误选界"和"Ridge 全量对照"是推荐分析步骤，当前未自动执行

## 完成后告诉用户

```
Phase 4 特征选择完成:
- 过滤: XX 个因缺失/低方差移除
- 稳定性: XX 个特征被选中（频率 > 阈值）
- VIF: [最高 XX，通过/有 XX 个 >10 需处理]
- 非线性: [X 个特征有非线性信号]
- 最终特征数: XX → 进入 Phase 5 训练
- EPV 重检: [仍满足/需注意]
```
