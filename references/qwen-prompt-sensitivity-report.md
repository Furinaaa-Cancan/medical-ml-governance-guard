# Qwen Methods Review: Prompt Sensitivity Report

**Version**: 1.0
**Date**: 2026-03-28
**Purpose**: 透明报告两个 prompt 版本的结果差异，避免选择性报告。

---

## 1. 背景

Qwen Methods 审查使用 LLM（qwen-plus）读取论文 Methods 节，按 12 维度 + Kapoor 泄漏分类评估方法学严谨性。

我们发现 **prompt 设计对结果有决定性影响**。同一组 50 篇论文，两个 prompt 的结论截然不同。

## 2. 两版 Prompt 对比

### Prompt v1（"absence = problem"）

核心逻辑：如果 Methods 没有明确描述某个实践，则判定为问题。
```
"Flag ANY of these if detected:
- L1.2: Preprocessing on combined train+test data before splitting"
```

### Prompt v2（"confirmed only"）

核心逻辑：只标记 Methods 文本**明确描述了错误做法**的情况。"没提到"归为 reporting gap，不归为泄漏。
```
"ONLY flag a leakage type if the text provides POSITIVE EVIDENCE.
Do NOT flag based on absence of information."
```

## 3. 结果对比

| 指标 | Prompt v1 | Prompt v2 | 变化 |
|------|----------|----------|------|
| 成功审查 | 46/50 | 45/50 | -1（API 错误） |
| **泄漏流行率** | **100%** | **17.8%** | -82 个百分点 |
| 平均得分 | 4.3/24 | 8.2/24 | +91% |
| Not publishable | 27 (59%) | 12 (27%) | -32pp |
| Major issues | 18 (39%) | 27 (60%) | +21pp |
| Solid | 1 (2%) | 6 (13%) | +11pp |
| Publication-grade | 0 | 0 | — |

### Grade 分布对比

```
Prompt v1:  ████████████████████████████░  Not publishable (59%)
            ████████████████░░░░░░░░░░░░░  Major issues (39%)
            ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  Solid (2%)

Prompt v2:  ████████░░░░░░░░░░░░░░░░░░░░░  Not publishable (27%)
            ████████████████████░░░░░░░░░░  Major issues (60%)
            ████░░░░░░░░░░░░░░░░░░░░░░░░░  Solid (13%)
```

## 4. 为什么差异这么大

| 因素 | Prompt v1 的行为 | Prompt v2 的行为 |
|------|-----------------|-----------------|
| Methods 没提预处理隔离 | 标记 L1.2（泄漏） | 标记为 reporting gap |
| Methods 没提 TRIPOD | 给 D8 = 0 | 给 D8 = 0（相同） |
| Methods 说"我们用了 StandardScaler" | 标记 L1.2（没说 train-only） | 标记 [AMBIGUOUS]，不标记泄漏 |
| Methods 说"scaler fit on full data" | 标记 L1.2 | 标记 L1.2 [CONFIRMED] |

**核心差异**：v1 把"沉默"当作"有罪"；v2 把"沉默"当作"未知"。

## 5. 哪个更接近真实？

基于 Methods vs Code 交叉比对（N=43 匹配论文）：

| 指标 | Prompt v1 | Prompt v2 | Code review (Claude) |
|------|----------|----------|---------------------|
| 泄漏论文数 | 43/43 (100%) | 6/43 (14%) | 18/43 (42%) |
| Agreement with code | 38.6% | 53.5% | — (reference) |

**Prompt v2 与代码审查的一致性（53.5%）高于 v1（38.6%）**。

但更重要的是**两个 prompt 都不完美**：
- v1 严重高估（100% vs 代码审查 42%）
- v2 可能低估（14% vs 代码审查 42%）
- 真实值可能在两者之间

## 6. 推荐使用方式

1. **不应单独使用任一 prompt 的结果作为泄漏流行率**
2. **Prompt v2 适合用于**：从 Methods 文本中提取已确认的方法学问题
3. **Prompt v1 适合用于**：生成完整的 reporting gap 列表（Methods 应该报告但没有报告的内容）
4. **两者结合**：v2 的 `leakage_flags` + v1 的 `reporting_gaps` 提供最完整的审查

## 7. 对论文的影响

如果报告 Methods 审查结果，**必须同时报告两个版本**：

> "Qwen Methods review with a 'confirmed-only' prompt identified methodological leakage in 17.8% of papers. A more aggressive prompt treating unreported practices as potential problems flagged 100%. The true Methods-detectable prevalence likely lies between these bounds. Code review (independent of Methods review) identified leakage in 42% of the same papers, suggesting Methods text substantially underreports actual implementation flaws."
