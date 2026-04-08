# R001-R020 ↔ Kapoor Leakage Taxonomy Mapping

**Version**: 1.0
**Date**: 2026-03-27
**Purpose**: 建立 MLGG lint 规则（R001-R020）与 Kapoor & Narayanan 2023 八型泄漏分类法（L1.1-L3.3）之间的精确映射关系，用于 Phase 2 手动审计中的交叉验证。

---

## 1. Kapoor & Narayanan 八型泄漏分类法

来源：Kapoor S, Narayanan A. Leakage and the reproducibility crisis in ML-based science. *Patterns*. 2023;4(9):100804

| 代码 | 类型 | 定义 | 手动审计检查点 |
|------|------|------|--------------|
| L1.1 | No test set | 没有保留独立测试集，所有数据用于训练+验证 | 是否有 held-out test set？ |
| L1.2 | Preprocessing on full data | 预处理（标准化/填充/编码/PCA）在分割前对全量数据 fit | scaler/imputer 是否仅在 train 上 fit？ |
| L1.3 | Feature selection on full data | 特征选择在分割前对全量数据执行 | 特征选择是否仅在 train 上执行？ |
| L1.4 | Duplicates across splits | 训练/测试集之间存在行级或患者级重复 | 是否有行/患者重复？ |
| L2 | Illegitimate features | 使用了索引时间后的特征或目标变量的代理特征 | 是否使用了 post-index 或代理特征？ |
| L3.1 | Temporal leakage | 未尊重时间顺序（训练数据晚于测试数据） | 时间顺序是否被尊重？ |
| L3.2 | Non-independence | 同一患者出现在多个分割中 | 患者是否仅在一个分割中？ |
| L3.3 | Sampling bias | 测试集不具有代表性（选择偏倚） | 测试集是否具有代表性？ |

---

## 2. 完整映射表

### 2.1 R001-R020 → Kapoor 类型（正向映射）

| Rule ID | 规则名 | 严重性 | Kapoor 主类型 | Kapoor 次类型 | 映射依据 |
|---------|--------|--------|-------------|-------------|---------|
| R001 | fit-before-split | ERROR | **L1.2** | — | `fit()`/`fit_transform()` 在 `train_test_split` 之前调用 = 预处理泄漏 |
| R002 | scaler-fit-on-test | ERROR | **L1.2** | — | 预处理器在测试数据上 fit = 预处理泄漏 |
| R003 | resample-on-test | ERROR | **L1.2** | L3.3 | SMOTE/过采样用于测试集 = 预处理泄漏 + 测试集分布被改变（采样偏倚） |
| R004 | split-without-group | WARNING | **L3.2** | L1.4 | 分割时未指定 groups = 患者可能出现在多个分割 |
| R005 | threshold-on-test | ERROR | **L1.2** | — | 在测试集上优化阈值 = 使用测试信息调优（广义预处理泄漏） |
| R006 | feature-selection-on-full | ERROR | **L1.3** | — | 特征选择在分割前执行 = 特征选择泄漏 |
| R007 | target-as-feature | ERROR | **L2** | — | 目标变量出现在特征矩阵中 = 非法特征 |
| R008 | temporal-split-shuffle | WARNING | **L3.1** | — | 时间数据使用 shuffle split = 时间泄漏 |
| R009 | no-confidence-intervals | INFO | — | — | 统计报告问题，**不直接对应泄漏类型** |
| R010 | train-metric-as-final | WARNING | — | — | 报告偏倚问题，**不直接对应泄漏类型** |
| R011 | cv-internal-smote | ERROR | **L1.2** | — | CV 内部 SMOTE 未使用 Pipeline = 跨 fold 预处理泄漏 |
| R012 | cv-accuracy-imbalanced | WARNING | — | — | 评估方法问题，**不直接对应泄漏类型** |
| R013 | hardcoded-threshold | WARNING | — | — | 评估方法问题，**不直接对应泄漏类型** |
| R014 | label-encoder-on-features | WARNING | — | — | 编码方法问题，**不直接对应泄漏类型** |
| R015 | small-test-set | WARNING | **L3.3** | — | 测试集过小 → 不稳定估计 → 采样偏倚 |
| R016 | no-random-state | INFO | — | — | 可重复性问题，**不直接对应泄漏类型** |
| R017 | early-stop-on-test | ERROR | **L1.2** | — | `eval_set` 使用测试集 = 测试信息参与训练过程 |
| R018 | scaling-before-trees | INFO | — | — | 效率问题，**不直接对应泄漏类型** |
| R019 | multiple-comparison | INFO | — | — | 统计问题，**不直接对应泄漏类型** |
| R020 | global-clean-before-split | WARNING | **L1.2** | — | `fillna(df.mean())` 在分割前 = 预处理泄漏（填充值包含测试集信息） |

