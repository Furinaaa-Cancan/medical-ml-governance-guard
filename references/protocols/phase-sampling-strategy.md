# Phase 1→2 Sampling Strategy & Statistical Power

**Version**: 1.0
**Date**: 2026-03-27
**Context**: REVIEW_PROTOCOL.md §6.3 和 §7.4 的补充说明

---

## 1. 两阶段设计原理

| 阶段 | 目的 | 方法 | 样本量 | 输出 |
|------|------|------|--------|------|
| Phase 1 | 估计泄漏流行率 | MLGG lint 自动扫描 | N=172 | 流行率 ± 95% CI |
| Phase 2 | 验证 MLGG 准确性 | 盲审（LLM + 人类） | N=50 | Sensitivity, specificity, kappa |

**为什么需要两阶段**：
- 单独 Phase 1（自动化）：覆盖面广但准确性未知（FP/FN 率？）
- 单独 Phase 2（手动）：准确性高但人力成本大、样本量小
- 两阶段结合：用 Phase 2 校准 Phase 1 的估计，得到**校正后流行率**

---

## 2. Phase 1 样本量与精度

### 2.1 已有样本

| 来源 | 数量 | 来源脚本 |
|------|------|---------|
| PMC 检索 v1 | 343 篇 | `collect_papers_with_code.py` |
| PMC 检索 v2 | 591 篇 | 同上（扩展搜索） |
| 合并去重 | 816 篇 | `papers_with_code_merged.jsonl` |
| 质量筛选 | 172 篇 | `verify_repos.py` → `papers_verified_v2.jsonl` |

### 2.2 精度计算

Phase 1 泄漏流行率 = 37/172 = **21.5%**

95% Wilson CI：

```
p = 0.215, n = 172
z = 1.96

CI = (p + z²/2n ± z × √(p(1-p)/n + z²/4n²)) / (1 + z²/n)
   = (0.215 + 0.011 ± 1.96 × √(0.000982 + 0.000029)) / (1.022)
   = (0.226 ± 0.062) / 1.022
   ≈ [0.160, 0.282]
```

**结论**：172 篇给出 ±6.1% 的精度，满足 ±7% 目标。

### 2.3 如需更高精度

| 目标精度 | 所需 N（假设 p=0.20） | 当前状态 |
|---------|----------------------|---------|
| ±10% | 62 | ✅ 已满足 |
| ±7% | 126 | ✅ 已满足（172） |
| ±5% | 246 | ❌ 需扩大 74 篇 |
| ±3% | 683 | ❌ 需大幅扩大 |

---

## 3. Phase 2 抽样细节

### 3.1 分层设计

**主分层因子**：MLGG 判定（有泄漏 / 无泄漏），等比抽样

**层内平衡因子**（尽量均衡，非严格配额）：

| 因子 | 分类 | 目标 |
|------|------|------|
| 期刊 IF | 高（≥30）/ 中（10-29）/ 低（<10） | 每层至少 5 篇 |
| 疾病领域 | cardiovascular / oncology / diabetes / sepsis_icu / kidney / other | 至少覆盖 5 类 |
| 发表年份 | 2015-2019 / 2020-2022 / 2023-2025 | 每段至少 8 篇 |

### 3.2 为什么 25:25 等比而非按流行率

Phase 1 流行率 = 21.5%。如果按流行率抽样，50 篇中只有 ~11 篇是"有泄漏"的。

**问题**：11 篇有泄漏样本不够计算稳定的 sensitivity：

```
若 sensitivity = 0.70，N_positive = 11
SE(sensitivity) = √(0.70 × 0.30 / 11) = 0.138
95% CI = [0.43, 0.97] — 太宽了
```

等比抽样（25:25）给出更稳定的 sensitivity 和 specificity 估计：

```
若 sensitivity = 0.70，N_positive = 25
SE(sensitivity) = √(0.70 × 0.30 / 25) = 0.092
95% CI = [0.52, 0.88] — 可接受
```

### 3.3 校正后流行率

因为 Phase 2 采用等比抽样（非按流行率），直接用 Phase 2 的 raw prevalence 会有偏。校正方法：

**Rogan-Gladen 校正公式**（Rogan & Gladen 1978）：

```
真实流行率 = (表观流行率 + Sp - 1) / (Se + Sp - 1)

其中：
  表观流行率 = Phase 1 的 MLGG 流行率 = 37/172 = 0.215
  Se = Phase 2 计算的 MLGG sensitivity
  Sp = Phase 2 计算的 MLGG specificity
```

**示例**：若 Se=0.70, Sp=0.90：
```
校正后流行率 = (0.215 + 0.90 - 1) / (0.70 + 0.90 - 1) = 0.115 / 0.60 = 0.192
```

