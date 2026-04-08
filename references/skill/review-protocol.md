# 评审循环协议（Review Loop Protocol）

每个 Phase 完成后**强制**执行此协议。这是 MLGG 的核心质量保障机制。

---

## 三种评审模式

不同阶段使用不同的评审方式：

| 模式 | 适用场景 | 机制 |
|------|---------|------|
| **Gate 模式** | Research 模式 Phase 1-9 / Pipeline 模式 A-1, A-2, A-4, A-5 | 运行 Gate 脚本 → 解析 JSON 报告（failures/warnings 数组） |
| **CLI 输出审查模式** | Pipeline 模式 A-3（train）和 A-6（workflow） | 读 CLI 产出的 JSON → Agent 按标准阈值判断 |
| **Lint + 人工审查模式** | Research 模式 Phase 3 | 运行 `mlgg lint check` + Agent 逐项代码审查 |

### CLI 输出审查模式（Pipeline 模式专用）

`mlgg.py train` 和 `mlgg.py workflow` 的输出不是标准 gate 报告（没有 failures/warnings 数组）。Agent 按以下标准自行判断：

**A-3 (`mlgg.py train`) 输出审查标准**：

| 读哪个文件 | 检查项 | 通过标准 | 未通过操作 |
|-----------|--------|---------|-----------|
| `evaluation_report.json` | test PR-AUC | > 0.5 | 检查特征/数据 |
| `evaluation_report.json` | 校准斜率 | 0.7 ~ 1.3 | 加 `--calibration-method sigmoid` |
| `evaluation_report.json` | CI 宽度 | < 0.20 | 增加 `--bootstrap-resamples` |
| `evaluation_report.json` | train-test gap | < 0.10 | 加正则化或减特征 |
| `evaluation_report.json` | 过拟合风险 | low / medium | high → 简化模型池 |
| `model_selection_report.json` | 候选模型数 | ≥ 3 | 增加 `--model-pool` |

**A-6 (`mlgg.py workflow`) 输出审查标准**：

| 读哪个文件 | 检查项 | 操作 |
|-----------|--------|------|
| `publication_gate_report.json` | 整体 pass/fail + 各 gate 状态 | 先看聚合结果 |
| `evidence/<gate>_report.json` | 失败 gate 详情 | `explain_gate.py --report <file>` |
| `self_critique_report.json` | 12 维评分 | 评分 < 75 → 查低分维度 |

两种 CLI 输出审查都遵守 3 轮迭代上限和 peer-review 查证要求。

### Lint + 人工审查模式（Research 模式 Phase 3）

Phase 3（预处理）没有独立 Gate 脚本，因为预处理内嵌在 sklearn Pipeline 中。该 Phase 的评审循环改为：
1. 运行 `python3 scripts/orchestration/mlgg.py lint check <file>` 扫描代码
2. Agent 按 MLGG-P01~P06 规则逐项审查 Pipeline 构建代码
3. 发现问题 → 同样用标准格式输出 → fix → 重新审查
4. lint 无诊断 + Agent 审查无问题 → 视为通过

---

## Gate 模式执行流程

### Step 1: 运行 Gate

1. 执行该 Phase 对应的 Gate 脚本（见各 Phase 规则文件中的命令）
2. **多 Gate 的 Phase**（如 Phase 6 有 5 个 Gate）：**一次性全部运行**，汇总所有报告后统一评审，而非逐个运行逐个修
3. 读取每个 Gate 输出的 JSON 报告
4. 解析三个列表：`failures[]`、`warnings[]`、`info[]`

### Step 2: 处理 CRITICAL

对每个 failure：

**a. 格式化输出**
```
[MLGG-XXX] CRITICAL: issue_code
Location: file:line
Problem: 具体描述
Fix: 修复方案
```

**b. 查证 peer-review-kb.json**

用 CLI 工具按字段匹配：
```bash
# 按 gate 名匹配
python3 scripts/tools/peer_review_lookup.py --gate <gate_name>

# 按问题标签匹配
python3 scripts/tools/peer_review_lookup.py --tags "<tag1>,<tag2>"

# 按维度+严重度匹配
python3 scripts/tools/peer_review_lookup.py --dimension <N> --severity HIGH

# 按关键词搜索
python3 scripts/tools/peer_review_lookup.py --search "<keyword>"

# 查看统计概况
python3 scripts/tools/peer_review_lookup.py --stats
```