### 2.2 Kapoor 类型 → R001-R020（反向映射）

| Kapoor 类型 | 对应规则 | 检测覆盖率评估 |
|-------------|---------|---------------|
| **L1.1** No test set | *无直接规则* | ⚠️ **覆盖缺口**：MLGG lint 不检测"是否存在独立测试集"，因为这需要语义分析，非 AST 可检测。需在 Phase 2 手动检查。 |
| **L1.2** Preprocessing on full data | R001, R002, R003, R005, R011, R017, R020 | ✅ **覆盖充分**：7 条规则覆盖，检测面最广。 |
| **L1.3** Feature selection on full data | R006 | ✅ 单点覆盖。检测 `SelectKBest`/`SelectFromModel`/`RFE` 等在分割前实例化。 |
| **L1.4** Duplicates across splits | *无直接规则* | ⚠️ **覆盖缺口**：行/患者重复需要运行时数据检查，非静态分析可检测。由 `leakage_gate` 和 `split_protocol_gate`（33-gate 流程）覆盖。 |
| **L2** Illegitimate features | R007 | ⚠️ **部分覆盖**：R007 检测目标变量作为特征，但不检测 post-index 代理特征（需要领域知识）。由 `definition_variable_guard` 和 `feature_lineage_gate`（33-gate 流程）补充。 |
| **L3.1** Temporal leakage | R008 | ⚠️ **部分覆盖**：R008 检测时间数据使用 shuffle，但不检测更隐蔽的时间泄漏（如 future feature engineering）。由 `leakage_gate` temporal checks 补充。 |
| **L3.2** Non-independence | R004 | ⚠️ **部分覆盖**：R004 检测 split 时缺少 `groups=`，但仅在代码中使用 `train_test_split` 时触发。GroupKFold 等其他分割方式可能绕过检测。 |
| **L3.3** Sampling bias | R003, R015 | ⚠️ **部分覆盖**：R003 检测 SMOTE 改变分布，R015 检测小测试集。但无法检测系统性选择偏倚。 |

---

## 3. 覆盖矩阵（热力图视图）

```
              L1.1  L1.2  L1.3  L1.4  L2    L3.1  L3.2  L3.3
R001           ·     ●      ·     ·    ·      ·     ·     ·
R002           ·     ●      ·     ·    ·      ·     ·     ·
R003           ·     ●      ·     ·    ·      ·     ·     ○
R004           ·     ·      ·     ·    ·      ·     ●     ·
R005           ·     ●      ·     ·    ·      ·     ·     ·
R006           ·     ·      ●     ·    ·      ·     ·     ·
R007           ·     ·      ·     ·    ●      ·     ·     ·
R008           ·     ·      ·     ·    ·      ●     ·     ·
R011           ·     ●      ·     ·    ·      ·     ·     ·
R015           ·     ·      ·     ·    ·      ·     ·     ●
R017           ·     ●      ·     ·    ·      ·     ·     ·
R020           ·     ●      ·     ·    ·      ·     ·     ·

检测规则数:    0     7      1     0    1      1     1     2
覆盖评级:     ❌    ✅     ✅    ❌   ⚠️    ⚠️    ⚠️   ⚠️

● = 主映射   ○ = 次映射
```

**注**：R009, R010, R012, R013, R014, R016, R018, R019 不直接对应任何泄漏类型（属于统计/编码/报告问题），未在矩阵中列出。

---

## 4. 覆盖缺口与补偿机制

