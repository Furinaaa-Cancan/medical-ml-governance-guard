---
name: ml-governance-guard
description: "Publication-grade governance for retrospective cohort binary-classification ML (EHR/registry/case-control/cross-sectional). 33 fail-closed gates covering leakage, calibration, fairness, TRIPOD+AI/PROBAST+AI compliance. Refuses omics/imaging/text modalities via R028."
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
| **`/mlgg`** | 人类用户（Claude Code 内） | 建模 / 训练 / "我有数据" —— 自动观察数据、推断参数、走 Pipeline 模式 6 步（仅 CSV）或 Research 模式 9 阶段（含用户代码） |
| **`mlgg <subcommand>`** | 终端 / 脚本自动化 | 28 个子命令（见 Quick Dispatch 分组表），包含 play / workflow / onboarding / audit / doctor / lint 等 |
| **`mlgg-lint`** | CI / pre-commit | 独立 pip 包，28 条 AST 规则（R001-R028，含 R028 omics 模态守卫），零依赖，5 秒扫完单文件 |

### 怎么选？`workflow` vs `audit`

- **项目是你用 MLGG 自己跑出来的**（`evidence/*.json` 存在、`configs/request.json` 符合 schema）→ `mlgg workflow --strict`，跑全部 33 gate 验证证据。
- **项目是别人写的、没有 MLGG 格式的 evidence**（只有 train.csv / notebook / 模型 pickle / metrics.json）→ `mlgg audit <dir>`，基于代码模式扫描 + 文件结构检查打分，不会因缺 `evidence/*.json` 而爆 noisy failure。
- **CI 里只想检查单文件代码泄漏** → `mlgg-lint check <file.py>`（零依赖，几秒出结果）。

## Quick Dispatch

Agent 面向人类用户默认走 `/mlgg`。以下是 `mlgg <subcommand>` 全部 28 个子命令的分组索引（`mlgg flow` 显示推荐顺序，`mlgg --help` 显示全表）。

**主流程（90% 场景）**

| 子命令 | 用途 |
|---|---|
| `onboarding` | 新手引导：demo data → train → attestation → strict workflow 一条龙 |
| `workflow` | 生产级：doctor → preflight → strict → summary |
| `strict` | 直接跑 33-gate fail-closed DAG |
| `train` | Train / select / evaluate + 产出 evidence artifacts |
| `summary` | 渲染用户可读的 markdown / JSON 摘要 |

**流水线步骤（需要拆步时）**

| 子命令 | 用途 |
|---|---|
| `init` | 生成项目目录和 config 模板 |
| `preflight` | 验证 train/valid/test schema 和语义映射 |
| `split` | 把单个 CSV 拆成 train/valid/test（患者级隔离） |
| `semantic-audit` | LLM 对特征列做语义泄漏检测 |

**交互入口**

| 子命令 | 用途 |
|---|---|
| `interactive` | 向导式 init/workflow/train/authority |
| `play` | Pixel-art 菜单式启动器 |

**环境 / 元数据**

| 子命令 | 用途 |
|---|---|
| `doctor` | 运行时依赖和可选后端检查 |
| `init-guide` | 为任意 ML 项目生成 MLGG 方法学指南（`.mlgg/` + CLAUDE.md） |
| `record-session` | 把 evidence 目录追加到 session 日志 |

**单 gate 直调**

| 子命令 | 用途 |
|---|---|
| `fairness` | Subgroup equalized odds / disparate impact |
| `sample-size` | EPV / shrinkage / Riley criteria |

**审计外部项目**

| 子命令 | 用途 |
|---|---|
| `audit` | 10 维定量打分（100 分制）审计外部 ML 项目 |
| `audit-report` | 综合审计报告（TRIPOD+AI / PROBAST+AI + error KB + 文献引用） |
| `audit-metrics` | 只从 metrics JSON 做 publication-readiness 快检（无需数据文件） |
| `batch-review` | 批量对 N 个项目做期刊标准审查 + 对比矩阵 |
| `export-review-prompt` | 导出 MLGG 评审规则为便携 LLM prompt（可粘到任意 LLM） |
| `lint` | 等价 `mlgg-lint`（AST 代码泄漏检测，零依赖） |

**Benchmark（内部用，release 前跑）**

| 子命令 | 用途 |
|---|---|
| `authority` | Authority E2E 基准套件 |
| `authority-release` | CKD release-grade 压力路由 |
| `authority-research-heart` | 心脏研究场景高压路由 |
| `benchmark-suite` | 多数据集稳定性矩阵（authority + adversarial） |
| `scan-diabetes` | 糖尿病 feasibility 扫描（跨 target mode 和行上限） |
| `adversarial` | Adversarial fail-closed gate 场景 |

---

**Script-level 工具（非 `mlgg` 子命令，直接 python3 调用）**