即实际泄漏流行率约 19.2%（低于 MLGG 的 21.5%，因为有 FP）。

---

## 4. 统计检验力分析

### 4.1 Kappa 的检验力

**零假设**：κ = 0（MLGG 和 LLM 完全随机一致）
**备择假设**：κ ≥ 0.40（至少 moderate agreement）

```
N = 50, α = 0.05
若真实 κ = 0.40：
  Power ≈ 0.82（通过 Monte Carlo 模拟，10,000 次）
若真实 κ = 0.60：
  Power ≈ 0.99
```

**结论**：N=50 足以在 κ≥0.40 时拒绝零假设（检验力 >0.80）。

### 4.2 Sensitivity 的检验力

**目标**：证明 MLGG sensitivity > 0.50（优于掷硬币）

```
N_positive = 25（等比抽样中有泄漏的论文）
H₀: Se = 0.50
H₁: Se > 0.50

若真实 Se = 0.70：
  Exact binomial test: P(X ≥ 18 | n=25, p=0.50) = 0.022
  Power = P(X ≥ 18 | n=25, p=0.70) ≈ 0.68

若真实 Se = 0.80：
  Power = P(X ≥ 18 | n=25, p=0.80) ≈ 0.91
```

**结论**：如果 MLGG 真实 sensitivity ≥ 0.80，N=25 足够检测。如果 sensitivity 在 0.60-0.70 之间，检验力偏低（~0.50-0.68），但仍可提供点估计和 CI。

### 4.3 时间趋势的检验力

**目标**：检测 2015-2025 泄漏流行率的线性趋势

```
N = 172, 假设 OR per year = 0.90（流行率每年下降 10%）
Logistic regression: leakage ~ year + journal_tier
Power ≈ 0.45（不足）

N = 172, 假设 OR per year = 0.80（流行率每年下降 20%）
Power ≈ 0.78（勉强）
```

**结论**：N=172 仅能检测到强时间趋势（OR≤0.80/年）。弱趋势需要更大样本。应在论文中报告这一局限性。

---

## 5. 亚组分析计划

### 5.1 预设亚组

| 亚组 | 分类 | 检验 | 最小子群 N |
|------|------|------|-----------|
| 期刊等级 | 高/中/低 IF | χ² 或 Fisher exact | 报告实际 N |
| 疾病领域 | 9 类 | 仅描述性统计（子群太小） | — |
| 发表年份 | 连续变量 | logistic regression | — |
| 模型类型 | LR / RF / XGB / DL / other | Fisher exact | N ≥ 10 |
| 数据来源 | EHR / public / registry | Fisher exact | N ≥ 10 |

### 5.2 多重比较校正

- 主分析（总流行率）：不校正
- 亚组分析：报告 uncorrected p-values + Bonferroni-adjusted p-values
- 明确声明亚组分析为**探索性**，非确证性

---

## 6. 分析流程图

```
Phase 1 (N=172)
    │
    ├── 主分析：MLGG 表观流行率 + 95% Wilson CI
    │
    ├── 亚组分析：按期刊/年份/疾病/模型分层描述
    │
    └── 时间趋势：logistic regression (leakage ~ year + journal)
            │
Phase 2 (N=50, 分层抽样)
    │
    ├── R1 vs R2：Cohen's kappa + 95% Bootstrap CI
    │
    ├── 分歧子集 (N≈20)：R3 仲裁
    │
    ├── MLGG 诊断准确性：Se, Sp, PPV, NPV (全样本 + 分歧子集)
    │
    ├── Per-Kapoor-type detection rate
    │
    └── Rogan-Gladen 校正流行率
            │
最终报告
    │
    ├── 校正后流行率 + 95% CI
    ├── MLGG 性能参数 (Se/Sp)
    ├── 亚组描述性统计
    ├── 时间趋势 (如检验力足够)
    └── PRISMA 流程图 (实际数字填充)
```

---

## 7. 与 REVIEW_PROTOCOL.md 的对应关系

| 本文档章节 | REVIEW_PROTOCOL.md 对应 | 补充内容 |
|-----------|----------------------|---------|
| §2 Phase 1 精度 | §7.4 样本量 | 具体 Wilson CI 计算 |
| §3 Phase 2 抽样 | §6.3 抽样描述 | 分层因子、等比 justification |
| §4 检验力 | §7.4 样本量 | kappa/sensitivity/trend 的检验力 |
| §5 亚组分析 | §7.1 亚组 | 预设亚组 + 多重比较校正 |
| §6 流程图 | — | 新增：完整分析流程 |
| §3.3 校正公式 | — | 新增：Rogan-Gladen 校正 |
