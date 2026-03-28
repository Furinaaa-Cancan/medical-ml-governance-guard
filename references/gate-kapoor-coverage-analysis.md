# 31-Gate ↔ Kapoor 2023 Leakage Taxonomy Coverage Analysis

**Version**: 1.0
**Date**: 2026-03-28
**Purpose**: 对照独立的外部分类法（Kapoor & Narayanan 2023），评估 MLGG 31-gate 框架的泄漏检测覆盖率，避免循环验证。

---

## 1. 外部参照标准

Kapoor S, Narayanan A. "Leakage and the reproducibility crisis in ML-based science." *Patterns*. 2023;4(9):100804.

该论文基于对 294 篇已发表论文的系统性回顾，提出了 8 种数据泄漏类型。这是目前最被广泛引用的 ML 泄漏分类体系。

## 2. 覆盖矩阵：Kapoor 8 型 × MLGG 31 Gate

| Kapoor 类型 | 定义 | MLGG Gate（运行时检测） | MLGG Lint（静态分析） | 覆盖评价 |
|------------|------|----------------------|---------------------|---------|
| **L1.1** No test set | 没有独立保留测试集 | `split_protocol_gate`（验证 train/valid/test 三分割存在性） | 无直接检测 | ✅ Gate 覆盖 |
| **L1.2** Preprocessing on full data | 预处理在全量数据上 fit | `leakage_gate`（检查 preprocessor fit 是否仅在 train）, `feature_engineering_audit_gate` | R001, R002, R011, R017, R020 | ✅ 双重覆盖（Gate + Lint） |
| **L1.3** Feature selection on full data | 特征选择在全量数据上执行 | `feature_engineering_audit_gate`（验证特征选择 scope = train_only）, `feature_lineage_gate` | R006 | ✅ 双重覆盖 |
| **L1.4** Duplicates across splits | 训练/测试集存在重复行/患者 | `leakage_gate`（row-hash overlap）, `split_protocol_gate`（entity-ID overlap） | 无（需运行时数据） | ✅ Gate 覆盖 |
| **L2** Illegitimate features | 使用索引时间后的特征或目标代理 | `definition_variable_guard`（表型定义泄漏）, `feature_lineage_gate`（特征来源追溯） | R007（仅目标变量作为特征） | ⚠️ 部分覆盖：检测 definition variable leak 和 target-as-feature，但不检测所有 post-index 特征（需要领域知识） |
| **L3.1** Temporal leakage | 训练数据包含测试期间的未来信息 | `leakage_gate`（temporal ordering: train_max < test_min）, `split_protocol_gate`（temporal protocol 验证） | R008（shuffle on temporal data） | ✅ 双重覆盖 |
| **L3.2** Non-independence | 同一患者出现在多个分割中 | `split_protocol_gate`（group_disjoint 检查）, `leakage_gate`（entity-ID overlap） | R004（split without groups） | ✅ 双重覆盖 |
| **L3.3** Sampling bias | 测试集不具有代表性 | `covariate_shift_gate`（train vs test 分布差异）, `distribution_generalization_gate`（分布泛化检查） | R015（small test set） | ⚠️ 部分覆盖：检测分布漂移和小测试集，但不检测系统性选择偏倚（需要领域知识） |

## 3. 覆盖率总结

| 评价 | 数量 | Kapoor 类型 |
|------|------|------------|
| ✅ 完全覆盖（Gate + Lint 双重） | 5/8 | L1.2, L1.3, L1.4, L3.1, L3.2 |
| ⚠️ 部分覆盖（检测部分但非全部子类型） | 2/8 | L2, L3.3 |
| ✅ Gate 覆盖（无 Lint 但 Gate 在运行时检测） | 1/8 | L1.1 |
| ❌ 未覆盖 | 0/8 | — |

**总覆盖率：8/8 类型有至少一个 gate 覆盖（100%）**
**完全覆盖率：6/8 类型有完整检测链（75%）**
**部分覆盖的 2 个类型需要领域知识辅助，MLGG 提供工具但不替代人类判断。**

## 4. MLGG 覆盖但 Kapoor 未列出的额外泄漏类型

MLGG 31-gate 还检测以下 Kapoor 2023 未明确列出的泄漏类型：

| 额外类型 | MLGG Gate | 说明 |
|---------|----------|------|
| **调参泄漏** | `tuning_leakage_gate`, `model_selection_audit_gate` | 超参数搜索使用测试数据 |
| **阈值泄漏** | `calibration_dca_gate` | 决策阈值在测试集上优化 |
| **缺失值泄漏** | `missingness_policy_gate` | 填充策略使用全量数据统计 |
| **类别不平衡泄漏** | `imbalance_policy_gate` | SMOTE/过采样在分割前执行 |
| **种子不稳定** | `seed_stability_gate` | 结果依赖于随机种子选择 |
| **报告偏倚** | `reporting_bias_gate` | 选择性报告有利结果 |

## 5. 与循环验证问题的关系

**问题**：消融实验（1,260 次运行）验证的是"MLGG gate 能否检出 MLGG 定义的 L1-L5 泄漏"——这是循环的。

**本文档的作用**：通过将 MLGG gate 映射到 Kapoor 的独立外部分类法，证明：
1. MLGG 的泄漏定义不是凭空发明的，而是对应已有学术共识
2. MLGG 的覆盖范围（8/8 类型）对齐了独立标准
3. 消融实验的 L1-L5 是 Kapoor 8 型的子集，不是自创类别

**这不能完全解决循环验证问题**（仍然缺少在独立标注数据上的外部验证），但降低了"自定义类别→自检测"的循环程度。

## 6. 已知局限

1. **L2（非法特征）的检测依赖 phenotype_definition_spec**——用户必须提供疾病定义变量列表，MLGG 才能自动检测。如果用户不提供，此类泄漏无法被自动发现。
2. **L3.3（采样偏倚）的完整检测需要领域知识**——covariate_shift_gate 检测统计分布差异，但不能判断差异是否"有意义"（如不同医院的收治标准差异）。
3. **Kapoor 论文中的"元数据泄漏"（如文件修改时间泄露标签信息）**——MLGG 不检测此类泄漏，但此类泄漏在医学 ML 中极罕见。
