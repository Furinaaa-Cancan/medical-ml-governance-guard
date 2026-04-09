# Blind Audit & Inter-Method Agreement Protocol

**Version**: 1.0
**Date**: 2026-03-27
**Applies to**: Phase 2 of the systematic review (REVIEW_PROTOCOL.md §6.3)

---

## 1. Overview

Phase 2 手动审计采用**三审员盲审 + 分歧仲裁**设计，用于：
1. 验证 MLGG lint（Phase 1）的检测灵敏度和特异度
2. 建立 Kapoor 八型泄漏分类的 ground truth
3. 计算 inter-method agreement（Cohen's kappa）

---

## 2. 抽样设计

### 2.1 抽样策略

从 Phase 1 的 N=172 篇论文中，采用**分层随机抽样**选取 N=50：

| 分层 | MLGG 判定 | 目标数量 | 抽样依据 |
|------|----------|---------|---------|
| 层 1 | 有泄漏（≥1 ERROR） | 25 | 从 37 篇中随机抽 25 |
| 层 2 | 无泄漏（0 ERROR） | 25 | 从 135 篇中随机抽 25 |

**分层因子**（层内平衡）：
- 期刊等级：高 IF（≥30）/ 中 IF（10-29）/ 低 IF（<10），各层尽量均衡
- 疾病领域：至少覆盖 5 个疾病类别
- 发表年份：覆盖 2015-2025 的时间跨度

### 2.2 抽样实现

```python
import random
random.seed(42)  # 固定种子，可复现

# Phase 1 结果
leaky = [p for p in papers if p["has_leakage_error"]]
clean = [p for p in papers if not p["has_leakage_error"]]

# 分层随机抽样
sample_leaky = random.sample(leaky, min(25, len(leaky)))
sample_clean = random.sample(clean, min(25, len(clean)))

blind_sample = sample_leaky + sample_clean
random.shuffle(blind_sample)  # 打乱顺序，消除审计员偏倚
```

### 2.3 样本量 justification

- N=50 对于计算 kappa 的 95% CI 足够（Sim J, Wright CC. J Clin Epidemiol 2005;58(10):982-984：N≥50 for kappa with 2 categories）
- 25:25 等比分层确保 sensitivity 和 specificity 都有充足样本
- 层内平衡按期刊/疾病/年份确保结论不被单一子群驱动

---

## 3. 盲审协议

### 3.1 审员角色

| 审员 | 身份 | 输入 | 输出 | 盲审状态 |
|------|------|------|------|---------|
| Reviewer 1（R1） | MLGG lint 自动扫描 | GitHub 代码 | R001-R020 发现列表 | — （自动化，无偏倚） |
| Reviewer 2（R2） | LLM（Claude）独立评审 | GitHub 代码（原始） | Kapoor 8 型判定 + 逐行证据 | **盲于 R1 结果** |
| Reviewer 3（R3） | 人类领域专家 | GitHub 代码 + R1/R2 分歧报告 | 最终裁定 | 仅在分歧子集上介入 |

### 3.2 盲审实施

**R2（LLM）盲审规则**：
1. R2 接收的输入**不包含** MLGG lint 的任何输出
2. R2 接收的 prompt **不提及** R1 的判定结果
3. R2 独立阅读代码，按 Kapoor 8 型逐项判定
4. R2 的输出格式与 R1 独立（R2 输出 Kapoor 类型，R1 输出 R0xx 规则）

**实施步骤**：

```
1. 生成盲审列表（blind_audit_list.jsonl）
   - 包含：paper_id（UUID，非原始 ID）、github_url、title
   - 不包含：MLGG lint 结果、Phase 1 判定

2. R1 扫描（自动）
   - 输入：github_url
   - 输出：{paper_uuid: {rules_triggered, has_leakage, findings}}
   - 存储：blind_audit_r1.jsonl（审计完成前不暴露给 R2）

3. R2 评审（LLM）
   - 输入：github_url（从 blind_audit_list.jsonl 读取）
   - Prompt：独立评审，不引用 MLGG
   - 输出：{paper_uuid: {kapoor_types, evidence_lines, verdict}}
   - 存储：blind_audit_r2.jsonl

4. 揭盲 + 比对
   - 将 R1 和 R2 的结果按 paper_uuid 合并
   - 计算 agreement metrics

5. R3 仲裁（仅分歧子集）
   - R3 接收：R1 发现 + R2 发现 + 代码链接
   - R3 裁定：最终 ground truth
```

### 3.3 UUID 匿名化

为防止审计员从 paper_id 反推 MLGG 判定，使用 UUID 替代原始 ID：

```python
import uuid
paper_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, paper["github_url"]))
```

---

## 4. 审计工具（R2 - LLM 评审）

### 4.1 Prompt 模板

