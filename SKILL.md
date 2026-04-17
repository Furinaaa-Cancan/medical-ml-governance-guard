---
name: ml-governance-guard
description: "Publication-grade medical prediction workflow with 33 fail-closed gates covering data leakage, calibration, fairness, TRIPOD+AI/PROBAST+AI compliance, and full model lifecycle governance."
---

# ML Governance Guard

## 架构

- `/mlgg` → 加载 `.claude/commands/mlgg.md`（状态机 + 评审循环，~200 行）
- 每个 Phase → 按需读 `references/protocols/phase-N.md`（仅 Research 模式）
- 审计模式 → `references/protocols/audit-mode.md`

---

## Entry Points（3 条正式入口）

MLGG 对外暴露 3 条稳定入口，其他所有功能都是它们的子命令或辅助脚本。

| 入口 | 面向 | 场景 |
|---|---|---|
| **`/mlgg`** | 人类用户（Claude Code 内） | 建模 / 训练 / "我有数据" —— 自动观察数据、推断参数、走 9 阶段 pipeline |
| **`mlgg <subcommand>`** | 终端 / 脚本自动化 | 29 个子命令（见下），包含 play / workflow / onboarding / audit / doctor / lint 等 |
| **`mlgg-lint`** | CI / pre-commit | 独立 pip 包，27 条 AST 规则，零依赖，5 秒扫完单文件 |

## Quick Dispatch

| 用户说的 | 命令 |
|---------|------|
| 建模 / 训练 / "我有数据" | `/mlgg` |
| 交互式体验 | `mlgg play` |
| 初始化项目 | `mlgg onboarding` |
| 跑完整 9 阶段 pipeline | `mlgg workflow --strict` |
| 检查环境 | `mlgg doctor` |
| 审计外部项目 | `mlgg audit <dir>` |
| 查看结果 | `python3 scripts/reporting/quick_summary.py <dir>` |
| 对比两次运行 | `python3 scripts/reporting/compare_runs.py --run-a <d1> --run-b <d2>` |
| 生成修复计划 | `python3 scripts/reporting/remediation_plan.py --evidence-dir <dir>` |
| 解释 gate 失败 | `python3 scripts/reporting/explain_gate.py --report <gate_report.json>` |
| 检查代码泄漏（CI 单文件） | `mlgg-lint check <file.py>`（或 `mlgg lint check`） |
| 查审稿案例 | `python3 scripts/review/peer_review_lookup.py --stats` |
| 审稿人怎么看？ | `python3 scripts/review/peer_review_lookup.py --tags "<tags>"` |
| gate 抓过什么？ | `python3 scripts/review/peer_review_lookup.py --gate <gate_name>` |
| 审查论文 Methods | `python3 scripts/review/score_paper_metadata.py --metadata <metadata.json>` |
| 批量评审 | `python3 scripts/review/batch_journal_review.py --manifest batch_manifest.json` |
| LaTeX 表格 | `python3 scripts/reporting/export_latex.py --evaluation-report evidence/evaluation_report.json` |
| 合规证书 | `python3 scripts/reporting/generate_compliance_certificate.py --evidence-dir evidence/` |
| 下载数据集 | `python3 examples/download_real_data.py <name>` (heart/breast/ckd/pima/framingham/diabetes130/diabetes130_full/rhc/sepsis_survival/...) |
| 下载 CDC 数据 | `python3 examples/download_cdc_data.py <name>` (brfss/nhis/covid/all) |
| 下载 NHANES | `python3 examples/download_nhanes.py --cycles both --output examples/nhanes_diabetes.csv` |
| 下载 NCI 癌症 | `python3 examples/download_nci_gdc.py --output examples/nci_gdc_cancer_survival.csv` |