| 用途 | 脚本 |
|---|---|
| 查看结果 | `scripts/reporting/quick_summary.py <dir>` |
| 对比两次运行 | `scripts/reporting/compare_runs.py --run-a <d1> --run-b <d2>` |
| 生成修复计划 | `scripts/reporting/remediation_plan.py --evidence-dir <dir>` |
| 解释 gate 失败 | `scripts/reporting/explain_gate.py --report <gate_report.json>` |
| LaTeX / 合规证书 | `scripts/reporting/export_latex.py` / `generate_compliance_certificate.py` |
| 论文审稿 | `scripts/review/peer_review_lookup.py` / `score_paper_metadata.py` |
| 下载数据集 | `examples/download_*.py`（详见 `references/docs/API-Reference.md`） |

内部工具函数（`_gate_utils.py`）和 SHAP gate 直接调用见 `references/docs/gate-framework-developer-guide.md`。

---

## Peer Review Evidence Protocol

Agent 审查代码时，查阅 `references/case-studies/peer-review-kb.json`（106 篇 NC 论文，375 条审稿意见）作为**补充背书**——当适用时可以引用，但不要把缺引用当作 gate 判定的依据。

> 审稿人的原话是有力的旁证，但不是 ground truth。KB 是 Nature Communications 已发表论文的审稿意见集合，**经过了 pre-publication filter**——有严重泄漏的论文在发表前就被拒，因此 KB 中 leakage 类审稿意见稀少（≈4% with leakage_gate mapping）。

**强弱覆盖、KB 结构、检索策略详见** `references/case-studies/peer-review-kb-audit-2026-04.md`。要点:
- Gate 失败 = evaluation / reporting / external validation → KB 是有力背书
- Gate 失败 = leakage → 优先 `leakage_gate` + lint R001-R028,KB 仅辅助(prepub filter 后 KB 中 leakage 案例稀少)
- **不要**用 "KB 里没提过" 反推 leakage 不存在

**引用格式**: `[PEER-REVIEW] PR-XXX-CYY (Nature Communications, 20XX) 审稿人: "..." 修复: "..."`

检索: `python3 scripts/review/peer_review_lookup.py --stats|--gate <name>|--tags "<tags>"`

**Caveat (RAG layer)**: BM25 inactive in free-text mode; see README for full limitations.

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

## 能力边界

MLGG 是**训练管线治理工具**，不是全栈 publication readiness。下面的分层请诚实读。

| 维度 | 覆盖 | 说明 |
|---|---|---|
| 数据划分 / 泄漏检测 / 管线隔离 | ✅ 强 | 33 gate 的核心设计目标；有代码扫描 + 运行时检测 |
| 模型选择 / 评估指标 / 校准 / DCA | ✅ 强 | 完整 14 指标面板，Bootstrap CI，TRIPOD+AI 对齐 |
| 公平性 / 亚组分析 | ✅ 中 | `fairness_equity_gate` 查等均化 odds + disparate impact |
| 样本量 / EPV | ✅ 中 | Riley 2019/2025 + van Houwelingen 阈值 |
| **Cohort selection bias**（谁进入队列、谁被排除、selection 机制） | ✅ 中 | `cohort_definition_gate` 现在验证 `--cohort-spec` JSON 声明的 inclusion/exclusion cascade（monotonicity + final_cohort_size 对账）、生成 `cohort_table_one.csv`（TRIPOD+AI Item 13a）、检查 `index_date_col` 存在性；`claim_tier=publication-grade` 时未声明 cascade → FAIL。仍不做与人群参考（NHANES/census）的 Table 1 对比，也不做 immortal-time-bias 值域检测（下放 `feature_lineage_gate`）。|
| **Label ascertainment validity**（结局如何被记录、coding 误差） | ❌ 超范围 | 需临床核验 + EHR 元信息，不是代码问题 |
| **Post-deployment monitoring**（上线后漂移、性能衰减） | ❌ 超范围 | MLGG 是离线治理，推荐 Evidently AI / WhyLabs 等 |

**模态**: 回顾性队列研究的二分类预测（EHR / 临床 / 注册 / 病例对照 / 横断面）。23 个 sklearn 模型族 + 4 个可选后端（XGBoost / CatBoost / LightGBM / TabPFN）。
**不支持**: 组学/基因组 (TCGA bulk、scRNA-seq、GWAS、甲基化) / 影像 / 文本 / 时序、多分类 / 回归、深度学习、部署流水线、survival/time-to-event (roadmap)。模态守卫: `mlgg-lint` R028 会在检测到 `gene_/probe_/snp_/cpg_/rs#/ENSG` 特征时直接拒绝。

用"publication-grade"时请具体到哪个维度："本项目已过 MLGG 训练管线治理（33 gate），cohort cascade 已声明+对账、Table 1 已生成，但 label ascertainment 依赖临床核验"——不要泛泛声称论文级就绪。

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

`references/protocols/` 下:`review-protocol.md`、`phase-1.md` ~ `phase-9.md`、`audit-mode.md`。
疾病/错误/文献知识库:`references/methodology/disease-definition-knowledge-base.json`、`references/operations/error-knowledge-base.json`、`references/methodology/literature-knowledge-base.json`。