```
你是一位医学 ML 方法学审稿人。请独立审查以下 GitHub 仓库的 Python 代码，
判断是否存在数据泄漏。

**仓库 URL**: {github_url}
**论文标题**: {title}

请按以下 8 种泄漏类型逐项检查：

1. L1.1 No test set — 代码中是否有独立的 held-out test set？
2. L1.2 Preprocessing on full data — scaler/imputer 是否仅在 train 上 fit？
3. L1.3 Feature selection on full data — 特征选择是否仅在 train 上执行？
4. L1.4 Duplicates across splits — 代码中有无去重/group-aware split？
5. L2 Illegitimate features — 是否使用了 post-index 特征或目标代理？
6. L3.1 Temporal leakage — 时间顺序是否被尊重？
7. L3.2 Non-independence — 同一患者是否可能出现在多个分割中？
8. L3.3 Sampling bias — 测试集选取是否有代表性？

对每种类型，请给出：
- 判定：PRESENT / ABSENT / CANNOT_ASSESS
- 证据：具体代码文件和行号
- 置信度：HIGH / MEDIUM / LOW

最终判定：该论文是否存在数据泄漏？（YES / NO / UNCLEAR）
```

### 4.2 R2 输出格式

```json
{
  "paper_uuid": "xxx",
  "reviewer": "R2_LLM",
  "review_timestamp": "2026-03-27T10:00:00Z",
  "kapoor_assessment": {
    "L1.1": {"verdict": "ABSENT", "evidence": "train_test_split() at line 45 of train.py", "confidence": "HIGH"},
    "L1.2": {"verdict": "PRESENT", "evidence": "StandardScaler().fit(X) at line 23 — before split at line 45", "confidence": "HIGH"},
    "L1.3": {"verdict": "ABSENT", "evidence": "SelectKBest after split at line 52", "confidence": "MEDIUM"},
    "L1.4": {"verdict": "CANNOT_ASSESS", "evidence": "No patient_id column visible", "confidence": "LOW"},
    "L2": {"verdict": "ABSENT", "evidence": null, "confidence": "MEDIUM"},
    "L3.1": {"verdict": "ABSENT", "evidence": "No temporal features", "confidence": "MEDIUM"},
    "L3.2": {"verdict": "CANNOT_ASSESS", "evidence": "No group information", "confidence": "LOW"},
    "L3.3": {"verdict": "ABSENT", "evidence": "test_size=0.2, standard split", "confidence": "MEDIUM"}
  },
  "overall_verdict": "YES",
  "overall_confidence": "HIGH",
  "leakage_types_found": ["L1.2"],
  "summary": "Preprocessing leakage: StandardScaler fitted on full dataset before train/test split."
}
```

---

## 5. Inter-Method Agreement 计算

### 5.1 二值化判定

为计算 kappa，将三审员的判定统一为二值：

| 审员 | 判定"有泄漏"的条件 |
|------|-------------------|
| R1 (MLGG) | `has_leakage_error == true`（≥1 个 ERROR 级别发现） |
| R2 (LLM) | `overall_verdict == "YES"` |
| R3 (Human) | 最终裁定为 "有泄漏" |

**CANNOT_ASSESS / UNCLEAR 处理**：
- R2 的 `overall_verdict == "UNCLEAR"` 视为 **NO**（保守：不确定 ≠ 有泄漏）
- 如果某篇论文 R2 判定 ≥50% 的类型为 CANNOT_ASSESS，标记为 **跳过**，不纳入 kappa 计算

### 5.2 Cohen's Kappa 计算

**公式**：

```
κ = (p_o - p_e) / (1 - p_e)

其中：
  p_o = 观察一致率 = (TP + TN) / N
  p_e = 期望一致率 = p_yes × q_yes + p_no × q_no

  p_yes = R1 判定"有泄漏"的比例
  q_yes = R2 判定"有泄漏"的比例
  p_no  = R1 判定"无泄漏"的比例
  q_no  = R2 判定"无泄漏"的比例
```

**Kappa 解释**（Landis JR, Koch GG. Biometrics 1977;33(1):159-174）：

| κ 范围 | 一致性 | 行动 |
|-------|--------|------|
| < 0.00 | 低于随机 | 重新审视审计标准 |
| 0.00 – 0.20 | Slight | 审计标准需校准 |
| 0.21 – 0.40 | Fair | 可接受但需报告局限性 |
| 0.41 – 0.60 | Moderate | 可接受 |
| 0.61 – 0.80 | Substantial | 良好 |
| 0.81 – 1.00 | Almost perfect | 优秀 |

### 5.3 Bootstrap CI for Kappa

```python
import numpy as np

def bootstrap_kappa_ci(r1_verdicts, r2_verdicts, n_boot=2000, alpha=0.05):
    """Bootstrap 95% CI for Cohen's kappa."""
    kappas = []
    n = len(r1_verdicts)
    for _ in range(n_boot):
        idx = np.random.choice(n, size=n, replace=True)
        r1_boot = [r1_verdicts[i] for i in idx]
        r2_boot = [r2_verdicts[i] for i in idx]
        kappas.append(cohens_kappa(r1_boot, r2_boot))
    return np.percentile(kappas, [alpha/2*100, (1-alpha/2)*100])
```