**`_gate_utils.py` 内部工具函数**（gate 实现中调用，非独立 CLI）：
`calibration_metrics()` / `compute_nri_idi()` / `compute_vif()` / `check_nonlinearity()` /
`mnar_sensitivity_analysis()` / `temporal_drift_analysis()` / `generate_model_card()` /
`imputation_sensitivity()` / `subgroup_dca()` / `feature_ablation()`。

**SHAP 可解释性 gate 直接调用**（通常由 workflow 自动触发）：
`python3 scripts/gates/shap_interpretability_gate.py --model-pool evidence/model_pool.pkl --train-data data/train.csv --test-data data/test.csv --target-col y --report evidence/shap_report.json`

---

## Peer Review Evidence Protocol

Agent 审查代码时，查阅 `references/case-studies/peer-review-kb.json`（106 篇 NC 论文，375 条审稿意见）作为**补充背书**——当适用时可以引用，但不要把缺引用当作 gate 判定的依据。

> 审稿人的原话是有力的旁证，但不是 ground truth。KB 是 Nature Communications 已发表论文的审稿意见集合，**经过了 pre-publication filter**——有严重泄漏的论文在发表前就被拒，因此 KB 中 leakage 类审稿意见稀少（≈4% with leakage_gate mapping）。

**KB 强在哪 / 弱在哪**（2026-04 audit，见 `references/case-studies/peer-review-kb-audit-2026-04.md`）:

| 覆盖强 | Concerns 数 | 覆盖弱 | Concerns 数 |
|---|---|---|---|
| 评估指标不全（AUPRC / MCC / Brier） | 119 | 数据泄漏直接证据 | 3 (category) + 10 (tag-derived) |
| 报告规范（TRIPOD / 图表完整性） | 52 | Split protocol | 3 |
| 外部验证缺失 | 21 | | |
| 模型选择 / 调参 | 17 | | |

**含义**：
- Gate 失败类型是 **evaluation / reporting / external validation** → KB 是有力背书
- Gate 失败类型是 **leakage** → 优先引用 `leakage_gate` 机制 + lint 规则 R001-R027，KB 只作为辅助
- **不要**用 "KB 里也没提过这种问题" 来反推某个 leakage 不存在

**KB 结构**: `concern_id`, `category`, `severity`, `mlgg_dimension`, `mlgg_gates`, `tags`, `concern_text`, `author_response`。每条 concern 至少映射到 1 个 `mlgg_gates`（P0-3b 已完成回填，0 条空数组）。

**检索策略**:
| 场景 | 检索字段 |
|------|---------|
| Gate 失败 | `mlgg_gates` 包含该 gate |
| 发现具体问题 | `tags` 匹配 |
| Phase checkpoint | `mlgg_dimension` |
| 严重度过滤 | `severity` |

**引用格式**: `[PEER-REVIEW] PR-XXX-CYY (Nature Communications, 20XX) 审稿人: "..." 修复: "..."`

```bash
python3 scripts/review/peer_review_lookup.py --stats
python3 scripts/review/peer_review_lookup.py --gate leakage_gate
python3 scripts/review/peer_review_lookup.py --tags "missing_calibration,no_dca"
```

---

## Clinical Semantic Review Checklist

Agent 审查或构建模型时，**必须**执行以下临床检查（自动 gate 无法覆盖）：

### Feature Timeline Audit
每个特征判定产生时间点：
- **Pre-index** (入院前: demographics, prior diagnoses) — 安全
- **Index-time** (入院时: admission labs, chief complaint) — 安全（如果预测在入院时）
- **Post-index** (出院后: length of stay, discharge disposition) — **LEAKAGE**

| 数据集 | 常被误用的 post-index 特征 |
|--------|--------------------------|
| Diabetes 130 (UCI) | time_in_hospital, num_medications, discharge_disposition_id |
| MIMIC-III/IV | Procedures, ventilation hours, vasopressor doses |

用户未指定预测时间点 → 问: "模型用于入院时、住院中、还是出院时？"