| 缺口 | 泄漏类型 | 为什么 lint 无法检测 | 补偿机制 |
|------|---------|-------------------|---------|
| L1.1 无测试集 | No test set | 需要理解完整代码执行流程 | Phase 2 手动审计 + LLM 代码评审 |
| L1.4 重复行 | Duplicates | 需要运行时数据访问 | 33-gate: `split_protocol_gate`, `leakage_gate` |
| L2 代理特征 | Illegitimate | 需要医学领域知识（诊断码→疾病定义） | 33-gate: `definition_variable_guard`, `feature_lineage_gate` |
| L3.1 隐蔽时序 | Temporal | 需要理解 feature engineering 时间窗口 | 33-gate: `leakage_gate` temporal checks |
| L3.2 深层依赖 | Non-independence | GroupKFold 等替代 API 可绕过 R004 | Phase 2 手动审计 |
| L3.3 系统偏倚 | Sampling bias | 需要理解采样设计意图 | Phase 2 手动审计 + metadata 评分（D1.temporal_split） |

---

## 5. Phase 2 审计中的使用方式

### 5.1 MLGG lint 结果 → Kapoor 类型转换

审计员在 Phase 2 手动审计时，按以下规则将 MLGG lint 发现转换为 Kapoor 类型：

```python
RULE_TO_KAPOOR = {
    "R001": ["L1.2"],
    "R002": ["L1.2"],
    "R003": ["L1.2", "L3.3"],
    "R004": ["L3.2"],
    "R005": ["L1.2"],
    "R006": ["L1.3"],
    "R007": ["L2"],
    "R008": ["L3.1"],
    "R011": ["L1.2"],
    "R015": ["L3.3"],
    "R017": ["L1.2"],
    "R020": ["L1.2"],
}
```

### 5.2 手动审计未发现但应检查的类型

由于 R001-R020 对 L1.1、L1.4 无覆盖，Phase 2 审计员**必须额外检查**：

1. **L1.1**：代码中是否存在独立的 `X_test` / `y_test` 分割？还是所有数据都用于 cross-validation？
2. **L1.4**：代码中是否有去重步骤？如果有 `patient_id` 字段，是否用于 group-aware split？

### 5.3 分歧判定

当 MLGG lint 和手动审计结论不一致时：

| 情况 | MLGG | 手动 | 处理 |
|------|------|------|------|
| **True Positive** | 有泄漏 | 有泄漏 | 一致，记录 Kapoor 类型 |
| **False Positive** | 有泄漏 | 无泄漏 | 检查：lint 规则是否因代码模式误触发？记录 FP 原因（如 Pipeline 包裹） |
| **True Negative** | 无泄漏 | 无泄漏 | 一致 |
| **False Negative** | 无泄漏 | 有泄漏 | 检查：缺口在哪个 Kapoor 类型？是否属于 §4 中的已知覆盖缺口？ |

---

## 6. 与 MLGG 内部泄漏分类法的对应关系

MLGG 内部使用 10 类泄漏分类（`references/leakage-taxonomy.md`），比 Kapoor 的 8 类更细：

| MLGG 内部类型 | 对应 Kapoor | MLGG lint 规则 |
|--------------|------------|---------------|
| 1. Split Contamination | L1.4 | — |
| 2. Group Leakage | L3.2 | R004 |
| 3. Temporal Look-Ahead | L3.1 | R008 |
| 4. Target Proxy Leakage | L2 | R007 |
| 5. Preprocessing Leakage | L1.2 | R001, R002, R003, R005, R011, R017, R020 |
| 5b. Missingness/Imputation Leakage | L1.2 | R020 |
| 6. Hyperparameter/Model Selection Leakage | L1.2 (广义) | R005, R017 |
| 7. Threshold/Calibration Leakage | L1.2 (广义) | R005 |
| 8. Post-Hoc Subgroup Fishing | — | R019 (间接) |
| 9. Data Merge Leakage | L3.1 | — |
| 10. (Checklist) | 全部 | 全部 |

**注**：Kapoor L1.1（无测试集）和 L1.3（特征选择泄漏）在 MLGG 内部分类中分别归入 Split Contamination 和 Preprocessing Leakage。Kapoor L3.3（采样偏倚）在 MLGG 中无独立类别，分散在 Group Leakage 和 Preprocessing Leakage 中。
