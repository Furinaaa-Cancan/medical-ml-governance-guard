# MLGG 论文实验方案

## 论文定位

**标题方向**: "ML Governance Guard: A 33-Gate Automated Methodology Verification Framework for Medical Prediction Models"

**目标期刊**: JAMIA / J Clin Epidemiol / Nature Methods (Application Note)

**核心 claim**: MLGG 能以接近人类审稿人的精度自动检测已发表医学 ML 论文中的方法学缺陷。

---

## 实验设计（5 个实验）

### Experiment 1: Prevalence Study — 已发表论文泄漏率
**目的**: 回答 "有多少已发表医学 ML 论文存在可检测的方法学问题？"

**方法**:
1. 用 `scan_published_repos.py` 从 PMC/PaperWithCode 收集 ≥100 个有 Python 代码的已发表医学 ML 论文
2. 用 MLGG lint (25 rules) 自动扫描所有 repo
3. 报告: 泄漏率、最常见泄漏类型、按期刊/年份/疾病分层

**产出**: Table 1 — Prevalence of methodological issues by type
**脚本**: `scan_published_repos.py` (已有), `e3_lint_accuracy.py` (已有)

**样本量论证**: N≥100 repos, 假设泄漏率 60% (Kapoor 2023), 则 95% CI ≈ ±10%

---

### Experiment 2: Red Team Validation — Synthetic Benchmark
**目的**: 验证 MLGG lint + agent 的检出率和误报率

**方法**: 已完成 — 40 个红队测试场景，覆盖 25 种泄漏模式
- 已知 ground truth (每个场景明确标注 BUG 位置)
- 三层架构分别评估

**产出**: Table 2 — Detection rates by layer and difficulty
```
| Layer | Easy (R1) | Medium (R2) | Hard (R3) | Extreme (R4) | Total |
|-------|-----------|-------------|-----------|---------------|-------|
| Lint  | 8/10      | 8/10        | 5/10      | 3/10          | 24/40 |
| +Agent| +2        | +2          | +4        | +5-7          | +13-15|
| Total | 10/10     | 10/10       | 9/10      | 8-10/10       | 37-39 |
```

**脚本**: 红队文件已在 /tmp/mlgg_redteam*/ — 需移入 experiments/paper/redteam/

---

### Experiment 3: Concordance with Human Reviewers — Peer Review KB Validation
**目的**: MLGG 的发现和真实审稿人的意见有多一致？

**方法**:
1. 从 peer-review-kb.json 中选 20 篇有公开代码的论文
2. 对每篇论文: (a) 用 MLGG lint 扫描代码 (b) 提取审稿人的方法学意见
3. 计算 concordance:
   - MLGG 发现的问题中，有多少在审稿意见中也出现？(precision proxy)
   - 审稿人指出的方法学问题中，有多少 MLGG 也能检测？(recall proxy)

**产出**: Table 3 — MLGG vs Human Reviewer Concordance
**关键指标**: Cohen's κ (agreement), precision, recall

**这是论文最核心的实验** — 直接回答 "MLGG 能否达到人类审稿人水平？"

---

### Experiment 4: Deflation Study — 泄漏修复后性能下降多少？
**目的**: 量化泄漏对报告性能的实际影响

**方法**:
1. 选 5-10 个有泄漏的论文 repo (Experiment 1 检出的)
2. 记录原始报告的 AUROC
3. 修复泄漏 (按 MLGG 建议)
4. 重跑代码，记录修复后 AUROC
5. 计算 deflation = AUROC_original - AUROC_fixed

**产出**: Figure 1 — Performance deflation after leakage repair
**脚本**: `run_deflation_experiment.py` (已有), `build_leaky_pipeline.py` (已有)

**假设**: 预期 deflation 0.02-0.15 AUROC (基于 Kapoor 2023 报告)

---

### Experiment 5: Gate Ablation — 每个 gate 的边际贡献
**目的**: 哪些 gate 贡献最大？33 个都需要吗？

**方法**:
1. 对 Experiment 1 的 ≥100 个 repo
2. 逐个禁用 gate，计算对总检出率的影响
3. 报告: gate 重要性排序、最小必要 gate 子集

**产出**: Figure 2 — Gate importance ranking (ablation study)
**脚本**: `run_gate_ablation.py` (已有)

**意义**: 为 L1/L2/L3 合规层级提供实证依据

---

## 执行优先级

```
优先级 1 (最核心 — 论文成立的基础):
  Exp 3: Concordance with Human Reviewers  ← 直接证明 MLGG = 人类审稿人水平
  Exp 1: Prevalence Study                  ← 证明问题严重性

优先级 2 (增强说服力):
  Exp 4: Deflation Study                   ← 量化泄漏的实际危害
  Exp 2: Red Team Validation               ← 已完成，整理数据即可

优先级 3 (补充分析):
  Exp 5: Gate Ablation                     ← 框架设计合理性论证
```

---

## 数据需求

| 实验 | 需要的数据 | 来源 | 工作量 |
|------|-----------|------|--------|
| Exp 1 | ≥100 个有代码的论文 repo | PMC + PaperWithCode | 搜索 1 天 + 筛选 2 天 |
| Exp 2 | 40 个红队脚本 | 已完成 | 整理 0.5 天 |
| Exp 3 | 20 篇 NC 论文 + 代码 + 审稿意见 | peer-review-kb.json | 匹配 1 天 + 分析 2 天 |
| Exp 4 | Exp 1 中 5-10 个有泄漏的 repo | Exp 1 产出 | 修复 + 重跑 3-5 天 |
| Exp 5 | Exp 1 的全部结果 | Exp 1 产出 | 分析 1 天 |

**总工期预估**: 2-3 周（以 Exp 3 + Exp 1 为主线）

---

## 论文结构草案

```
Abstract
1. Introduction
   - Problem: 86% → 94% high ROB in medical ML
   - Gap: No automated code-level verification tool
   - Contribution: MLGG framework + empirical validation

2. Methods
   2.1 MLGG Architecture (33 gates, 3 layers, 25 lint rules)
   2.2 Peer Review Knowledge Base (107 NC papers, 375 concerns)
   2.3 Experiment Design (Exp 1-5)

3. Results
   3.1 Prevalence of methodological issues (Exp 1) → Table 1
   3.2 Detection accuracy (Exp 2) → Table 2
   3.3 Concordance with human reviewers (Exp 3) → Table 3 + Figure
   3.4 Performance deflation (Exp 4) → Figure 1
   3.5 Gate importance (Exp 5) → Figure 2

4. Discussion
   - MLGG vs existing approaches (tool_comparison_matrix.json)
   - Limitations: binary only, semantic issues need agent, etc.
   - Implications for journals, reviewers, researchers

5. Conclusion
```

---

## 伦理考虑

- 不公开指名批评特定论文 — 报告聚合统计量
- 审稿意见来自公开数据（NC 开放审稿）— 无隐私问题
- 代码扫描不涉及患者数据 — 只分析代码结构