### Definition Variable Leakage (Lint 无法检测)
当用户用 `hba1c >= 6.5` 或 `fasting_glucose >= 126` 定义糖尿病标签后，
这些变量**不能**出现在特征列表中。Agent 必须检查:
1. 标签是如何构建的（查找 `df["label"] = ...` 的定义逻辑）
2. 定义中用到的列是否出现在 `features = [...]` 或 `X = df.drop(...)` 中
3. 如果结局 = 疾病诊断，读 `references/methodology/disease-definition-knowledge-base.json` 获取泄漏黑名单

### Variable Aliasing (Lint R021 可部分检测)
用户可能将 test set 赋给别名变量后用于调参:
```python
holdout_X = X_test       # alias
for params in grid:
    score = evaluate(holdout_X)  # 实际上在用 test set 调参
```
R021 可检测 `holdout/held_out` 等关键词，但任意命名（如 `eval_data = X_test`）
仍需 agent 人工追踪赋值链。

### Calibration Standards (Van Calster 2019)
每次校准报告必须包含:
1. Calibration slope (target: 1.0)
2. Calibration intercept (target: 0)
3. O:E ratio (target: 1.0)
4. ECE (<0.05 good, <0.10 acceptable)

### Interpretability Standards
- Multi-model SHAP: ≥ 2 model families
- Cross-model Spearman rank ρ ≥ 0.5
- Top-5 features 临床可解释

### Fairness Standards
- 95% Bootstrap CI for subgroup metrics
- n < 200 subgroups flagged as unreliable
- Equalized odds gap + disparate impact ratio

### Model Comparison
- ≥ 3 models on same test → 需多重比较校正 (Bonferroni-adjusted DeLong)
- 无校正 → 报告为 "empirical comparison" 非 "statistically superior"

---

## 12 维评分 (100 分制)

| # | 维度 | 权重 | 评分要点 |
|---|------|------|---------|
| 1 | 数据完整性 | 12 | Split 隔离、患者级不重叠、时序有序 |
| 2 | 防泄漏 | 15 | 无目标/定义/谱系/未来泄漏 |
| 3 | 流水线隔离 | 12 | 预处理器仅 train fit、插补隔离 |
| 4 | 模型选择严谨性 | 10 | 候选≥3、one-SE、不窥测试集 |
| 5 | 统计有效性 | 12 | Bootstrap CI、置换检验、校准、DCA |
| 6 | 泛化证据 | 10 | Train-test gap、外部队列、种子稳定 |
| 7 | 临床完整性 | 7 | 完整指标面板、混淆矩阵、阈值 |
| 8 | 报告标准 | 7 | TRIPOD+AI、PROBAST+AI |
| 9 | 可重复性 | 6 | 种子记录、版本追踪 |
| 10 | 安全与溯源 | 3 | 模型签名、工件完整性 |
| 11 | 公平性 | 3 | 均等化优势、差异影响比 |
| 12 | 样本量 | 3 | EPV≥10、收缩因子≥0.90 |

≥90 顶刊级 · 75-89 需补充 · 60-74 重大缺陷 · <60 不可发表

期刊标准映射: `references/standards/journal-rigor-standards.json` (Nature Medicine, Lancet DH, JAMA, BMJ, npj DM)

---

## Developer Reference

### 添加新数据集
1. `examples/download_real_data.py` → `URLS` + `prepare_<name>()` + `PREPARE` dict
2. 输出: `patient_id, event_time, y, features...`
3. `scripts/orchestration/mlgg_pixel.py` → i18n + `PLAY_DOWNLOAD_DATASETS`

### 添加新模型族
`scripts/training/train_select_evaluate.py` 5 处: `SUPPORTED_MODEL_FAMILIES`, `_family_grid()`, `_build_estimator_for_family()`, `_family_base_complexity()`, `_family_friendly_name()`