输出引用：
```
[PEER-REVIEW] PR-XXX-CYY (Nature Communications, 20XX)
  审稿人: "原文引用..."
  修复: "作者的修复方案..."
  统计: 107 篇 NC 论文中 N/375 (X%) 的审稿意见涉及类似问题
```

**c. 执行修复**
- 如果是代码问题 → 直接修改代码
- 如果是配置问题 → 修改配置并解释
- 如果是数据问题 → 向用户说明，提供选项
- 如果需要用户决策 → 明确列出选项和建议

**d. 重新运行 Gate**
- 修复后必须重跑**同一批**Gate（不是只跑失败的那一个）
- 确认该 CRITICAL 已消除
- 如果产生新的 CRITICAL → 继续处理

### Step 3: 迭代控制

- **最多 3 轮** fix-and-rerun
- 每轮记录：修了什么、结果如何
- 第 3 轮仍有 CRITICAL → **停止**，向用户完整报告：
  ```
  ⛔ Phase N 评审未通过（3 轮修复后仍有问题）
  
  未解决的 CRITICAL:
  1. [MLGG-XXX] problem_description
     已尝试: [修复方案]
     原因: [为什么自动修复不够]
  
  建议: [需要用户手动处理的事项]
  ```

### Step 4: 处理 WARNING

- **非 strict 模式**: 展示 WARNING，建议修复但不阻断
- **strict 模式**: WARNING 视为阻断，走 CRITICAL 同样的 fix-and-rerun 流程

WARNING 输出格式：
```
[MLGG-R02] WARNING: seed_stability_not_tested
Problem: 未进行多种子稳定性检验
Recommendation: 建议运行 ≥5 seeds，std < 0.02
NC 参考: 38/375 审稿意见要求可复现性验证
```

### Step 5: Phase 总结卡

所有检查通过后，输出总结卡：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Phase N ✓  [Phase 名称]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Gate 检查: X 项通过
  修复问题: Y 项（Z 轮修复）
  关键发现:
    • [发现 1]
    • [发现 2]
  产出文件:
    • evidence/xxx_report.json
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  → 准备进入 Phase {N+1}？
```

等待用户确认后才进入下一 Phase。

---

## Peer Review 查证工具

审查时**必须**使用 `peer_review_lookup.py` 检索证据，不要手动打开 JSON 文件搜索：

```bash
# 统计概况（每次审查开始时可先看一眼）
python3 scripts/tools/peer_review_lookup.py --stats

# 按问题类别查
python3 scripts/tools/peer_review_lookup.py --category evaluation_metrics --limit 3

# 按 gate 名查（gate 失败时用）
python3 scripts/tools/peer_review_lookup.py --gate calibration_dca_gate

# 按标签查（发现具体问题时用）
python3 scripts/tools/peer_review_lookup.py --tags "missing_calibration,no_dca"

# 按维度+严重度查（Phase checkpoint 时用）
python3 scripts/tools/peer_review_lookup.py --dimension 5 --severity HIGH

# 自由文本搜索
python3 scripts/tools/peer_review_lookup.py --search "calibration missing AUC"
```

增强说服力时，引用 `references/peer_reviews/peer-review-kb-stats.json` 中的统计数据：

| 维度 | 统计引用模板 |
|------|------------|
| 评估指标 | "107 篇 NC 论文中，119/375 (31.7%) 的审稿意见要求完善评估指标" |
| 数据泄漏 | "25 条 CRITICAL 级问题中，数据泄漏和结局定义错误最常见" |
| 校准缺失 | "只报 AUC 不报校准是 NC 审稿人最常提出的 HIGH 级问题" |
| 研究设计 | "81/375 (21.6%) 的意见涉及研究设计" |

---

## 评审循环的不可协商规则

1. **不可跳过**: 即使用户说"跳过检查"，也必须运行 Gate / lint，至少告知结果
2. **不可降级**: CRITICAL 不能降为 WARNING
3. **必须重跑**: 修复后必须重跑 Gate 验证，不能仅靠人工判断
4. **必须记录**: 每次修复的内容和原因都要告诉用户
5. **不可粉饰**: 如果问题确实存在，不因为是自己写的代码就放松标准