### 5.4 MLGG 诊断准确性（以 R3 为 Ground Truth）

仅在 R3 参与的分歧子集（N≈20）上计算：

```
Sensitivity = TP / (TP + FN)    — MLGG 检出真正有泄漏的论文的比例
Specificity = TN / (TN + FP)    — MLGG 正确放行无泄漏论文的比例
PPV = TP / (TP + FP)            — MLGG 报告泄漏的论文中真正有泄漏的比例
NPV = TN / (TN + FN)            — MLGG 报告无泄漏的论文中真正无泄漏的比例
```

> **注意**：分歧子集的 sensitivity/specificity 不能直接推广到全样本（选择偏倚：分歧子集是困难案例）。全样本的 sensitivity/specificity 需要用全部 50 篇的结果计算。

---

## 6. 分歧仲裁规则

### 6.1 触发条件

以下情况触发 R3 仲裁：

| 情况 | R1 (MLGG) | R2 (LLM) | 处理 |
|------|-----------|-----------|------|
| 一致：有泄漏 | YES | YES | 无需仲裁，记录为 TP |
| 一致：无泄漏 | NO | NO | 无需仲裁，记录为 TN |
| **分歧：MLGG 有、LLM 无** | YES | NO | → R3 仲裁 |
| **分歧：MLGG 无、LLM 有** | NO | YES | → R3 仲裁 |
| R2 不确定 | — | UNCLEAR | → R3 仲裁（如果 R1 有明确判定） |

### 6.2 R3 仲裁流程

1. R3 接收：R1 的具体发现（规则 ID、文件、行号）+ R2 的 Kapoor 类型判定 + 代码仓库 URL
2. R3 独立审查代码
3. R3 给出最终裁定：
   - **CONFIRMED_LEAKAGE**：确认存在泄漏，指定 Kapoor 类型
   - **FALSE_POSITIVE**：R1/R2 的判定为误报，说明原因
   - **UNCERTAIN**：代码信息不足以判定（标记为排除项）

### 6.3 最终 Ground Truth 确定

```
if R1 == R2:
    ground_truth = R1  # 一致判定直接采用
elif R3 exists:
    ground_truth = R3  # 分歧由 R3 仲裁
else:
    ground_truth = EXCLUDED  # 无法判定，排除
```

---

## 7. 报告输出

### 7.1 混淆矩阵

```
                  Ground Truth
                  有泄漏    无泄漏
MLGG 判定  有泄漏   TP        FP
           无泄漏   FN        TN
```

### 7.2 报告模板

```markdown
## Inter-Method Agreement Results

- **Sample size**: N=50 (25 MLGG-positive, 25 MLGG-negative)
- **Excluded**: X papers (R2 CANNOT_ASSESS > 50%)
- **Auditable**: N-X papers

### Confusion Matrix (MLGG vs R2-LLM)
|           | LLM: YES | LLM: NO |
|-----------|----------|---------|
| MLGG: YES |    TP    |    FP   |
| MLGG: NO  |    FN    |    TN   |

### Agreement Metrics
- Cohen's κ = X.XX (95% CI: X.XX – X.XX)
- Observed agreement (p_o) = X.XX
- Expected agreement (p_e) = X.XX

### MLGG Diagnostic Accuracy (vs R3 Ground Truth, N=20 disagreement subset)
- Sensitivity: X.XX (95% CI: X.XX – X.XX)
- Specificity: X.XX (95% CI: X.XX – X.XX)
- PPV: X.XX
- NPV: X.XX

### Per-Kapoor-Type Detection
| Type | N (ground truth) | MLGG detected | LLM detected | R0xx rules |
|------|-----------------|---------------|---------------|------------|
| L1.2 |       X         |      X        |       X       | R001,R002  |
| ...  |                 |               |               |            |
```

---

## 8. 当前状态与下一步

| 步骤 | 状态 | 产物 |
|------|------|------|
| 分层抽样 | ✅ 已完成 | `blind_audit_list.jsonl`（50 篇） |
| R1 扫描 | ✅ 已完成 | `code_audit_v3_final.json` |
| R2 评审 | ⏳ 5/50 已完成 | `manual_audit_log.jsonl` |
| 揭盲比对 | ⏳ 初步 | `blind_audit_results.json`（kappa=0.314, Fair） |
| R3 仲裁 | 未开始 | — |
| 最终报告 | 未开始 | — |

**当前 kappa=0.314（Fair）** 说明 MLGG 和 LLM 的判定一致性偏低。可能原因：
1. R2 只完成了 5/50，样本量不足以得到稳定 kappa
2. MLGG lint 的 FP 率较高（precision=0.38）
3. LLM 和 MLGG 对"泄漏"的定义粒度不同（MLGG 按 R0xx 规则，LLM 按 Kapoor 类型）

**下一步**：完成剩余 45 篇 R2 评审 → 重新计算 kappa → 识别分歧模式 → R3 仲裁 → 最终报告。