### 添加新 Gate
统一 CLI 契约: `--report`, `--strict`, exit 0/2, `build_report_envelope()`, `start_gate_timer()`, 注册到 `_gate_registry.py`。

### 添加新 Lint 规则
`plugin/mlgg_lint/rules/r0xx_rule_name.py` + `plugin/tests/samples/r0xx_bad.py` + `r0xx_good.py`

---

## 常见错误恢复

| 错误 | 修复 |
|------|------|
| `candidate_pool_too_small` | 增加模型族或 `--max-trials-per-family` |
| 训练超时 (>20min) | 减少模型数/trials |
| `FileNotFoundError` | 检查 `data/` 下 CSV |
| Gate 失败 | `python3 scripts/reporting/explain_gate.py --report evidence/<gate>_report.json` |

---

## Gate 严格性 Profile

| Profile | 适用场景 | EPV | 最小事件 |
|---------|---------|-----|---------|
| `standard` | N≥1000 | 10 | 100 |
| `small_cohort` | N=200-1000 | 7 | 50 |
| `rare_disease` | N<200 | 5 | 20 |

在 `request.json` 中指定: `"thresholds": {"profile": "rare_disease"}`

---

## 可用数据集 (16 个, 526K+ 行)

| 数据集 | 行数 | 下载命令 |
|--------|------|---------|
| Sepsis Survival | 129K | `download_real_data.py sepsis_survival` |
| Diabetes 130 Full | 102K | `download_real_data.py diabetes130_full` |
| BRFSS 2022 | 100K | `download_cdc_data.py brfss` |
| NHANES | 16K | `download_nhanes.py --cycles both` |
| RHC | 5.7K | `download_real_data.py rhc` |
| Heart/Breast/Pima | <1K | `download_real_data.py heart` |

---

## 能力边界

**能做**: 表格型医学二分类 (EHR/临床/注册), 20 个 sklearn 模型族 + 4 个可选后端, 33 gate 全生命周期治理
**不能做**: 图像/文本/时序, 多分类/回归, 深度学习, 模型部署

---

## Research 模式常见修复

| 用户代码中的问题 | 严重度 | 修复 |
|----------------|--------|------|
| `train_test_split(X, y)` 无 groups | CRITICAL | 加 `groups=df["patient_id"]` |
| `scaler.fit(X)` 在 split 前 | CRITICAL | 移到 split 后 `scaler.fit(X_train)` |
| SMOTE 用在全数据 | CRITICAL | 删 SMOTE，改 `class_weight="balanced"` |
| 只报 AUROC | MAJOR | 补 AUPRC、MCC、Brier、校准、DCA |
| 无 CI | MAJOR | 加 bootstrap 95% CI (≥1000) |
| 阈值在 test 上选 | CRITICAL | 改为 validation 上选 (Youden's J) |
| 定义变量做特征 | CRITICAL | 删除所有定义变量 |

---

## 标准化交付物

```
<project>/
├── data/train.csv, valid.csv, test.csv
├── configs/request.json, *.json
├── evidence/*_report.json (×33), manifest.json, prediction_trace.csv.gz
├── models/model.pkl + model.pkl.sig
└── results/summary.md, tables.tex
```

---

## Phase 文件参考

```
references/protocols/
├── review-protocol.md    # 评审循环详细协议
├── phase-1.md ~ phase-9.md  # 各阶段详细规则
└── audit-mode.md         # 快速审计模式
```

疾病定义知识库: `references/methodology/disease-definition-knowledge-base.json` (10 种常见疾病)
错误知识库: `references/operations/error-knowledge-base.json`
文献知识库: `references/methodology/literature-knowledge-base.json` (30 条顶刊)

Agent Quick Reference:
```
构建新项目:  mlgg.py onboarding --mode auto
审计项目:    audit_external_project.py
修复计划:    remediation_plan.py --evidence-dir <dir>
证据对比:    evidence_comparator.py
LaTeX导出:   export_latex.py
```
