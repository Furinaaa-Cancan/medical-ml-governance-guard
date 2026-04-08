# Phase 3: 预处理

> **Pipeline 模式 (路径 A)**：Phase 3-6 由 `mlgg.py train` 一条命令自动完成，本文件不适用。
> **Research 模式 (路径 B)**：用户自己写预处理代码时，按以下规则审查。

## 目标
编码、插补、缩放——全部只在训练集上 fit，保证 Pipeline 隔离。

## 前置条件
- Phase 2 评审通过：`evidence/leakage_report.json` 存在且 status=pass
- `data/train.csv` 和 `data/test.csv` 存在

## 关键事实

**预处理内嵌在 `train_select_evaluate.py` 的 sklearn Pipeline 中，不是独立脚本。**

Pipeline 结构: `Imputer → Scaler → Classifier`
- 每一步只在训练集 fit，验证/测试集只做 transform

## 处理逻辑

### 编码
- Binary → 0/1（OOD → 0.5）
- Categorical → OneHot（OOD → 全零）
- Numeric → 保持

### 插补
- 默认: `SimpleImputer(median)` + missing indicator 列
- 可选: `IterativeImputer` (MICE)，大数据自动降级
- 树模型 (RF/XGB/LGBM/CatBoost): 不添加 indicator（原生处理缺失）

### 缩放
- `StandardScaler`（LR/SVM 必须，树模型统一应用）

### 不平衡处理
- **不用 SMOTE**（van den Goorbergh 2022: 损害校准）
- 改用 `class_weight='balanced'`
- 使用 balanced 权重 → Phase 6 必须做 Platt 校准

## 本阶段规则

| ID | 严重度 | 规则 |
|----|--------|------|
| P01 | CRITICAL | 所有 fit() 只在训练集 |
| P02 | CRITICAL | SMOTE 仅训练集，慎用 |
| P03 | CRITICAL | 分割前不做全局 dropna/clip/quantile |
| P04 | CRITICAL | 填补统计量只从训练集计算 |
| P05 | CRITICAL | 编码匹配语义（名义 → OneHot，序数 → Ordinal 需验证单调性） |
| P06 | WARNING | 缺失按机制分层 |

## Agent 必须检查的陷阱

- 名义变量被当数值（race=1,2,3 直接给 LR）→ 确认 OneHot 已执行
- 有序变量假设单调性不成立 → 确认 ordinal 是合理的
- 缺失率 >80% 的列是否需要丢弃
- 编码后特征数暴增（>200 列考虑跳过 VIF）

## 评审循环（Lint + 人工审查模式）

本阶段没有独立 Gate 脚本。评审循环按以下步骤执行：

**Step 1: Lint 扫描**
```bash
# 如果有手动预处理脚本
python3 scripts/orchestration/mlgg.py lint check <preprocessing_script.py>
```

**Step 2: Agent 逐项代码审查**
1. 检查 Pipeline 构建代码，确认所有 fit() 只作用于训练集
2. 确认编码方式匹配变量语义（名义 → OneHot，不能 Ordinal）
3. 确认无分割前的全局预处理（dropna/clip/quantile）
4. 确认 SMOTE 未被使用，或仅在训练集内使用

**Step 3: 发现问题时**
- 按标准格式输出 `[MLGG-P0X] CRITICAL: ...`
- 修复代码
- 重新执行 Step 1-2 审查
- 最多 3 轮

**Step 4: 全部通过 → Phase 总结卡**

## 完成后告诉用户

```
Phase 3 预处理完成（全部 fit on train only）:
- 编码: XX categorical → OneHot, XX binary → 0/1
- 插补: [SimpleImputer median / MICE]
- 缩放: StandardScaler
- 编码后特征数: XX（原始 XX → 编码后 XX）
- 定义变量 [hba1c, ...] 已排除
- 不平衡处理: class_weight='balanced'（Phase 6 需 Platt 校准）
```
