<p align="right">
  <a href="./README_EN.md">English</a> | 中文
</p>

<h1 align="center">
  <code>medical-ml-governance-guard</code>
</h1>

<p align="center">
  <img src="https://img.shields.io/badge/MLGG-v1.0-FF6B35?style=for-the-badge&labelColor=1a1a2e" alt="MLGG v1.0">
  <br><br>
  <strong style="font-size: 2em;">ML Governance Guard</strong>
  <br>
  <em>顶刊级审稿标准 × AI 驱动的医学预测模型治理框架</em>
  <br><br>
  <a href="https://github.com/Furinaaa-Cancan/medical-ml-governance-guard"><img src="https://img.shields.io/badge/GitHub-Furinaaa--Cancan%2Fmedical--ml--governance--guard-181717?logo=github" alt="GitHub Repo"></a>
  <br>
  <a href="https://polyformproject.org/licenses/noncommercial/1.0.0/"><img src="https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/tests-5501%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/gates-33%20fail--closed-critical" alt="Gates">
  <img src="https://img.shields.io/badge/datasets-16%20medical-purple" alt="Datasets">
  <img src="https://img.shields.io/badge/code-147K%20lines-informational" alt="Code">
  <img src="https://img.shields.io/badge/lint%20rules-28%20(R001--R028)-orange" alt="Lint Rules">
  <a href="https://doi.org/10.1136/bmj-2023-078378"><img src="https://img.shields.io/badge/TRIPOD%2BAI-2024-blue" alt="TRIPOD+AI"></a>
  <a href="https://doi.org/10.1136/bmj-2024-082505"><img src="https://img.shields.io/badge/PROBAST%2BAI-2025-blue" alt="PROBAST+AI"></a>
</p>

---

<p align="center">
<strong>33 道 fail-closed 门控</strong> &middot; <strong>9 阶段工作流</strong> &middot; <strong>12 维量化评分</strong> &middot; <strong>3 级合规认证</strong>
<br>
<strong>23 个模型族</strong> &middot; <strong>16 个真实医学数据集 (630K+ 行)</strong> &middot; <strong>119 篇 NC 审稿证据</strong> &middot; <strong>28 条静态分析规则</strong>
<br><br>
<em>每一条审查建议都引用真实顶刊审稿意见作为论据。<br>不是规则引擎，是能像 Nature Medicine 审稿人一样思考的 AI 协审系统。</em>
</p>

---

## MLGG vs Claude Skill — 架构边界

> **MLGG 是 hybrid**：Claude Skill 做外壳，Python gate 做内核。**幻觉最多改变「跑了哪些 gate」，改变不了「每个 gate 的 pass/fail」。**

### 三层结构（层内标注了各自的幻觉风险）

```
┌──────────────────────────────────────────┐
│  SKILL.md + CLAUDE.md  ~380 行           │  ⚠️ 可能幻觉
│  软决策：跑哪个阶段、理解用户意图        │  读者：LLM
└──────────────────────────────────────────┘
                  ↓ 编排调用
┌──────────────────────────────────────────┐
│  33 道 gate  ~40K 行 Python              │  ✅ 0 幻觉
│  硬决策：pass / fail / critical 三态     │  读者：CPython
│  同输入同输出，CI 可回归                 │
└──────────────────────────────────────────┘
                  ↓ KB 查询
┌──────────────────────────────────────────┐
│  references/  ~2 MB human-curated KB     │  ✅ 0 幻觉
│  peer-review-kb.json （119 篇 NC 审稿）  │  读者：SQL / JSON
│  codebooks/ukb （8 层验证，1.87M cells） │
│  methodology/disease-kb.json             │
└──────────────────────────────────────────┘
```

**幻觉锁在最顶层**——下面两层永远拿确定性算法 + 静态数据算 pass/fail。

### 逐行风险：哪些动作可能被幻觉影响？

| 动作 | 层 | 幻觉风险 | 能否改变 pass/fail |
|---|---|---|---|
| `/mlgg` 决定跑哪个 workflow | Skill | ⚠️ | ❌ 可能多/漏跑，但**每个跑了的 gate 结论仍然确定** |
| Claude 用自然语言总结 gate 输出 | Skill | ⚠️ | ❌ 只是表达层偏差 |
| `leakage_gate.py` 判定标签泄漏 | Python | ✅ | ❌ 确定性算法 |
| `calibration_dca_gate.py` 算 ICI/DCA | Python | ✅ | ❌ 纯数值计算 |
| `verify_ukb_codebook.py` 8 层验证 | Python | ✅ | ❌ 1.87M cell 全量对账 |
| 从 `peer-review-kb.json` 引审稿意见 | references | ✅ | ❌ SQL / JSON 精确查找 |

### 两种用法，底层同一份 pass/fail

- **交互**：`/mlgg` → Claude 读你的意图 → 自动编排 9 阶段 pipeline
- **CI / 发布级**：`python3 scripts/gates/leakage_gate.py --data x.csv` —— 跳过 Skill，直接调底层

两种用法最终跑的是**同一份 Python gate**。Skill 省的是「敲命令的时间」，不承担正确性。

### 工程保证（而不只是愿景）

- **SKILL.md ≤ 500 行**：当前 288 行，符合 Claude Code 官方建议；超长内容拆到 `docs/` 或 gate docstring。
- **文档数字 pre-commit 校验**：`check_docs_consistency.py` + `check_readme_stats.py` 抓 `SKILL.md ↔ README ↔ reviewer.yaml` 的 parity 和 KB freshness drift，**PR 会被 fail 而不是 merge 后才发现**。
- **阈值是代码不是 prompt**：所有 pass/fail 阈值、validator 规则、检测算法都是 Python 常量 + 函数，gate 不从 markdown 读判定逻辑。

---

## 目录

- [MLGG vs Claude Skill — 架构边界](#mlgg-vs-claude-skill--架构边界)
- [为什么需要 MLGG](#为什么需要-mlgg)
- [系统能力总览](#系统能力总览)
- [快速开始](#快速开始)
- [9 阶段工作流](#9-阶段工作流)
  - [阶段一：队列定义与样本量](#阶段一队列定义与样本量)
  - [阶段二：数据划分](#阶段二数据划分)
  - [阶段三：预处理](#阶段三预处理)
  - [阶段四：特征筛选](#阶段四特征筛选)
  - [阶段五：模型训练与选择](#阶段五模型训练与选择)
  - [阶段六：评估与校准](#阶段六评估与校准)
  - [阶段七：多模型 SHAP 可解释性](#阶段七多模型-shap-可解释性)
  - [阶段八：公平性与亚组分析](#阶段八公平性与亚组分析)
  - [阶段九：报告与合规](#阶段九报告与合规)
- [33 道安全门控 (Gate DAG)](#33-道安全门控-gate-dag)
- [12 维量化评分](#12-维量化评分)
- [33 条方法论规则](#33-条方法论规则)
- [23 个模型族](#23-个模型族)
- [16 个医学数据集](#16-个医学数据集)
- [28 条静态分析规则 (R001-R028)](#27-条静态分析规则-r001-r027)
- [21 项分析工具](#21-项分析工具)
- [安全加固层](#安全加固层)
- [项目结构](#项目结构)
- [安装指南](#安装指南)
- [命令参考](#命令参考)
- [文献基础](#文献基础)
- [Claude Code 集成](#claude-code-集成)
- [CI/CD](#cicd)
- [许可证与引用](#许可证与引用)
- [English Version](#english-version)

---

## 为什么需要 MLGG

医学 ML 论文中数据泄漏和方法学缺陷的发生率远超预期。已发表预测模型中高偏倚风险的比例极高 (Wynants et al. 2020, BMJ; Navarro et al. 2023, BMJ)。

| 常见错误 | 后果 | MLGG 阻止方式 |
|:---------|:-----|:-------------|
| 全数据上标准化后再划分 | 性能虚抬，审稿人看不出来 | Gate P01: Pipeline 隔离审计 |
| 死亡患者纳入再入院预测 | 结局结构性不可能，AUROC 被污染 | Gate C01: 队列定义审查 |
| 名义变量用 OrdinalEncoder | LR 系数失去临床意义 (实测 AUROC +0.02) | Gate P05: 强制 OneHot |
| 只报 AUROC 不报 MCC 和 LR+/LR- | AUROC 0.65 看起来可以，但 MCC 0.12 说明近乎随机 | Gate E02: 完整 14 指标面板 |
| 用 train-test gap 选模型 | 无文献支撑，可能选到次优模型 | Gate M04: 验证集 PR-AUC + one-SE |
| 特征选择用全数据 | 信息从测试集泄漏到训练集 | Gate F03: 训练集独占约束 |
| HbA1c 既定义糖尿病又作为预测特征 | 完美泄漏，模型学到的是定义本身 | Gate C02: 定义列强制排除（按预测疾病作用域匹配，避免非糖尿病 target 误报 glucose） |
| Bootstrap CI 用正态近似 | 小样本/非对称分布不可靠 | Gate E01: 强制 percentile bootstrap |
| `time_in_hospital` / `num_medications` / `discharge_*` 作特征 | 教科书 post-index 泄漏（diabetes_130 / MIMIC 经典模式） | Gate L01: 特征名正则抓 5 类 post-index 模式 + `forbidden_features` 拉黑 |
| Doctor-provided `surv2m` / `prg6m` 作特征 | 医生预估目标，近完美 target leak | Gate C02 + Gate F03: 3 套正则（surv\d / prognos / prg\d）+ 特征谱系溯源 |
| `received_drug_x` / `prescribed_statin` 作特征 | Immortal time bias：接受治疗的患者必然存活到治疗窗口 (Suissa 2008; Hernán 2016) | Gate L01 `IMMORTAL_TIME_RE`: 9 类治疗动词前缀，排除 `history_*` / `prior_*` / `ever_*` / `_before_enrollment` 等合法基线 |
| 未声明队列筛选级联，审稿人无从审 selection bias | NC 审稿拒点 top-3 | Gate C01 `--cohort-spec`: 声明 inclusion/exclusion cascade → 单调性 + 最终行数一致性校验；publication-grade tier 不声明直接 FAIL |
| 特征列命名 `gene_BRCA1` / `rs12345` / `ENSG00000...` | 把组学数据拿来跑 MLGG 是 scope 错配 | `mlgg-lint` R028: ≥3 个组学命名前缀匹配即拒绝，引导到 Scanpy / TCGAbiolinks / PLINK |

> **MLGG 不是又一个 ML 工具包。** 它是一套达到顶刊审稿标准的 AI 协审系统——33 道 fail-closed 门控 + 119 篇 Nature Communications 真实审稿意见作为知识库。每一条建议都能引用审稿人原文作为论据。

---

## 审稿级审查机制

MLGG 的核心不是跑脚本，而是**像顶刊审稿人一样审查你的代码**。

```
你的代码 ──→ /mlgg 审查 ──→ 发现问题 ──→ 引用审稿人原文 ──→ 给出修复代码 ──→ 重新验证
```

**三层审查架构：**

| 层 | 机制 | 能抓到什么 |
|:---|:-----|:----------|
| **第一层：28 条 AST 静态分析** | 代码模式匹配 (R001-R028) | `scaler.fit(X)` 在 split 前、SMOTE 用在 test 上、阈值在 test 选 |
| **第二层：33 道 fail-closed 门控** | 运行时验证，报告 JSON 产出 | 患者跨 split、校准 ECE > 0.1、EPV < 10、CI 宽度 > 0.20、**post-index 特征名模式抓取**（time_in_hospital / num_medications / discharge / ventilation / vasopressor）、**疾病作用域匹配**（glucose 只对糖尿病 target 报） |
| **第三层：临床语义审查 + 审稿证据** | AI agent 理解代码含义 + 119 篇审稿 KB + **issue-code 重排检索** | 出院后变量预测出院后结局、HbA1c 定义泄漏、亚组校准缺失。RAG 不只按 severity 排，而是基于失败代码的关键词（ppv / baseline / imputation）对 tag 和原文重排 |

**审稿证据库 (Peer Review Knowledge Base)：**

从 119 篇 Nature Communications 医学 ML 论文中结构化提取了 452 条审稿意见。**检索精度经过 2026-04 重构**：原版只按 mlgg_gates 过滤 + severity 排序（在 clinical_metrics_gate 的 ppv 失败上精度仅 20%）；现在用 `retrieve_for_failure(gate_name, issue_codes)`——分词失败代码 → 过滤 stopwords → 按 `tag_overlap × 3 + text_overlap` 重排 → 无匹配时回退 severity 兜底。

| 类别 | 占比 | 示例审稿人原话 |
|:-----|:-----|:-------------|
| 评估指标 | 31.7% | *"AUC should not be the only metric. Provide PPV, NPV, calibration."* |
| 研究设计 | 21.6% | *"Using future data which would not be available for clinical decision."* |
| 报告规范 | 13.9% | *"Should report calibration and net benefit analysis."* |
| 外部验证 | 5.6% | *"External validation on independent cohort is essential."* |

**KB 索引完整性**：所有 452 条 concerns 现在都有至少 1 个 `mlgg_gates` 映射（旧版 73.6% 是空数组，retrieval 对四分之三 KB 失效）。Warning-only gate（strict 模式升 fail 的）现在也会拉取 peer review context——不再因为"只有 warning 没有 failure"而背书为空。

**KB 覆盖诚实说明**：KB 是 NC 已发表论文的审稿意见——pre-publication filter 已经筛掉了严重 leakage。结果：leakage 类审稿意见稀少（≈4%）；KB 强在 evaluation / reporting / external validation，弱在 leakage。遇到 leakage 失败时优先依赖 `leakage_gate` + `mlgg-lint` R001-R028，不依赖 KB。

> 当 MLGG 发现你的代码有问题时，它不只是说"违反了规则 E02"——它会告诉你：*"NC 审稿人在 119 篇论文中 129 次（28.5%）要求完善评估指标。这是审稿人最常提出的问题类别。"*

---

## 系统能力总览

```
原始数据 ──→ 9-Phase 工作流 ──→ 33 道门控审计 ──→ 合规证书 ──→ 可发表报告
```

| 模块 | 说明 | 规模 |
|:-----|:-----|:-----|
| **33 道安全门控** | fail-closed DAG 架构，覆盖泄漏/可解释性/公平性/校准/鲁棒性/TRIPOD+AI/PROBAST+AI | 9 层并行执行 |
| **12 维量化评分** | 数据完整性/防泄漏/流水线隔离/模型选择/统计有效性/泛化证据/临床完整性/报告标准/可重复性/安全与溯源/公平性/样本量 | 0-100 分 |
| **3 级合规** | L1 (12 门, 泄漏审计) / L2 (25 门, 统计有效) / L3 (全部 33 门, 发布级) | 渐进认证 |
| **23 个模型族** | LR (L1/L2/ElasticNet) / SVM (linear/RBF) / RandomForest (balanced) / ExtraTrees / XGBoost / CatBoost / LightGBM / HistGradientBoosting / KNN / MLP / AdaBoost / RUSBoost / EasyEnsemble / BalancedRandomForest / GaussianNB / DecisionTree / TabPFN + Stacking / Soft-Voting / Weighted-Voting | 自动超参搜索 |
| **16 个真实数据集** | UCI / CDC / NCI / Vanderbilt / MIT-LCP / Framingham / Vanderbilt SUPPORT2 官方数据 | 总计 630K+ 行 |
| **多模型 SHAP 集成引擎** | 多族 L1 归一化集成 + Kendall tau 一致性 (FDR-BH 校正) + 跨模型 Spearman 排名相关 + 5 张发表级 CSV | RF/XGB/CatBoost/LGBM/LR |
| **学术合规引擎** | TRIPOD+AI 2024 (27 项) / PROBAST+AI 2025 (4 域) / STARD-AI | 全项逐条验证 |
| **审稿证据库** | 119 篇 NC 论文 × 452 条结构化审稿意见，按 gate/tag/severity 检索 | 每条建议引用原文 |
| **28 条 Lint 规则** | 静态分析检测代码级泄漏反模式 (R001-R028) | .py + .ipynb |
| **安全加固层** | HMAC-SHA256 / AES-256-GCM / 链式审计日志 / 路径穿越防护 / 受限反序列化 | fail-closed |
| **21 个分析工具** | Riley 样本量 / 校准三件套 / NRI-IDI / 学习曲线 / VIF / MNAR 敏感性 / PDP 边际效应 / FDR-BH 校正 / 时序漂移 / ... | 100% 覆盖 Nature ML Checklist |

---

## 快速开始

### 30 秒体验：检测你的数据有没有泄漏

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-governance-guard.git
cd medical-ml-governance-guard
pip install -r requirements.txt

# 用自带的心脏病数据集：划分 → 检测泄漏（2 条命令）
python3 scripts/training/split_data.py \
  --input examples/heart_disease.csv --output-dir /tmp/mlgg_demo \
  --target-col y --patient-id-col patient_id --time-col event_time \
  --strategy grouped_temporal --seed 42

python3 scripts/gates/leakage_gate.py \
  --train /tmp/mlgg_demo/train.csv --valid /tmp/mlgg_demo/valid.csv \
  --test /tmp/mlgg_demo/test.csv \
  --target-col y --id-cols patient_id --time-col event_time \
  --report /tmp/mlgg_demo/leakage_report.json
```

输出 `Status: PASS` = 数据划分正确，没有患者跨 split、没有时序泄漏。把 `heart_disease.csv` 换成你自己的 CSV 和列名就行。

> 完整 5 分钟教程见 [Beginner-Quickstart.md](references/docs/Beginner-Quickstart.md)

### AI 审稿人全程引导（推荐）

```bash
claude          # 打开 Claude Code
/mlgg           # AI 审稿人自动引导 9 阶段
```

自动完成：观察数据 → 划分 → 训练 23 模型族 → 33 道门控审查 → TRIPOD+AI 合规报告。每一步引用真实审稿意见作为论据。

### 更多入口

```bash
python3 scripts/orchestration/mlgg.py doctor         # 验证安装
python3 scripts/orchestration/mlgg.py play           # 像素风终端 UI

# 引导式建模（无需 Claude Code）
python3 scripts/orchestration/mlgg.py onboarding \
  --project-root /tmp/mlgg_demo --mode guided --yes

# 审计任何 ML 项目（无需配置）
python3 scripts/reporting/generate_audit_report.py --project-dir /path/to/project

# 静态代码扫描（28 条 AST 泄漏规则）
cd plugin && pip install -e . && cd ..
python3 -m mlgg_lint check /path/to/your_script.py
```

---

## 9 阶段工作流

MLGG 强制按 9 个阶段顺序执行，每个阶段有明确检查点，不通过不进入下一阶段。

```
  阶段一           阶段二           阶段三           阶段四
  队列定义   ────>  数据划分    ────>  预处理      ────>  特征
                     协议               管线               筛选
  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐
  │ EPV      │       │ Patient │       │ Fit on  │       │ ElasticN│
  │ Riley    │       │ disjoint│       │ train   │       │ Stability│
  │ Missing  │       │ Temporal│       │ only    │       │ Ridge   │
  │ Types    │       │ order   │       │ OneHot  │       │ control │
  └────┬─────┘       └────┬────┘       └────┬────┘       └────┬────┘
       │                  │                  │                  │
       v                  v                  v                  v
  阶段五           阶段六           阶段七           阶段八
  模型训练   ────>  评估校准    ────>  可解释性    ────>  公平性
  与选择             与校准                               与公平
  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐
  │ >=3 fam │       │ 14 metr │       │ Multi   │       │ EqOdds  │
  │ One-SE  │       │ Boot CI │       │ model   │       │ Disparate│
  │ Optimism│       │ DCA+NRI │       │ SHAP    │       │ Subgroup│
  │ LrnCurve│       │ Calibr  │       │ Kendall │       │ DCA     │
  └────┬─────┘       └────┬────┘       └────┬────┘       └────┬────┘
       │                  │                  │                  │
       └──────────────────┴────────┬─────────┴──────────────────┘
                                   v
                            阶段九：报告与合规
                            ┌─────────────────┐
                            │ TRIPOD+AI 2024  │
                            │ PROBAST+AI 2025 │
                            │ L1 / L2 / L3    │
                            │ 12-Dim Score    │
                            └─────────────────┘
```

---

### 阶段一：队列定义与样本量

> **脚本**: `cohort_definition_gate.py` &nbsp;|&nbsp; **层**: 0 &nbsp;|&nbsp; **规则**: C01, F05, Z01

#### 1.1 队列定义（MLGG-C01）

排除结局结构性不可能的记录。例如在再入院预测中，死亡/临终关怀患者不可能再入院，纳入会虚抬 AUROC (实测 +0.004)。排除规则必须在任何分析之前确定，且记录排除人数和理由 (TRIPOD+AI Item 4a)。

#### 1.2 样本量 — Riley 三准则（Riley 2019, Stat Med）

传统 EPV >= 10 规则已被证明"过于简化且缺乏证据支撑" (Riley 2019 原文)。MLGG 实现三准则：

| 准则 | 公式 (简化) | 含义 | 阈值 |
|:-----|:-----------|:-----|:-----|
| C1 收缩因子 | n >= p / ((1-S) x phi), S >= 0.9 | 预测系数收缩不超过 10% | S >= 0.90 |
| C2 Optimism | n >= p / 0.05 | R^2 表观值与调整值之差 <= 0.05 | delta <= 0.05 |
| C3 精度 | n >= phi(1-phi) / (0.05/1.96)^2 | 总体风险估计 95% CI 半宽 <= 0.05 | SE <= 0.05 |

取三者最大值为最小样本量。p = 候选参数数，phi = 事件率。

| EPV 范围 | 判定 |
|:---------|:-----|
| EPV < 5 | **FAIL** &mdash; 样本量严重不足 |
| EPV 5-10 | **WARNING** &mdash; 需要额外证据 |
| EPV 10-20 | **INFO** &mdash; 可接受，推荐 >= 20 |
| EPV >= 20 | **PASS** |

#### 1.3 数据类型自动检测

每列按基数和类型分类：

| 类型 | 检测条件 | 处理方式 |
|:-----|:---------|:---------|
| `numeric` | 高基数连续值 | 保持原值 |
| `binary` | 恰好 2 个唯一值 | 映射为 0/1 |
| `categorical` | 3-20 个唯一值 | OneHot 编码 |
| `constant` | 0-1 个唯一值 | 自动丢弃 |
| `id_or_text` | 高基数非数值 | 标记为非特征 |

输出 `feature_profile.csv`：每列的缺失率、唯一值数、描述统计。

#### 1.4 缺失值概况

按特征统计缺失率。>50% 缺失自动标记。检测缺失与结局的相关性 (|r| > 0.1 标记为 MNAR 信号)。检测纵向/横截面：患者 ID 有重复行 -> 纵向数据。

#### 1.5 可疑相关性检测

| 条件 | 判定 | 含义 |
|:-----|:-----|:-----|
| \|r\| > 0.95 | **FAIL** | 几乎确定泄漏 |
| \|r\| > 0.80 | **WARNING** | 高风险，需人工审查 |
| \|r\| > 0.50 | **INFO** | 正常预测能力 |

---

### 阶段二：数据划分

> **脚本**: `split_data.py` &nbsp;|&nbsp; **Gates**: `split_protocol_gate` + `leakage_gate` &nbsp;|&nbsp; **规则**: S01, S02

#### 2.1 患者级 disjoint 划分（MLGG-S01）

同一患者的所有记录 (如多次住院) 必须归入同一 split。违反此原则会导致模型"记住"患者特征，虚抬测试性能。实现：按 `patient_id` 分组，组为最小不可分割单位。

#### 2.2 三种划分策略

| 策略 | 适用数据 | 时间列 | 原理 |
|:-----|:---------|:-------|:-----|
| `grouped_temporal` | 纵向 EHR / 队列 | 必须 | 按患者首次事件时间排序，前 60% train / 中 20% valid / 后 20% test。保证 train 时间 < valid < test (MLGG-S02) |
| `grouped_random` | 横截面调查 (NHANES, BRFSS) | 不需要 | 患者随机打乱后按比例分配。`--cross-sectional` 跳过时序检查 |
| `stratified_grouped` | 横截面 + 需保证正类比例一致 | 不需要 | 按结局标签分层，层内随机分配，各 split 正类率差异 < 3% |

#### 2.3 安全约束

| 约束 | 阈值 | 违反后果 |
|:-----|:-----|:---------|
| 每 split 最少行数 | 20 | FAIL |
| 每 split 最少正例 | 10 | FAIL |
| 每 split 最少负例 | 10 | FAIL |
| 每 split 最少独立患者 | 5 | FAIL |
| 正类率跨 split 漂移 | > 10% | WARNING |
| 患者 ID 跨 split 重叠 | 任何 | **FAIL (零容忍)** |

#### 2.4 泄漏检测（7 类正则）

泄漏门控检测 7 类可疑特征名模式：

| 类别 | 匹配模式 | 示例 |
|:-----|:---------|:-----|
| 显式标记 | `future`, `leak` | `future_value`, `data_leak` |
| 目标别名 | `target`, `label`, `outcome` | `target_col`, `outcome_flag` |
| 确诊后变量 | `pred_`, `confirmed_`, `staging` | `pred_risk`, `confirmed_diagnosis` |
| 病理结果 | `pathology`, `biopsy_result`, `histology` | `biopsy_result_code` |
| 时间泄漏 | `next_`, `future_`, `post_`, `after_` | `next_visit_date`, `post_surgery` |
| 结局日期 | `diagnosis_date`, `death_date`, `event_date` | `discharge_date` |
| 衍生指标 | `readmit`, `mortality_flag`, `los_days` | `readmit_30d`, `survival_status` |

#### 2.5 输出工件

- `train.csv`, `valid.csv`, `test.csv`
- `split_protocol.json` (自动生成，gate 可验证)
- `split_report.json` (SHA-256 checksums)

---

### 阶段三：预处理

> **脚本**: `train_select_evaluate.py` Pipeline &nbsp;|&nbsp; **规则**: P01-P06

#### 3.1 铁律：所有 fit() 仅在训练集（P01/P03/P04）

预处理管道结构：`Imputer -> Scaler -> Classifier`。每一步的统计量 (中位数、均值、标准差、类别映射) 只从训练集计算，验证集和测试集只调用 `.transform()`。这防止了最常见的数据泄漏 &mdash; 预处理泄漏 (Kaufman 2012, ACM TKDD)。

#### 3.2 分类变量编码（MLGG-P05）

| 特征类型 | 检测条件 | 编码方法 | OOD 安全性 |
|:---------|:---------|:---------|:-----------|
| Binary (2 值) | `nunique == 2` | 按 train 映射为 0/1, `.fillna(0.0)` | 未见类别 -> 0.0 |
| Categorical (3-15 值) | `3 <= nunique <= 15` | OneHot, train 类别决定 dummy 列 | 未见类别 -> 全零行 |
| Numeric (>15 值且连续) | `nunique > 15` and numeric | 保持原值 | N/A |
| High-cardinality (>15 非数值) | `nunique > 15` and string | 保持原值 (用户自行处理) | N/A |

**为什么不用 OrdinalEncoder 编码名义变量**: 名义变量 (如 race=1,2,3,4,5) 用 OrdinalEncoder 会让模型假设 race=5 是 race=1 的 5 倍 &mdash; LR 系数失去临床意义 (实测：改为 OneHot 后 LR AUROC +0.02)。

#### 3.3 分层缺失策略（MLGG-P06, Madley-Dowd 2019）

不使用固定阈值 (如"丢弃 >60% 缺失")，而是按缺失机制分层：

| 层级 | 缺失率 | 推荐策略 | 理由 |
|:-----|:-------|:---------|:-----|
| Tier 4 | > 80% | 丢弃原值，保留缺失指示变量 | 原值极度稀疏，"是否缺失"本身可能有预测价值 |
| Tier 3 | 40-80% | 插补 + 缺失指示变量 | 插补可能不准，指示变量补偿 |
| Tier 2 | 5-40% | 插补 + 缺失指示变量 | 标准 MAR 处理 |
| Tier 1 | < 5% | 简单插补 (中位数/众数) | 缺失太少，不值得复杂处理 |

> **实现说明**: 当前代码统一使用 `SimpleImputer(median, add_indicator=True)`。上述分层是推荐的分析框架。树模型 (RF/XGB/LGBM) 不添加 indicator 列 (原生处理缺失)。

> **机制检验强制**: 任何特征缺失率 >5% 时，`missingness_policy_gate` 要求 policy 中声明 `mechanism_assessment`（方法 + 结论: MCAR/MAR/MNAR/mixed）；>40% 时额外要求 `mnar_sensitivity` 分析结果。参考 Madley-Dowd 2019, Cro 2020。

#### 3.4 SMOTE 立场

van den Goorbergh 2022 (JAMIA) 证明 SMOTE 严重损害风险预测模型的概率校准。MLGG 默认不使用 SMOTE，改用 `class_weight="balanced"` + 事后 Platt scaling 校准。

---

### 阶段四：特征筛选

> **脚本**: `train_select_evaluate.py` &nbsp;|&nbsp; **规则**: F01-F06

#### 4.1 设计哲学

Harrell 2015 和 Steyerberg 2019 推荐"临床先验预指定 + 惩罚收缩"而非数据驱动筛选。但当候选特征远超临床知识时，MLGG 提供有控制的筛选路径。

#### 4.2 Elastic Net CV（Zou & Hastie 2005）

联合调优正则化参数：
- alpha in {0.1, 0.3, 0.5, 0.7, 1.0}: 0.1 接近 Ridge (保留所有特征), 1.0 等价 LASSO (稀疏)
- C in {0.001, 0.01, 0.1, 1.0, 10.0}
- 5 折 StratifiedKFold 内部 CV，选择 PR-AUC 最优组合
- **分组选择** (Yuan & Lin 2006, Group LASSO): OneHot 产生的 dummy 列属于同一原始变量，必须同进同退

#### 4.3 稳定性选择（Meinshausen & Buhlmann 2010）

- 100 次子采样 (每次抽 80% 训练集)
- 每次拟合 Elastic Net (C=0.3, L1)，记录非零特征
- 特征入选概率 = 被选中的次数 / 100
- 保留入选概率 > 0.6 的特征
- **修正**: 使用全局 train median 做插补 (而非 bootstrap 局部 median)，避免信息泄漏

#### 4.4 Ridge 对照（Harrell 2015）

始终与"不做筛选、只用 Ridge 收缩"的全量模型比较。如果 Elastic Net 选择后 PR-AUC 损失 > 0.005，回退到全量 Ridge。

#### 4.5 废弃：单因素筛选

Heinze 2018 (Biometrical Journal) 明确反对单因素 p 值筛选：导致多重比较问题、丢弃弱但联合有效的特征、引入选择偏倚。MLGG 只将单因素分析 (Mann-Whitney U) 作为诊断工具，不用于特征选择决策。

---

### 阶段五：模型训练与选择

> **脚本**: `train_select_evaluate.py` &nbsp;|&nbsp; **门控**: `model_selection_audit_gate` &nbsp;|&nbsp; **规则**: M01-M04, R01

#### 5.1 训练管线结构

每个候选模型以 sklearn `Pipeline` 形式构造，确保预处理和模型训练严格绑定：

```
Pipeline([
    ("imputer",    SimpleImputer(strategy="median", add_indicator=True)),
    ("scaler",     StandardScaler()),
    ("classifier", model)      # 如 LogisticRegression / RandomForest / XGBoost ...
])
```

- **Imputer**: 中位数插补 + 缺失指示列（树模型不加 indicator，原生处理缺失）
- **Scaler**: StandardScaler 仅在训练集 fit，验证/测试集只 transform
- **Classifier**: 由模型族决定，带预定义超参网格

#### 5.2 候选模型族（MLGG-M03：>= 3）

MLGG 支持 23 个模型族（详见 [23 个模型族](#23-个模型族) 节），推荐至少比较 3 族：

| 推荐族 | 优势 | 典型超参网格 |
|:-------|:-----|:------------|
| **Logistic Regression** (L1/L2/ElasticNet) | 线性基线，系数可直接临床解释 | C in {0.01, 0.1, 1, 10}, penalty in {l1, l2, elasticnet} |
| **Random Forest** | 非线性 + 特征交互，天然处理缺失 | n_estimators in {300, 500}, max_depth in {4, 5, 6} |
| **XGBoost / LightGBM** | 梯度提升，通常性能最优 | n_estimators in {200, 400}, max_depth in {3, 5, 7}, learning_rate in {0.01, 0.05, 0.1} |
| **CatBoost** (可选) | 原生类别编码 | depth in {4, 6, 8}, learning_rate in {0.03, 0.1} |
| **SVM** (可选) | 高维空间，小样本有优势 | C in {0.1, 1, 10}, kernel in {linear, rbf} |

调优方式：Optuna TPE sampler 或 Grid Search，在**验证集**上调优，绝不碰测试集。默认 5 折 StratifiedKFold 内部 CV。

#### 5.3 模型复杂度排名

one-SE 规则需要"选最简单模型"，因此每个候选模型有一个复杂度分数。排名规则：

```
族基础复杂度（越小越简单）：
  Gaussian NB (1) < LR-L1 (2) < LR-L2 (3) < LR-EN (4) < KNN (5)
  < Decision Tree (6) < SVM-linear (7) < SVM-rbf (8) < AdaBoost (9)
  < RF (10) < ExtraTrees (11) < HistGB (12) < MLP (13)
  < XGBoost (14) < CatBoost (15) < LightGBM (16) < TabPFN (17)

族内排名：按超参复杂度加分
  - LR: C 越大越复杂（正则化越弱）
  - RF: max_depth 越深 + n_estimators 越多 = 越复杂
  - XGBoost: 深度 x 树数量 x 学习率的组合

集成模型：复杂度 = 15000+（永远排在最后）
```

#### 5.4 类别不平衡处理

医学数据通常严重不平衡（正类 5-15%）。MLGG 支持 7 种策略，**所有重采样仅在训练集上执行**：

| 策略 | 实现 | 适用场景 |
|:-----|:-----|:---------|
| `auto` | 根据不平衡比自动选择 | 默认推荐 |
| `none` | 不做任何处理 | 平衡数据 |
| `class_weight` | `class_weight="balanced"` | **推荐** &mdash; 不生成合成样本，需配合 Platt scaling 校准 |
| `random_oversample` | 少数类随机重复采样 | 简单，不引入噪声 |
| `random_undersample` | 多数类随机丢弃 | 数据量充足时 |
| `smote` | 合成少数类过采样 | **慎用** &mdash; van den Goorbergh 2022 证明损害校准 |
| `adasyn` | 自适应合成采样 | **慎用** &mdash; 同 SMOTE 问题 |

> **铁律**: 重采样只作用于训练集（`apply_imbalance_strategy_to_train()`），验证集和测试集保持原始分布不变。

#### 5.5 交叉验证细节

| 参数 | 默认值 | 说明 |
|:-----|:-------|:-----|
| CV 折数 | 5 | StratifiedKFold，保持各折正类比例一致 |
| 最小折数 | 3 | 低于 3 折强制报错 |
| 选择数据源 | `cv_inner` | 模型选择基于内部 CV 的 OOF 预测 |
| 备选数据源 | `valid` | 使用独立验证集（适合大数据集） |
| 嵌套 CV | `nested_cv` | 外层选模型 + 内层调参（最严格但最慢） |

当选择 `cv_inner` 时，模型在训练集上做 K 折 CV，收集 out-of-fold 预测，在 OOF 上计算 PR-AUC 用于模型选择。**测试集自始至终不参与任何选择过程。**

#### 5.6 模型选择标准（MLGG-M04, Yang KDD 2023）

**不使用 train-test gap 选模型。** Yang et al. 2023 证明验证集性能是更可靠的模型选择准则：

```
  错误做法:  选 |AUC_train - AUC_test| 最小的模型
  MLGG:      选验证集 PR-AUC 最高的模型（one-SE 规则破平局）
```

**One-SE 规则**：在最优性能的 1 个标准误范围内，选择复杂度最低的模型（偏好 LR > RF > XGBoost）：

```python
best_se = best_std / sqrt(n_folds)        # 最优模型的标准误
threshold = best_mean - best_se            # 可接受的最低性能
eligible = [m for m in candidates if m.mean >= threshold]  # 筛选合格模型
selected = min(eligible, key=complexity_rank)               # 选最简单的
```

#### 5.7 过拟合回调机制

当选定模型的 train-test gap 超过阈值时，自动触发过拟合回调：

```
1. 计算过拟合风险：
   - PR-AUC gap > 0.15  →  risk = "high"
   - PR-AUC gap > 0.10  →  risk = "medium"
   - 否则               →  risk = "low"

2. 如果 risk >= "medium"：
   - 在候选池中寻找 gap 更小的替代模型
   - 替代模型必须仍满足 one-SE 规则
   - 如果找到，切换到替代模型并记录 fallback_trace
   - 如果没找到，保留原模型但发出 WARNING

3. 输出：
   - callback_activated: true/false
   - original_model_id: 原始选择
   - fallback_trace: 替代搜索过程
```

> Gap 仍然**不用于模型选择**——回调仅在选择完成后作为安全网触发。

#### 5.8 阈值选择（MLGG-M02）

在**验证集**上通过 F-beta 最大化 + 临床约束确定最优分类阈值。阈值绝不在测试集上选择（MLGG-M01 零容忍）。

**选择流程**：

```
1. 生成 299 个分位数阈值 + 0.5（共 300 个候选）
2. 对每个阈值，在选择集（valid/cv_inner OOF）上计算指标
3. 筛选满足所有临床约束的"可行阈值"
4. 在可行阈值中选 F-beta 最大的
5. 如果有 guard split（内部交叉验证），在 guard split 上二次验证
6. 如果 guard split 无可行阈值，选约束违反最小的阈值
```

默认临床约束（可通过 `--sensitivity-floor` 等参数覆盖）：

| 临床指标 | 默认下限 | 含义 |
|:---------|:---------|:-----|
| Sensitivity | >= 0.70 | 漏诊率上限 30% |
| NPV | >= 0.70 | 阴性预测值下限 |
| Specificity | >= 0.60 | 误诊率上限 40% |
| PPV | >= 0.50 | 阳性预测值下限 |

> **为什么不用 Youden's J**: Youden's J（Sensitivity + Specificity - 1）不考虑临床约束。F-beta + 临床下限可以保证模型在临床可接受的范围内运行。例如，Youden's J 可能选到 Sensitivity=0.50 的阈值（漏诊一半患者），而 MLGG 的约束会阻止这种情况。

#### 5.9 概率校准

`class_weight="balanced"` 会扭曲预测概率（ECE 可达 0.3-0.4）。MLGG 在训练后自动进行概率校准：

| 校准方法 | 实现 | 适用场景 |
|:---------|:-----|:---------|
| Platt scaling | `CalibratedClassifierCV(method="sigmoid")` | **默认** &mdash; 大多数模型适用 |
| Isotonic regression | `CalibratedClassifierCV(method="isotonic")` | 非单调关系 |
| 无校准 | &mdash; | 模型原生概率已校准（如 LR） |

校准器在**验证集**上 fit，应用于测试集。校准后 ECE 应 < 0.06。

#### 5.10 Bootstrap Optimism Correction（Steyerberg 2019 Ch.17）

内部验证方法，估计模型性能的"乐观偏差"：

```
对 B 次 bootstrap 重采样（B >= 100）：
    1. 在 bootstrap 样本上拟合模型
    2. 在 bootstrap 样本上评分 → apparent_i
    3. 在原始训练集上评分 → test_i
    4. optimism_i = apparent_i - test_i

校正后性能 = 原始表观性能 - mean(optimism_i)
```

输出 `bootstrap_optimism_correction` 块，包含 pr_auc / roc_auc / brier 三个指标的 apparent / optimism / corrected 值。

#### 5.11 学习曲线（Figueroa 2012）

评估模型是否已"收敛"——训练数据再增加是否还能提升性能：

- 在 {10%, 20%, 30%, 50%, 70%, 85%, 100%} 训练集比例上分别训练
- 每个比例使用分层子采样保持正类率一致
- 收敛判定：最后 3 个点的相对标准差 < 2%
- 输出 `learning_curve` 块：每个点的 train_score / valid_score + converged flag
- 如果未收敛，建议增加数据量或简化模型

#### 5.12 定义列强制排除

`--definition-cols HbA1c,fasting_glucose` &mdash; 结局定义列被**强制排除**，不再是建议。防止最常见的医学 ML 泄漏：用于定义结局的变量混入预测特征。

#### 5.13 输出工件

训练完成后生成以下工件，全部经 HMAC-SHA256 签名：

| 工件 | 文件 | 内容 |
|:-----|:-----|:-----|
| 最优模型 | `model.pkl` | 序列化的 Pipeline（Imputer + Scaler + Classifier + 校准器 + 阈值） |
| 模型池 | `model_pool.pkl` | 各族最优候选模型（供 SHAP 分析用） |
| 选择报告 | `model_selection_report.json` | 候选池、CV 分数、one-SE 跟踪、选中模型 |
| 评估报告 | `evaluation_report.json` | 测试指标、CI、过拟合分析、校准、DCA、NRI/IDI |
| 预测轨迹 | `prediction_trace.csv.gz` | 每行的 y_true / y_score / y_pred（供回放验证） |
| 特征工程报告 | `feature_engineering_report.json` | 特征选择过程、稳定性、VIF、非线性检验 |
| 分布报告 | `distribution_report.json` | 特征分布漂移（JSD）across train/valid/test |
| CI 矩阵报告 | `ci_matrix_report.json` | 所有指标的 Bootstrap 95% CI |
| 鲁棒性报告 | `robustness_report.json` | 时间片和亚组性能 |
| 种子敏感性报告 | `seed_sensitivity_report.json` | 多种子稳定性分析 |
| 置换零分布 | `permutation_null.txt` | PR-AUC 的置换检验零分布 |

---

### 阶段六：评估与校准

> **脚本**: `train_select_evaluate.py` + 13 道统计门控 &nbsp;|&nbsp; **规则**: E01-E06

#### 6.1 完整 14 指标面板（MLGG-E02）

测试集一次性使用，报告 5 域 14 项指标 (对标 Riley et al. Lancet Digital Health 2025; doi:10.1016/S2589-7500(25)00021-4)：

| 域 | 指标 | 目标/解读 |
|:---|:-----|:---------|
| **区分度** | AUROC, PR-AUC | 模型区分正/负的能力。PR-AUC 对不平衡数据更敏感 |
| **校准** | 校准截距(->0), 斜率(->1), O:E 比(->1), ECE | 预测概率与实际风险的一致性 (Van Calster 2019) |
| **整体性能** | Brier score | BSS = 1 - Brier_model / Brier_prevalence, >0 优于基线 |
| **分类** | Sensitivity, Specificity, PPV, NPV, F1, **MCC**, Accuracy | MCC 是不平衡数据下唯一可靠的单一分类指标 (Chicco 2020) |
| **临床效用** | **LR+, LR-**, DCA 净效用, NRI, IDI | LR+ > 5 有临床价值, LR- < 0.2 可排除 (Deeks 2004) |

> **为什么必须报 MCC 和 LR+/LR-**: AUROC 0.65 可能看起来"还行"，但 MCC 0.12 (接近随机) 和 LR+ 1.6 (无决策价值) 揭示模型真实能力。仅报 AUROC/F1 是选择性报告。

#### 6.2 校准三件套（Van Calster 2019, BMC Medicine）

通过 logistic recalibration 拟合 `logit(y) ~ a + b x logit(y_hat)`：

| 指标 | 理想值 | 偏离含义 | Gate 阈值 |
|:-----|:-------|:---------|:---------|
| 校准截距 a | 0 | a < 0 系统高估; a > 0 系统低估 | \|a\| <= 1.00 |
| 校准斜率 b | 1 | b < 1 过拟合; b > 1 欠拟合 | 0.80 <= b <= 2.00 |
| O:E 比 | 1 | 观察事件数 vs 期望事件数 | 0.70-1.43 (fail), 0.80-1.25 (warn) |
| ECE | 0 | 预测概率分组误差 | <= 0.06 |
| CITL | 0 | Calibration-in-the-large | \|CITL\| <= 0.10 (fail), <= 0.05 (warn) |

#### 6.3 决策曲线分析（Vickers 2006）

DCA 评估模型在不同决策阈值下的临床净效用：

| 参数 | 默认值 | 含义 |
|:-----|:-------|:-----|
| 阈值网格 | 0.05-0.50, step 0.05 | 临床决策阈值范围 |
| 优势覆盖率 | >= 50% | 模型优于"全治疗"的阈值比例 |
| 平均优势 | >= 0.0 | 平均净效用改善 |

#### 6.4 NRI / IDI（Pencina 2008）

| 指标 | 含义 |
|:-----|:-----|
| Categorical NRI | 在阈值处，新模型正确重分类的净比例 |
| Continuous NRI | 不依赖阈值的重分类改善 |
| IDI | 事件组和非事件组预测概率差的改善量 |

#### 6.5 Bootstrap 95% CI（MLGG-E01）

所有主要指标使用 percentile bootstrap 计算 95% CI：

| 参数 | 默认值 | 约束 |
|:-----|:-------|:-----|
| Test CI resamples | 500 | >= 200 (evaluation_quality_gate) |
| CI matrix resamples | 2000 | 覆盖所有 split 和 cohort |
| Permutation resamples | 300 | 置换检验 零分布 |
| CI width max | 0.20 | 超过则 FAIL |
| Min baseline delta | 0.01 | 必须优于 prevalence baseline |

#### 6.6 泛化差距阈值

| 比较 | 指标 | WARNING | FAIL |
|:-----|:-----|:--------|:-----|
| train -> valid | PR-AUC | > 0.05 | > 0.08 |
| valid -> test | PR-AUC | > 0.04 | > 0.06 |
| train -> test | F2-beta | > 0.07 | > 0.10 |
| valid -> test | Brier | > 0.02 | > 0.03 |

Gap 仅用于诊断报告，不用于模型选择 (MLGG-E04)。

#### 6.7 多种子稳定性（MLGG-R02）

| 指标 | Std Max | Range Max |
|:-----|:--------|:----------|
| PR-AUC | 0.03 | 0.08 |
| F2-beta | 0.05 | 0.12 |
| Brier | 0.02 | 0.05 |

Strict mode 要求 >= 5 seeds, non-strict >= 3 seeds。

#### 6.8 事后校准（MLGG-E05）

`class_weight="balanced"` 会扭曲预测概率 (ECE 可达 0.3-0.4)。必须用 Platt scaling 或 isotonic regression 在**验证集**上拟合校准器，然后应用于测试集。校准后 ECE 应 < 0.06。

---

### 阶段七：多模型 SHAP 可解释性

> **门控**: `shap_interpretability_gate` &nbsp;|&nbsp; **层**: 5

#### 7.1 为什么多模型而非单模型

不同模型族有不同的归纳偏差：RF 偏好交互特征、XGBoost 偏好非线性分段、LR 只看线性效应。单模型 SHAP 排名反映的是该模型的"世界观"，不是数据的真相 (Rashomon 效应, Breiman 2001)。多模型平均更鲁棒。

#### 7.2 计算流程

```
For each model family m in {RF, XGB, CatBoost, LGBM, LR, ...}:
    1. Extract clf from Pipeline, transform data with preceding steps
    2. Select Explainer:
       - TreeExplainer  (exact, O(TLD)):  RF / XGB / CatBoost / LGBM
       - LinearExplainer (exact, O(MxD)):  LR
       - KernelExplainer (approx, O(2^M)): SVM / KNN / MLP
    3. Background data: train subset (default 200 rows)
    4. Explanation data: test subset (default 500 rows)
    5. Compute SHAP values -> (n_explain x n_features) matrix
```

#### 7.3 比例归一化集成（PMC11513550）

```
For each model m:
    abs_importance_m = mean(|SHAP_m|, axis=samples)    -> (n_features,)
    proportion_m     = abs_importance_m / sum(...)      -> sum = 1

Cross-model ensemble:
    ensemble_proportion = mean(proportion_m, for all m) -> equal-weight average
```

L1 归一化消除模型间尺度差异 (RF SHAP 值在 [0, 0.02], XGBoost 在 [0, 0.15])，确保每个模型族投票权相等。

#### 7.4 跨模型一致性检验

| 检验 | 含义 | FAIL | WARN |
|:-----|:-----|:-----|:-----|
| Kendall tau (FDR-BH 校正) | 两个模型的特征重要性排名相关 | tau < 0.3 | tau < 0.5 |
| Top-N Jaccard | Top-10 特征集合重叠度 | &mdash; | Jaccard < 0.3 |
| Direction consistency | 所有模型 signed SHAP 同向? | &mdash; | `mixed` 方向 |
| Extreme concentration | 单特征 > 50% 总重要性 | &mdash; | WARNING |

> 当模型族 >= 3 时，多对 Kendall tau P 值自动应用 Benjamini-Hochberg FDR 校正，避免多重比较假阳性。

#### 7.5 PDP 边际效应（Partial Dependence，互补 SHAP）

SHAP 对相关特征可能产生误导（联盟博弈论假设）。PDP 提供互补视角——展示单个特征对预测的边际效应曲线：

- 自动对 SHAP Top-K 特征（默认 5）计算 PDP（`sklearn.inspection.partial_dependence`）
- 跨所有模型族分别计算，可观察不同模型对同一特征的响应差异
- 零方差特征自动跳过并发出 `PDP_FEATURE_CONSTANT` 警告

#### 7.6 五张发表级 CSV 表格

| 表格 | 文件名 | 用途 | 列 |
|:------|:-----|:--------|:--------|
| **A** | `shap_table_a_ensemble_importance.csv` | 论文主表 | 排名、特征、集成比例、方向、各模型比例 |
| **B** | `shap_table_b_per_model_detail.csv` | 审稿人补充表 | 特征、每模型 MeanAbsSHAP / 比例 / 带符号 SHAP / 排名 |
| **C** | `shap_table_c_rank_agreement.csv` | 方法学证据 | 模型A、模型B、Kendall_tau、P 值 (FDR 校正)、Top10 重叠、Jaccard |
| **D** | `shap_table_d_case_explanations.csv` | 临床叙事 | 病例索引、风险类别、真实标签、预测分数、Top-3 驱动特征 |
| **E** | `pdp_table_e_marginal_effects.csv` | 边际效应 | 模型族、特征、特征值、PD 值 |

每张 CSV 首行为方法论注释 (`# Method: ...`)，可被 `pd.read_csv(comment="#")` 跳过。

---

### 阶段八：公平性与亚组分析

> **门控**: `fairness_equity_gate` &nbsp;|&nbsp; **规则**: Q01, Q02

#### 8.1 亚组分析（MLGG-Q01, TRIPOD+AI Item 16b）

按保护属性 (race, gender, age) 分组，每组独立计算：AUROC, PR-AUC, Sensitivity, Specificity, PPV, FPR, prevalence。

#### 8.2 公平性阈值（7 项指标）

| 指标 | WARNING | FAIL | 定义 |
|:-----|:--------|:-----|:-----|
| Equalized odds gap (sensitivity) | > 0.10 | > 0.15 | 各亚组灵敏度的最大差距 |
| Disparate impact ratio (80% rule) | < 0.85 | < 0.80 | 少数群体/多数群体阳性预测率比 |
| Subgroup PR-AUC minimum | < 0.50 | < 0.40 | 任何亚组的最低性能 |
| FPR parity gap (HEAL) | > 0.10 | > 0.15 | 各亚组假阳性率的最大差距 |
| FNR parity gap (HEAL) | > 0.10 | > 0.15 | 各亚组假阴性率的最大差距 |
| PPV parity gap (预测值公平性) | > 0.10 | > 0.15 | 各亚组 PPV 的最大差距 |
| Calibration slope deviation (校准公平性) | > 0.20 | > 0.30 | 各亚组校准斜率偏离 1.0 的最大值 |

> **多重比较警告**: 当 N 特征 x 7 指标 > 10 次比较时，自动发出 multiplicity warning 并报告 Bonferroni 调整后 alpha，避免假阳性。

#### 8.3 小亚组处理（MLGG-Q02）

| 亚组大小 | 处理方式 |
|:---------|:---------|
| n < 20 | 不计算公平性指标 |
| n 20-50 | 计算但标记"不稳定" |
| n 50-200 | 计算，发出 WARNING |
| n >= 200 | 完全可靠 |

#### 8.4 不可能定理声明

当报告 >= 3 个公平性指标时，自动提示不可能定理 (Chouldechova A. Big Data 2017;5(2):153-163; Kleinberg J et al. ITCS 2017)：除基率相等或完美预测外，不可能同时满足所有公平性标准。

---

### 阶段九：报告与合规

> **门控**: `publication_gate` + `self_critique_gate` + `security_audit_gate` &nbsp;|&nbsp; **规则**: T01

#### 9.1 TRIPOD+AI 2024 清单（Collins 2024, BMJ）

27 项逐项核对，机器验证每项有对应证据文件。17 项为必须项 (含 6 项 AI 新增)：

| 新增 AI 项 | 要求 |
|:-----------|:-----|
| Item 12 | 公平性评估已报告 |
| Item 13 | 可解释性分析已报告 |
| Item 18 | 模型不确定性已报告 |
| Item 20 | 公平性结果已报告 |
| Item 24 | AI 特定局限性已讨论 |
| Item 27 | 模型/代码可用性已声明 |

#### 9.2 PROBAST+AI 2025 偏倚风险（Moons 2025, BMJ）

4 域评估，16 个信号问题：

| 域 | 评估内容 |
|:---|:---------|
| D1 Participants | 数据来源、入排标准、代表性 |
| D2 Predictors | 特征定义、时间可得性、盲法 |
| D3 Outcome | 结局定义、判定方法、时间窗 |
| D4 Analysis | 样本量、缺失处理、模型选择、验证 |

每域判定 low / high / unclear。总体 ROB 必须为 `low` 才能声称 publication-grade。

#### 9.3 三级合规（L1/L2/L3）

| 等级 | 名称 | 门控数 | 适用场景 | TRIPOD+AI | PROBAST ROB |
|:------|:-----|:------|:-----------------|:----------|:-----------|
| **L1** | 泄漏审计 | 12 | 会议论文、初步报告 | &mdash; | &mdash; |
| **L2** | 统计有效 | 25 | 专业期刊（JAMIA、npj DM） | >= 17/27 | low/unclear |
| **L3** | 发布级 | **全部 33 门** | Nature Medicine、Lancet、JAMA、BMJ | >= 23/27 | **low** |

> **外部验证政策**: 无外部验证数据时，`external_validation_gate` 返回 `status="skipped"`，总审计评分硬性上限 85 分（不可能达到 >=90 顶刊级），L3 合规自动阻断，并强制要求在 Limitations 中声明。支持三种外部验证类型：`cross_period`（时间验证）/ `cross_institution`（地理验证）/ `independent_cohort`（独立队列）。

**L1 Gates (12)**: request_contract, manifest, execution_attestation, leakage, split_protocol, covariate_shift, definition_guard, feature_lineage, imbalance, missingness, tuning, reporting_bias

**L2 adds (13)**: model_selection_audit, feature_engineering_audit, clinical_metrics, prediction_replay, generalization_gap, seed_stability, calibration_dca, ci_matrix, metric_consistency, evaluation_quality, permutation, sample_size, robustness

**L3 adds (8)**: distribution_generalization, external_validation, fairness_equity, cohort_definition, shap_interpretability, publication, self_critique, security_audit

#### 9.4 结构化局限性讨论

必须覆盖：数据来源局限、时间有效性、编码体系变化 (ICD-9 -> ICD-10)、外部效度、公平性局限、DCA 临床效用结论。如 DCA 显示无净效用，必须诚实报告 &mdash; 不隐瞒负面结果。

---

## 33 道安全门控 (Gate DAG)

33 道门控按有向无环图 (DAG) 分 9 层执行。同层可并行，全部通过才能声称 L3 Publication-Grade。

```
层 0  契约验证           cohort_definition  |  request_contract
   |
层 1  指纹锁定           manifest_lock
   |
层 2  执行证明     execution_attestation
   |
层 3  数据验证 (4 并行)     leakage  |  split_protocol  |  covariate_shift  |  reporting_bias
   |
层 4  策略审计 (5 并行)   definition_guard  |  feature_lineage  |  imbalance  |  missingness  |  tuning
   |
层 5  模型审计 (4 并行)    model_selection_audit  |  feature_engineering  |  clinical_metrics  |  shap
   |
层 6  统计验证 (13 并行)   calibration_dca  |  ci_matrix  |  distribution  |  eval_quality
                          external_validation  |  fairness  |  gap  |  metric_consistency
                          permutation  |  prediction_replay  |  robustness  |  sample_size  |  seed
   |
层 7  发布聚合     publication_gate
   |
层 8  终审 (2 并行)    self_critique  |  security_audit
```

<details>
<summary><strong>33 道门控详细说明（点击展开）</strong></summary>

| # | 层 | 门控 | 检查内容 | 输出报告 |
|:--|:------|:-----|:---------------|:-------------|
| 1 | 0 | `cohort_definition_gate` | EPV 充分性、Riley 三准则、数据类型、缺失值、可疑相关性 | `cohort_definition_report.json` |
| 2 | 0 | `request_contract_gate` | 请求 JSON 模式、文件路径、发布策略反降级保护 | `request_contract_report.json` |
| 3 | 1 | `manifest_lock` | SHA-256 加密锁定所有数据/配置/评估/门控脚本指纹 | `manifest.json` |
| 4 | 2 | `execution_attestation_gate` | 分离签名验证 + **外部 `trusted_signers.json` 指纹白名单** + `--max-age-hours` 新鲜度（默认 168h 防重放）+ bundle 路径沙箱（拒绝 symlink 逃逸）+ 见证人仲裁。详见 `references/attestation/README.md` | `execution_attestation_report.json` |
| 5 | 3 | `leakage_gate` | 行哈希重叠、患者 ID 重叠、时间边界违规、7 类特征名正则 | `leakage_report.json` |
| 6 | 3 | `split_protocol_gate` | 患者级 disjoint 划分、时序正确性、患病率检查、最小划分大小 | `split_protocol_report.json` |
| 7 | 3 | `covariate_shift_gate` | 逐特征 Jensen-Shannon 散度、患病率漂移、缺失率漂移 | `covariate_shift_report.json` |
| 8 | 3 | `reporting_bias_gate` | TRIPOD+AI 2024 (17 项) + PROBAST+AI 2025 (6 域) + STARD-AI 清单 | `reporting_bias_report.json` |
| 9 | 4 | `definition_variable_guard` | 阻止结局定义变量作为预测特征；**循环定义检测、时间窗文档化、预测后特征泄漏检查** | `definition_guard_report.json` |
| 10 | 4 | `feature_lineage_gate` | 阻止索引时间后衍生特征进入训练 | `lineage_report.json` |
| 11 | 4 | `imbalance_policy_gate` | 类别不平衡策略、训练集独占重采样、患病率验证 | `imbalance_policy_report.json` |
| 12 | 4 | `missingness_policy_gate` | 缺失数据策略、MICE 规模保护、插补器隔离；**>5% 强制机制检验、>40% 强制 MNAR 敏感性** | `missingness_policy_report.json` |
| 13 | 4 | `tuning_leakage_gate` | 超参调优协议、测试集隔离、CV 嵌套 | `tuning_leakage_report.json` |
| 14 | 5 | `model_selection_audit_gate` | one-SE 规则回放、>= 3 候选模型、逻辑回归基线、指纹验证 | `model_selection_audit_report.json` |
| 15 | 5 | `feature_engineering_audit_gate` | 特征组来源、训练集独占范围、稳定性证据 | `feature_engineering_audit_report.json` |
| 16 | 5 | `clinical_metrics_gate` | 14 指标面板完整性、混淆矩阵一致性、临床下限验证 | `clinical_metrics_report.json` |
| 17 | 5 | `shap_interpretability_gate` | 多模型 SHAP 集成、Kendall tau 一致性、4 张发表级 CSV | `shap_interpretability_report.json` |
| 18 | 6 | `calibration_dca_gate` | ECE、斜率/截距、O:E 比、CITL、DCA 净效用、逐队列验证 | `calibration_dca_report.json` |
| 19 | 6 | `ci_matrix_gate` | 所有划分和外部队列的 Bootstrap CI 矩阵 | `ci_matrix_gate_report.json` |
| 20 | 6 | `distribution_generalization_gate` | 跨划分分布漂移、特征级 JSD、迁移准备度 | `distribution_generalization_report.json` |
| 21 | 6 | `evaluation_quality_gate` | CI 宽度 <= 0.20、重采样 >= 200、基线改善 >= 0.01 | `evaluation_quality_report.json` |
| 22 | 6 | `external_validation_gate` | 外部队列指标、迁移差距、每队列 >= 100 事件；**缺失时总分 cap 85、L3 阻断** | `external_validation_gate_report.json` |
| 23 | 6 | `fairness_equity_gate` | 均等化几率、差异影响比、亚组性能下限、HEAL FPR/FNR、**PPV 公平性、校准公平性、多重比较警告** | `fairness_equity_report.json` |
| 24 | 6 | `generalization_gap_gate` | 训练-验证-测试性能差距（PR-AUC、F2-beta、Brier） | `generalization_gap_report.json` |
| 25 | 6 | `metric_consistency_gate` | 请求与评估报告之间的指标值一致性 | `metric_consistency_report.json` |
| 26 | 6 | `permutation_significance_gate` | 置换零分布显著性检验 | `permutation_report.json` |
| 27 | 6 | `prediction_replay_gate` | 行级预测轨迹指标回放（容差 1e-6） | `prediction_replay_report.json` |
| 28 | 6 | `robustness_gate` | 时间片和患者亚组性能稳定性 | `robustness_gate_report.json` |
| 29 | 6 | `sample_size_gate` | EPV >= 10、收缩因子 >= 0.90、外部 >= 100 事件、CI 精度 | `sample_size_report.json` |
| 30 | 6 | `seed_stability_gate` | 多种子方差（PR-AUC std <= 0.03，strict >= 5 seeds） | `seed_stability_report.json` |
| 31 | 7 | `publication_gate` | 聚合 L1/L2/L3 合规、指纹基线对比、质量评分 | `publication_gate_report.json` |
| 32 | 8 | `self_critique_gate` | 12 维质量评分 + 可操作建议 | `self_critique_report.json` |
| 33 | 8 | `security_audit_gate` | HMAC 模型签名、证据完整性、依赖真实性、敏感数据扫描 | `security_audit_report.json` |

</details>

---

## 12 维量化评分

每个维度独立评分，加权求和得出总分 (0-100)：

| # | 维度 | 权重 | 评估内容 |
|:--|:----------|:------:|:-----------------|
| 1 | 数据完整性 | 12 | 划分隔离、患者不重叠、时序正确性、行无重复 |
| 2 | 防泄漏 | 15 | 目标泄漏、定义变量、索引后特征、特征名模式 |
| 3 | 流水线隔离 | 12 | 训练集独占预处理、插补器/缩放器/重采样范围强制 |
| 4 | 模型选择严谨性 | 10 | 候选池多样性、one-SE 规则、测试集隔离、基线比较 |
| 5 | 统计有效性 | 12 | Bootstrap CI、置换检验、校准三件套、DCA、指标一致性 |
| 6 | 泛化证据 | 10 | 训练-测试差距、外部队列、迁移 CI、种子稳定性 |
| 7 | 临床完整性 | 7 | 完整 14 指标面板（MCC、LR+/LR-）、混淆矩阵、阈值可行性 |
| 8 | 报告标准 | 7 | TRIPOD+AI 2024、PROBAST+AI 2025、排除标准、局限性 |
| 9 | 可重复性 | 6 | 种子锁定、版本追踪、执行证明、指纹锁定 |
| 10 | 安全与溯源 | 3 | HMAC-SHA256 签名、AES-256-GCM、审计链、受限反序列化 |
| 11 | 公平性 | 3 | 亚组分析、均等化几率、差异影响比、HEAL FPR/FNR |
| 12 | 样本量 | 3 | EPV 标准、Riley 三准则、收缩因子、有效样本量 |

  **评分解读**：

| 分数范围 | 等级 | 含义 |
|:------|:------|:--------|
| >=90 | L3 | 顶刊水准（Nature Medicine、Lancet、JAMA、BMJ） |
| 75-89 | L2 | 需要补充（专业期刊） |
| 60-74 | L1 | 重大缺陷（仅限会议论文） |
| < 60 | — | 不可发表 |

---

## 33 条方法论规则

<details>
<summary><strong>完整规则表（点击展开）</strong></summary>

| ID | 严重度 | 规则 | 文献来源 |
|:---|:---------|:-----|:-----------|
| **C01** | CRITICAL | 定义合格队列——排除结局结构性不可能的记录 | TRIPOD+AI 2024 Item 4a |
| **S01** | CRITICAL | 按患者 ID 划分——同一患者不跨 split | Steyerberg 2019 Ch.5 |
| **S02** | CRITICAL | 测试集时间必须晚于训练集 | Futoma 2020 (Lancet DH) |
| **P01** | CRITICAL | 预处理器仅在训练集上 fit | Kaufman 2012 (ACM TKDD) |
| **P02** | CRITICAL | SMOTE 仅在训练集；慎用：损害校准 | van den Goorbergh 2022 (JAMIA) |
| **P03** | CRITICAL | 划分前禁止全局清洗 | |
| **P04** | CRITICAL | 插补统计量仅来自训练集 | |
| **P05** | CRITICAL | 名义 -> OneHotEncoder；有序 -> OrdinalEncoder（需验证单调性） | 实测 AUROC +0.02 |
| **P06** | WARNING | 缺失按机制分层，不用固定丢弃阈值 | Madley-Dowd 2019 |
| **F01** | CRITICAL | 禁止目标变量作为特征 | |
| **F02** | CRITICAL | 禁止未来信息作为特征 | |
| **F03** | CRITICAL | 特征选择仅在训练集 | |
| **F04** | WARNING | 单因素筛选已废弃——用 Elastic Net 或 Ridge | Heinze 2018 |
| **F05** | CRITICAL | 定义预测时间点；分类所有特征的时间归属 | TRIPOD+AI Item 4b |
| **F06** | WARNING | Elastic Net 分组选择 + 稳定性选择 + Ridge 对照 | Zou 2005, Meinshausen 2010 |
| **M01** | CRITICAL | 禁止在测试集上调参 | |
| **M02** | CRITICAL | 阈值在验证集上选择 | |
| **M03** | WARNING | 比较 >= 3 个模型族 | TRIPOD+AI Item 7b |
| **M04** | CRITICAL | 模型选择用验证集性能，不用 train-test gap | Yang 2023 (KDD) |
| **E01** | CRITICAL | 所有主要指标需 95% CI（bootstrap >= 1000） | Efron 1993 |
| **E02** | CRITICAL | 完整 14 指标面板：区分度 + 分类（含 MCC、LR+/LR-）+ 校准 + DCA | Van Calster 2019, Chicco 2020 |
| **E03** | WARNING | 校准 ECE < 0.06 | |
| **E04** | WARNING | Train-test gap 仅作诊断，不作选择标准 | Steyerberg 2019 |
| **E05** | WARNING | class_weight="balanced" 需事后校准 | Platt 2000 |
| **E06** | WARNING | Bootstrap optimism correction（>= 100 次重采样） | Steyerberg 2019 Ch.17 |
| **Z01** | WARNING | 样本量：EPV >= 10（简化）；严格用 Riley 2019 | Peduzzi 1996, Riley 2019 |
| **R01** | INFO | 设置 random_state 保证可复现 | |
| **R02** | WARNING | 多种子稳定性（>= 5 seeds，std < 0.03） | Riley 2023 (Biom J) |
| **T01** | WARNING | TRIPOD+AI 2024 合规 | Collins 2024 (BMJ) |
| **Q01** | WARNING | 亚组分析（性别/年龄/种族） | TRIPOD+AI Item 16b |
| **Q02** | WARNING | 亚组指标需 Bootstrap CI；n < 200 标为不可靠 | Steyerberg 2019 Ch.25 |

</details>

---

## 23 个模型族

| 模型族 | 别名 | 类型 | 说明 |
|:-------|:------|:-----|:------|
| `logistic_l1` | `lr_l1` | Logistic Regression | L1 惩罚（稀疏） |
| `logistic_l2` | `lr_l2` | Logistic Regression | L2 惩罚（Ridge） |
| `logistic_elasticnet` | `lr_en` | Logistic Regression | L1+L2 混合 |
| `random_forest_balanced` | `rf` | Random Forest | 平衡类别权重 |
| `extra_trees_balanced` | `extra_trees` | Extra Trees | 平衡类别权重 |
| `hist_gradient_boosting_l2` | `hgb` | Gradient Boosting | sklearn 直方图梯度提升 |
| `adaboost` | &mdash; | AdaBoost | 二分类 |
| `xgboost` | `xgb` | XGBoost | 需安装 xgboost |
| `catboost` | &mdash; | CatBoost | 需安装 catboost |
| `lightgbm` | `lgbm` | LightGBM | 需安装 lightgbm |
| `svm_linear` | `svm_lin` | SVM | 线性核 |
| `svm_rbf` | `svm` | SVM | RBF 核 |
| `knn` | &mdash; | K-Nearest Neighbors | 基于距离 |
| `gaussian_nb` | &mdash; | Naive Bayes | 高斯假设 |
| `mlp` | &mdash; | MLP | 神经网络 |
| `tabpfn` | &mdash; | TabPFN | 基础模型 |
| `decision_tree` | `dt` | Decision Tree | 单树基线 |
| `soft_voting` | `voting` | Soft Voting Ensemble | Top-K 集成 |
| `weighted_voting` | &mdash; | Weighted Voting | 性能加权 |
| `stacking` | `stack` | Stacking | 元学习器集成 |

复杂度排名： Gaussian NB (1) < LR (2-4) < DT (5) < KNN (6) < SVM (7-8) < RF/Trees (9-10) < Boosting (11-14) < MLP (15) < TabPFN (17) < Ensemble (15000+).

---

## 16 个医学数据集

<details>
<summary><strong>大型数据集（>10K 行）</strong></summary>

```bash
python3 examples/download_real_data.py diabetes130_full   # UCI 101K readmission
python3 examples/download_real_data.py sepsis_survival    # UCI 129K sepsis survival
python3 examples/download_real_data.py rhc                # Vanderbilt 5.7K ICU mortality
python3 examples/download_cdc_data.py brfss               # CDC BRFSS 100K diabetes
python3 examples/download_cdc_data.py nhis                # CDC NHIS 28K diabetes
python3 examples/download_cdc_data.py covid               # CDC COVID-19 100K hospitalization
python3 examples/download_nhanes.py --cycles both         # CDC NHANES 16K diabetes
python3 examples/download_nci_gdc.py                      # NCI/NIH 25K cancer survival
```

</details>

<details>
<summary><strong>小型 UCI 数据集</strong></summary>

```bash
python3 examples/download_real_data.py heart    # 297 rows
python3 examples/download_real_data.py breast   # 569 rows
python3 examples/download_real_data.py pima     # 768 rows
```

</details>

<details>
<summary><strong>预置数据集</strong></summary>

- `chronic_kidney_disease.csv` &mdash; UCI CKD (400 rows)
- `support2.csv` &mdash; Vanderbilt SUPPORT2 ICU prognosis (9K rows)
- `diabetes_130_readmission.csv` &mdash; UCI diabetes readmission (compact)
- `covid19_hospitalization.csv` &mdash; COVID-19 hospitalization prediction

</details>

所有数据来自官方机构（CDC / UCI / NCI-NIH / Vanderbilt），无需注册，一键下载。总计 630K 行。

---

## 28 条静态分析规则 (R001-R028)

| 类别 | 规则 | 严重度 |
|:---------|:------|:---------|
|   **数据泄漏** | R001 fit-before-split, R002 scaler-on-test, R003 SMOTE-on-test, R005 threshold-on-test, R006 feature-selection-full, R007 target-as-feature, R017 early-stop-on-test, R020 global-clean-before-split | ERROR |
|   **划分问题** | R004 split-without-group, R008 temporal-shuffle, R015 small-test-set | WARNING |
|   **交叉验证** | R011 CV-internal-SMOTE, R012 accuracy-on-imbalanced | ERROR/WARNING |
|   **评估误用** | R010 train-metric-as-final, R013 hardcoded-threshold | WARNING |
|   **预处理** | R014 LabelEncoder-on-features, R018 scaling-before-trees | WARNING/INFO |
|   **可复现性** | R016 no-random-state | INFO |
|   **统计严谨性** | R009 no-CI, R019 multiple-comparison | INFO |
|   **模态守卫** | R028 omics-feature-prefix（拒绝 `gene_/probe_/snp_/cpg_/rs#/ENSG` 特征，指向 Scanpy/TCGAbiolinks/PLINK） | ERROR |

```bash
# 对任何 Python 项目运行静态分析
python3 -m mlgg_lint /path/to/code/
```

---

## 21 项分析工具

| 工具 | 函数 | 审稿人常问 | 文献 |
|:-----|:---------|:-----------------|:-----------|
| Riley 样本量 | `riley_sample_size()` | "样本量论证？" | Riley 2019 |
| 校准三件套 | `calibration_metrics()` | "校准斜率/截距？" | Van Calster 2019 |
| 校准分 bin CI | `calibration_bin_ci()` | "校准曲线有 CI 吗？" | NC Reviewer #2 |
| NRI / IDI | `compute_nri_idi()` | "比基线模型好多少？" | Pencina 2008 |
| 学习曲线 | `learning_curve_data()` | "数据量够吗？" | Figueroa 2012 |
| VIF 共线性 | `compute_vif()` | "特征间共线性？" | PMC4888898 |
| 非线性检验 | `check_nonlinearity()` | "线性假设合理吗？" | Harrell 2015 |
| 系数导出 | `export_model_coefficients()` | "模型系数是什么？" | NC Reviewer #1 |
| MNAR 敏感性 | `mnar_sensitivity_analysis()` | "MAR 假设如果错了？" | PMC10481859 |
| 时序漂移 | `temporal_drift_analysis()` | "模型部署后还准吗？" | PMC8627243 |
| 模型卡片 | `generate_model_card()` | "结构化模型文档？" | Mitchell M et al. FAT* 2019 |
| 插补敏感性 | `imputation_sensitivity()` | "换插补方法结论变吗？" | Madley-Dowd et al. J Clin Epidemiol 2019 |
| 亚组 DCA | `subgroup_dca()` | "少数族裔有临床效用吗？" | Vickers 2006 + PROBAST+AI 2025 |
| 基线对比 | `baseline_comparisons()` | "比随机/患病率好多少？" | NC ML Checklist |
| 特征消融 | `feature_ablation()` | "去掉关键特征性能怎么变？" | NC ML Checklist |
| 计算资源 | `compute_resource_report()` | "训练用了多少资源？" | NC ML Checklist |
| Rubin 规则 | `rubins_rules_combine()` | "多重插补怎么合并？" | Rubin 1987 |
| 鲁棒性压力测试 | `robustness_stress_test()` | "对异常值/噪声稳定吗？" | Original |
| Bootstrap Optimism | `bootstrap_optimism_correction()` | "内部验证的乐观偏差？" | Steyerberg 2019 |
| PDP 边际效应 | `_compute_pdp_ice()` | "特征对预测的边际影响？" | Friedman 2001 |
| FDR-BH 多重校正 | `fdr_bh_correction()` | "多次比较是否校正？" | Benjamini-Hochberg 1995 |

100% 覆盖 [Nature Portfolio ML Checklist V1.1](https://www.nature.com/documents/machine-learning-checklist.pdf) (30 items).

---

## NHANES Codebook RAG 系统

公共数据集（NHANES、BRFSS 等）的变量定义、skip pattern、编码规则常被误解，导致静默的数据泄漏。MLGG 内置三层 RAG 检索自动拦截：

| 层 | 机制 | 覆盖 |
|---|------|------|
| Layer 1 | **手动 Codebook Registry** — 人工标注的变量元数据（类型、gated missingness、测量协议、反向因果） | 21 个 NHANES 变量 |
| Layer 2 | **RAG 自动检索** — BM25 + trigram 混合检索 Harvard CCB-HMS 58K 变量库 + skip-chain 图 | 3,964 变量/cycle |
| Layer 3 | **Disease-KB x Codebook** — 从疾病定义知识库提取排除术语，映射到 NHANES codes | 自动标记 definition variable |

**Onboarding 自动触发**：`mlgg onboarding --input-csv nhanes_diabetes.csv` 自动检测 dataset/disease/cross-sectional，训练前运行 codebook RAG + definition_variable_guard + leakage_gate。

**外部验证对齐检查**：`external_validation_gate` 自动检测 degenerate prediction（全阴性/全阳性）、prevalence shift、常数特征，防止无意义的外部验证。缺失特征使用训练集中位数填充。

详见 `references/codebooks/dataset-codebook-registry.json` 和 `scripts/codebooks/nhanes_codebook_lookup.py`。

---

## 安全加固层

| 组件 | 实现 | 状态 |
|:----------|:--------------|:-------|
| 模型签名 | HMAC-SHA256 时间安全 `hmac.compare_digest()` | fail-closed |
| 证据加密 | AES-256-GCM（无降级——需 cryptography 包）| fail-closed |
| 审计链 | 仅追加 JSONL + 链式 HMAC 哈希，每条 fsync | 防篡改 |
| 反序列化 | RestrictedUnpickler 模块白名单 + 可调用黑名单 | 沙箱化 |
| 路径穿越 | safe_path() 符号链接解析 + 禁止前缀检查 + 沙箱强制 | 已防御 |
| 执行证明 | OpenSSL 分离签名 **+ `trusted_signers.json` 指纹白名单（外部信任锚）+ 新鲜度窗口（默认 7 天）+ bundle 路径沙箱** + 见证人仲裁（最少 2）+ 密钥轮换（180 天）| fail-closed，自认证+重放+逃逸均阻断 |
| 敏感数据 | 18 模式扫描（API 密钥、PEM 块、PHI 字段、SSN、信用卡）| 自动检测 |
| 密钥保护 | .mlgg_model_key chmod 0o600、.gitignore 保护、向上搜索 + 降级警告 | 加固 |

---

## 基准测试结果

5 个医学数据集的端到端基准（全部存入 `experiments/`）：

| 数据集 | 行数 | 特征 | Prevalence | ROC-AUC | PR-AUC | 校准 (slope) | 关键发现 |
|--------|------|------|-----------|---------|--------|-------------|---------|
| CKD 慢性肾病 | 399 | 24 | 63% | 0.999 | 1.000 | 3.08 | 极小样本，诊断特征区分度极高 |
| RHC ICU 死亡率 | 5,735 | 54 | 65% | 0.750 | 0.834 | **0.977** | 校准最优，高 prevalence 队列 |
| SUPPORT2 重症 | 9,105 | 43 | 26% | 0.892 | 0.635 | 0.745 | 发现并排除 11 个泄漏/事后变量 |
| NHANES 糖尿病 | 15,549 | 12 | 18% | 0.810 | 0.443 | — | 横截面数据，无时序 |
| Sepsis 脓毒症 | 129,392 | 3 | 9% | 0.689 | 0.159 | 0.804 | 仅 3 特征，性能受限（正确反映） |

> 每个基准包含完整的 evidence 报告（33 gate 结果 + session_log）。通过 SUPPORT2 测试发现并修复了 6 个 pipeline bug（特征泄漏检测、分类变量保留、scoma 编码等）。

---

## 项目结构

```
medical-ml-governance-guard/
│
├── scripts/                              # ─── 核心代码 (106 files, ~83K LOC) ───
│   │                                      # LOC snapshot 2026-04-24; drifts per commit —
│   │                                      # treat as order-of-magnitude, run `wc -l` for exact.
│   │
│   ├── core/              (6 files, 7.0K LOC)   # 框架底座 — 所有 gate 共享的基础设施
│   │   ├── _gate_framework.py            #   531  报告信封 v2.0, GateIssue/Severity, CLI 契约 (exit 0/2)
│   │   ├── _gate_registry.py             #   820  33 gate DAG 拓扑排序 + 依赖解析 + 层级并行
│   │   ├── _gate_utils.py                #  2927  60+ 统计函数: calibration, VIF, NRI/IDI, DCA, bootstrap CI
│   │   ├── _audit_shared.py              #   238  12 维评分 + 代码反模式正则扫描
│   │   ├── _peer_review_retrieval.py     #   781  452 条审稿意见 BM25 检索 + tag 同义词扩展 + issue-code 加权重排
│   │   └── _security.py                  #  1725  HMAC 签名, AES-256-GCM 加密, 受限反序列化
│   │
│   ├── gates/             (33 files, 28K LOC)   # 33 道 fail-closed 门控 (每个独立 CLI)
│   │   │
│   │   │  ┌─ Layer 0: 入口验证 ─────────────────────────────────────────────┐
│   │   ├── request_contract_gate.py      #  3792  请求契约验证 (所有 gate 的前置条件)
│   │   ├── cohort_definition_gate.py     #  1936  队列定义 + codebook RAG 验证
│   │   │  └──────────────────────────────────────────────────────────────────┘
│   │   │
│   │   │  ┌─ Layer 1: 数据完整性 ───────────────────────────────────────────┐
│   │   ├── leakage_gate.py               #   674  行/实体/时序泄漏检测
│   │   ├── split_protocol_gate.py        #   556  train-valid-test 划分协议审计
│   │   ├── manifest_lock.py              #   330  evidence 文件完整性锁定
│   │   │  └──────────────────────────────────────────────────────────────────┘
│   │   │
│   │   │  ┌─ Layer 2-3: 特征与模型审计 ────────────────────────────────────┐
│   │   ├── definition_variable_guard.py  #   453  定义变量泄漏防护 (HbA1c 定义糖尿病又作特征)
│   │   ├── feature_lineage_gate.py       #   533  特征血统追踪
│   │   ├── feature_engineering_audit_gate.py #  417  编码/缩放/工程审计 + 一次-hot 特征谱系映射
│   │   ├── tuning_leakage_gate.py        #   469  超参调优隔离验证
│   │   ├── model_selection_audit_gate.py  #   783  one-SE 规则 + 候选池充分性
│   │   ├── imbalance_policy_gate.py      #   650  SMOTE/加权规则审查
│   │   ├── missingness_policy_gate.py    #  1081  缺失值处理隔离 + MNAR 敏感性
│   │   │  └──────────────────────────────────────────────────────────────────┘
│   │   │
│   │   │  ┌─ Layer 4-5: 评估与校准 ────────────────────────────────────────┐
│   │   ├── evaluation_quality_gate.py    #   752  14 指标面板 + CI 方法验证
│   │   ├── calibration_dca_gate.py       #   798  ECE/O:E/CITL 校准 + 决策曲线分析
│   │   ├── ci_matrix_gate.py             #   820  95% CI 矩阵 (bootstrap percentile)
│   │   ├── clinical_metrics_gate.py      #   810  PPV/Sensitivity 临床阈值审查
│   │   ├── metric_consistency_gate.py    #   472  跨指标统计一致性
│   │   ├── permutation_significance_gate.py #  286  置换检验显著性
│   │   ├── sample_size_gate.py           #   552  EPV ≥ 10, Riley shrinkage ≥ 0.90
│   │   │  └──────────────────────────────────────────────────────────────────┘
│   │   │
│   │   │  ┌─ Layer 5-6: 泛化与公平性 ──────────────────────────────────────┐
│   │   ├── shap_interpretability_gate.py #  1450  多模型 SHAP + Spearman 排名一致性
│   │   ├── fairness_equity_gate.py       #   750  均等化赔率 + 差异影响比
│   │   ├── external_validation_gate.py   #   779  外部队列漂移检测
│   │   ├── distribution_generalization_gate.py # 814  协变量偏移 EODD/CMMD
│   │   ├── covariate_shift_gate.py       #   877  分布漂移统计检验
│   │   ├── generalization_gap_gate.py    #   276  训练-测试差距阈值
│   │   ├── robustness_gate.py            #   498  超参扰动 + 时序/分组鲁棒性
│   │   ├── seed_stability_gate.py        #   425  种子敏感性验证
│   │   ├── reporting_bias_gate.py        #   402  选择性报告偏倚
│   │   ├── prediction_replay_gate.py     #   537  预测可复现性验证
│   │   │  └──────────────────────────────────────────────────────────────────┘
│   │   │
│   │   │  ┌─ Layer 7-8: 终极聚合 ──────────────────────────────────────────┐
│   │   ├── execution_attestation_gate.py #  3405  执行证明签名验证
│   │   ├── publication_gate.py           #   616  TRIPOD+AI 2024 / PROBAST+AI 2025 合规
│   │   ├── security_audit_gate.py        #   388  代码安全审计 (AST 扫描)
│   │   └── self_critique_gate.py         #   458  LLM 自我审查
│   │      └──────────────────────────────────────────────────────────────────┘
│   │
│   ├── training/          (7 files, 11.9K LOC)  # 模型训练与数据准备
│   │   ├── train_select_evaluate.py      #  8610  训练引擎: 5 模型族, CV, one-SE 选择, 14 指标评估
│   │   │                                 #        LR(L1/L2/EN) + RandomForest + HistGradientBoosting
│   │   │                                 #        产出: evaluation_report, model_selection_report,
│   │   │                                 #              prediction_trace, ci_matrix, robustness, seed_sensitivity
│   │   ├── split_data.py                 #  1129  患者级安全划分: grouped_temporal / stratified_grouped
│   │   │                                 #        保证同一患者不跨 split, 时序不穿越
│   │   ├── init_project.py               #   290  项目脚手架: 创建 configs/ + data/ + evidence/ + keys/
│   │   ├── schema_preflight.py           #   447  CSV 列名/类型/语义验证 + 自动映射建议
│   │   ├── generate_execution_attestation.py # 1188  HMAC 签名认证 + 时间戳 + 见证人多签
│   │   └── generate_demo_medical_dataset.py #  222  离线 demo 数据集生成器
│   │
│   ├── reporting/         (15 files, 6.2K LOC)  # 报告、审计与导出
│   │   ├── audit_metrics.py              #   387  [轻量入口] 零依赖指标审查 — 贴 Table 2 查漏
│   │   │                                 #        检查: 指标完整性 / 样本量 / 校准 / DCA / TRIPOD
│   │   ├── audit_external_project.py     #   681  10 维项目审计 (100 分制), 扫代码 + 跑 gate
│   │   ├── generate_audit_report.py      #  1260  TRIPOD+AI/PROBAST+AI 合规报告 + 文献引用
│   │   ├── generate_compliance_certificate.py # 668  3 级合规证书 (L1 泄漏审计 / L2 统计 / L3 发表级)
│   │   ├── render_user_summary.py        #   316  从 evidence/ 生成人类可读 Markdown 摘要
│   │   ├── export_latex.py               #   277  发表级 LaTeX 表格 (指标面板 + CI)
│   │   ├── export_review_prompt.py       #   346  导出审查提示词 (无需本地部署, 贴到任意 LLM)
│   │   ├── explain_gate.py               #   263  Gate 失败代码解释器 (failure code → 人话)
│   │   ├── remediation_plan.py           #   412  从 evidence/ 生成优先级修复计划
│   │   ├── compare_runs.py               #   262  两次运行对比 (指标 diff + gate 变化)
│   │   ├── evidence_comparator.py        #   265  evidence 文件级差异对比
│   │   ├── evidence_digest.py            #   252  evidence 目录紧凑摘要
│   │   ├── quick_summary.py              #   325  一条命令查看训练结果
│   │   ├── record_session.py             #   --   交互会话记录（用于后续审计回放）
│   │   └── report_health_check.py        #   235  evidence 完整性仪表盘
│   │
│   ├── codebooks/         (12 files, 7.0K LOC)  # 数据字典工具 (NHANES / UK Biobank)
│   │   ├── nhanes_codebook_lookup.py     #  1055  NHANES 60K 变量 FTS5 全文检索 + RAG 验证
│   │   ├── ukb_codebook_lookup.py        #  1286  UKB 12K 字段验证 + 时序泄漏检测 + 别名 + disease-KB join + --exclude-risk
│   │   ├── codebook_factory.py           #   105  统一工厂: NHANES/UKB/BRFSS → 同一接口
│   │   ├── build_nhanes_codebook_db.py   #   580  Harvard CCB-HMS TSV → SQLite (60K vars + 204K codes)
│   │   ├── build_ukb_codebook_db.py      #  1026  UKB Data Showcase → SQLite (12K 字段 + FTS5 + 533K encoding values)
│   │   ├── fetch_nhanes_2021_2023.py     #   288  CDC 2021-2023 新周期数据爬取
│   │   ├── fetch_ukb_showcase.py         #   215  UKB Schema 文件下载 (公开, 无需登录) + sha256 manifest
│   │   ├── verify_nhanes_codebook.py     #   263  SQLite vs CDC XPT 地面真值验证
│   │   ├── verify_ukb_codebook.py        #  1455  UKB 8 层验证: L1 sha / L2 49 HARD 不变式 / L2c 全 cell / L3 golden seeds / L3b disease-KB / content-facet hash / (L4 见下)
│   │   ├── verify_ukb_against_live.py    #   288  L4 对 UKB 官网 live 交叉核验 (11 .txt sha / 100+ 字段 title+cat / 5 encoding 行数 / 20 units)
│   │   ├── add_disease_kb_provenance.py  #   --   disease KB provenance 批量标注
│   │   └── _kb_provenance.py / __init__.py
│   │
│   ├── review/            (8 files, 4.4K LOC)   # 论文分析与审稿案例
│   │   ├── peer_review_lookup.py         #   133  119 篇 NC 论文 × 452 条审稿意见, 按 gate/tag 检索
│   │   ├── batch_journal_review.py       #   776  批量期刊审查 (多论文 × 多期刊标准)
│   │   ├── extract_paper_metadata.py     #  1236  PDF → 结构化 metadata.json (LLM 驱动)
│   │   ├── score_paper_metadata.py       #   620  metadata → 12 维评分 + Major/Minor/Questions + evidence-backing audit
│   │   ├── fetch_papers.py               #  1031  论文批量下载 + 去重 + 元数据提取
│   │   ├── backfill_peer_review_gates.py #   --   反填审稿意见到 gate × tag 索引
│   │   ├── add_robustness_permutation_gates.py # --   为现有审稿意见补 robustness / permutation 条目
│   │   └── correct_subgroup_overmatch.py #   --   修复审稿意见的亚组 over-match 问题
│   │
│   ├── diagnostics/       (15 files, 5.3K LOC)  # 环境诊断 + 文档一致性 + KB 卫生
│   │   ├── env_doctor.py                 #   169  依赖健康检查 (core + optional backends)
│   │   ├── init_guide.py                 #  1035  交互式项目方法学指南生成器
│   │   ├── mlgg_web.py                   #   701  Flask Web UI (legacy 本地向导)
│   │   ├── gate_coverage_matrix.py       #   229  Gate × 数据集适配矩阵
│   │   ├── gate_timeline.py              #   282  Gate 执行时间线可视化
│   │   ├── gate_applicability.py         #   131  Gate 适用场景匹配
│   │   ├── threshold_sensitivity.py      #   431  决策阈值敏感性分析
│   │   ├── visualize_results.py          #   304  训练结果可视化
│   │   ├── policy_generator.py           #   387  组织级治理策略模板生成
│   │   ├── check_docs_consistency.py     #   --   SKILL.md ↔ README ↔ reviewer.yaml 数字漂移检测 (pre-commit)
│   │   ├── check_readme_stats.py         #   --   README 中文/英文版数字 parity + 活体 KB freshness 对账
│   │   ├── disease_kb_review_check.py    #   --   disease-KB 字段临床审核 checklist 生成
│   │   ├── generate_disease_kb_review_sheets.py  #   --   按疾病批量生成审核表
│   │   ├── kb_hygiene_check.py           #   --   KB 字段 provenance / 引用 / 更新时间卫生检查
│   │   └── retrieval_eval_harness.py     #   --   peer-review 检索精度基准 (scenarios.json + baseline.json)
│   │
│   └── orchestration/     (10 files, 12.5K LOC) # 工作流编排 + CLI 入口
│       │
│       │  ┌─ 用户入口 ──────────────────────────────────────────────────────┐
│       ├── mlgg.py                       #   731  [主入口] 统一 CLI, 30+ 子命令路由
│       ├── mlgg_onboarding.py            #  2006  引导式工作流: CSV → split → train → attest → DAG
│       ├── mlgg_interactive.py           #  1919  交互式向导 (init/workflow/train/authority)
│       ├── mlgg_pixel.py                 #  5187  像素风终端 UI (TUI)
│       │  └──────────────────────────────────────────────────────────────────┘
│       │
│       │  ┌─ 执行引擎 ──────────────────────────────────────────────────────┐
│       ├── run_dag_pipeline.py           #  1224  DAG 执行: 拓扑排序, 断点续跑, 层级并行
│       ├── run_productized_workflow.py   #   379  生产流水线: doctor → preflight → DAG → summary
│       │  └──────────────────────────────────────────────────────────────────┘
│       │
│       │  ┌─ 辅助模块 ──────────────────────────────────────────────────────┐
│       ├── triage.py                     #   362  智能 gate 路由 (跳过不适用的 gate)
│       ├── semantic_audit.py             #   250  LLM 语义审查层 (规则 gate 之后)
│       ├── failure_diagnosis.py          #   142  Gate 失败时 LLM 修复建议
│       └── run_endurance_test.py         #   767  6 小时耐久性测试
│          └──────────────────────────────────────────────────────────────────┘
│
├── tests/                  (131)         # ─── 测试 (~35K lines) ───
│   ├── conftest.py                       #   统一 fixture (tmp_path, 路径注入, 共享数据)
│   ├── test_*_gate.py      (32)          #   每个 gate 对应一个测试文件
│   ├── test_*_e2e.py       (7)           #   端到端流程测试 (onboarding, workflow, train, split)
│   ├── test_stress_*.py    (5)           #   压力测试 (audit chain, pipeline, numeric, security)
│   ├── test_security*.py   (4)           #   安全 + 红队测试
│   └── SKILL_RED_TEAM.md                 #   红队攻击场景文档
│
├── references/                           # ─── 知识库 (8 个领域子目录) ───
│   ├── standards/          (6)           # 报告标准
│   │   ├── tripod-ai-official-checklist.json     # TRIPOD+AI 2024 (27 项机器可验证)
│   │   ├── probast-ai-signalling-questions.json  # PROBAST+AI 2025 (4 域偏倚评估)
│   │   ├── stard-ai-checklist.json               # STARD+AI 诊断准确性
│   │   └── journal-rigor-standards.json          # 5 大期刊审稿标准
│   │
│   ├── methodology/        (5)           # 方法学知识
│   │   ├── disease-definition-knowledge-base.json  # 11 种疾病定义 (ICD, 实验室, 药物, UKB 字段)
│   │   ├── leakage-taxonomy.md                     # Kapoor 八型泄漏分类
│   │   └── literature-knowledge-base.json          # 59 篇 IF>10 文献索引
│   │
│   ├── codebooks/                        # 数据字典
│   │   ├── nhanes/         (8+SQLite)    #   Harvard 58K 变量 + 202K codebook entries + BM25 索引
│   │   ├── ukb/            (12+SQLite)   #   UKB Data Showcase 11,821 字段 + 533,286 encoding values + 216 golden seeds + 106 aliases + 8 层验证 (source_manifest.json + ukb_golden_fields.yaml + KNOWN_GAPS.md)
│   │   └── dataset-codebook-registry.json  # 通用 registry (BRFSS/NHIS/MIMIC)
│   │
│   ├── case-studies/                     # 审稿案例知识库 ("别人审别人" → 结构化 KB)
│   │   ├── peer-review-kb.json           #   452 条结构化审稿意见 (按 gate/dimension/tag 索引)
│   │   ├── nature_communications/        #   119 篇 NC 论文审稿意见 PDF + parsed JSON
│   │   └── <journal>/<disease>/          #   5 期刊 × 10 疾病领域的论文分析
│   │
│   ├── templates/          (27)          # JSON 模板 (request, split, evaluation, attestation...)
│   ├── operations/         (13)          # 运行时 KB (error 诊断 107 条, 评分方法, gate 矩阵)
│   ├── protocols/          (16)          # Phase 1-9 规则 + 审计/盲审/采样协议
│   ├── attestation/        (3)           # HMAC 签名 onboarding 指南 + 可信签名人模板
│   ├── retrieval_eval/     (2)           # peer-review 检索基准 (baseline.json + scenarios.json)
│   └── docs/               (8)           # Architecture, API-Reference, Quickstart, Troubleshooting
│
├── plugin/                               # ─── 静态分析 Lint (独立子包) ───
│   ├── mlgg_lint/          (9+30 files)  # AST 级 28 条泄漏检测规则 (R001-R028)
│   │   └── rules/                        #   fit_before_split, smote_on_test, target_encoding_leak...
│   ├── tests/              (5+60 samples)# good/bad 样本 + CLI/engine 测试
│   ├── vscode/             (4)           # VS Code 扩展
│   └── pyproject.toml                    # 独立包配置 (pip install -e plugin/)
│
├── agents/                 (3)           # ─── 多 Agent 配置 ───
│   ├── extractor.yaml                    #   论文 → metadata.json (Sonnet/Gemini/GPT-4o)
│   ├── reviewer.yaml                     #   metadata → 12 维评审 (Sonnet/Gemini/GPT-4o)
│   └── README.md                         #   Agent 分工说明
│
├── examples/               (22)          # ─── 示例数据 + 项目模板 ───
│   ├── *.csv               (16)          #   16 个医学数据集 (630K+ 行, UCI/CDC/NHANES/NCI)
│   ├── download_*.py       (4)           #   数据下载器 (real_data, cdc, nhanes, nci_gdc)
│   ├── demo_diabetes130/                 #   完整 9 阶段参考实现
│   └── template/                         #   可复用项目脚手架 (cp -r 后填入数据)
│
├── papers/                               # ─── 论文审查库 ("我们审别人") ───
│   ├── README.md                         #   元数据评审方法学 + 12 维评分标准
│   ├── templates/                        #   paper_metadata_template.json
│   └── <journal>/<disease>/<author>/     #   PDF + metadata.json + audit_output/
│
├── experiments/                          # ─── 基准测试套件 ───
│   ├── authority-e2e/                    #   4 个 UCI 数据集对抗性验证 + 基准矩阵
│   ├── support2-benchmark/              #   SUPPORT2 重症预后 (9105 行, ROC-AUC 0.892)
│   ├── nhanes-benchmark/                #   NHANES 糖尿病 (15549 行, ROC-AUC 0.810)
│   ├── rhc-benchmark/                   #   RHC ICU 死亡率 (5735 行, ROC-AUC 0.750)
│   ├── ckd-benchmark/                   #   CKD 慢性肾病 (399 行, ROC-AUC 0.999)
│   └── sepsis-benchmark/                #   Sepsis 脓毒症 (129K 行, ROC-AUC 0.689)
│
├── .claude/                              # ─── Claude Code 配置 ───
│   ├── commands/mlgg.md                  #   /mlgg skill 定义 (9 阶段 state machine)
│   └── QUEUE_PROMPTS.md                  #   Prompt 模板库 (66KB, gate review/开发任务)
│
├── .github/workflows/      (5)          # ─── CI/CD ───
│   ├── ci-unit.yml                       #   快速单元测试 (2-5 min)
│   ├── ci-extended.yml                   #   扩展测试 (30-45 min)
│   ├── ci-full.yml                       #   完整测试 + 基准 (60+ min)
│   ├── ci-overnight.yml                  #   权威基准 + 压力测试 (overnight)
│   └── ci-security.yml                   #   安全审计 + 红队 + RBAC
│
└── ROOT FILES
    ├── CLAUDE.md                         #   Agent 操作协议 (审稿人角色 + 安全边界)
    ├── SKILL.md                          #   /mlgg 技能定义 (9 阶段方法学指南)
    ├── pyproject.toml                    #   包元数据 + 依赖声明
    ├── README.md / README_EN.md          #   项目文档 (中/英双语)
    ├── CONTRIBUTING.md                   #   开发规范
    ├── CHANGELOG.md                      #   版本历史
    └── LICENSE                           #   PolyForm Noncommercial 1.0.0
```

### 数据流

```
用户 CSV ──→ /mlgg (orchestration/)
              │
              ├─ Phase 1: cohort_definition_gate ←── codebooks/ (变量语义验证)
              ├─ Phase 2: training/split_data.py + split_protocol_gate
              ├─ Phase 3-4: leakage/feature gates ←── references/methodology/ (泄漏分类)
              ├─ Phase 5: training/train_select_evaluate.py + model gates
              ├─ Phase 6: calibration/evaluation gates ←── references/standards/ (TRIPOD+AI)
              ├─ Phase 7-8: SHAP/fairness gates
              └─ Phase 9: publication_gate + self_critique_gate
                            │
                            ├─ evidence/ (JSON 报告 + HMAC 审计链)
                            └─ references/case-studies/ (引用审稿意见)
```

### 两个产品 + 一套 28-子命令 CLI

| 入口 | 安装 | 用途 | 依赖 |
|------|------|------|------|
| **mlgg-lint** | `pip install mlgg-lint` | 扫描 Python 代码 data leakage（28 条 AST 规则，含 R028 组学守卫） | 零依赖 |
| **mlgg** | `pip install ml-governance-guard` | 28 个子命令 CLI（onboarding / workflow / audit / audit-metrics / fairness / sample-size / lint / ...），完整 33-gate pipeline | numpy/pandas/sklearn |

子命令全表见 `SKILL.md` §"Quick Dispatch"。`audit-metrics` 是 `mlgg` 子命令之一，不是独立包。

### 四条审查路径

| 路径 | 执行者 | 输入 | 输出 |
|------|--------|------|------|
| **A. 代码扫描** | `mlgg-lint check code.py` | Python 源码 (.py/.ipynb) | R001-R028 泄漏检测报告 |
| **B. 指标审查** | `mlgg audit-metrics --metrics '{}'` | 论文 Table 2 数字 | TRIPOD+AI 合规缺口报告 |
| **C. 全流程审查** | `mlgg onboarding --input-csv` | 用户数据 CSV（可选 `--cohort-spec` 声明 inclusion/exclusion cascade） | evidence/ 报告 + 33 gate 验证 + Table 1 (TRIPOD+AI 13a) |
| **D. 论文元数据评审** | API agents (`agents/`) | 论文 PDF（含 prompt-injection 防御：paper 文本作为 untrusted data 隔离） | 12 维评分 |

---

## 安装指南

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-governance-guard.git
cd medical-ml-governance-guard
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

# 可选：模型后端 + 类别不平衡（imbalanced-learn）+ 可视化
python3 -m pip install -r requirements-optional.txt

# 验证
python3 scripts/orchestration/mlgg.py doctor
```

  **环境要求**: Python 3.10+, numpy, pandas, scikit-learn, scipy, joblib.

  **可选**: xgboost, catboost, lightgbm, tabpfn, optuna, shap, flask, cryptography, imbalanced-learn.

### 开发者：本地 pre-commit 钩子（推荐）

同一套 CI 规则，本地 3 秒反馈，装好后每次 `git commit` 自动跑：

```bash
python3 -m pip install --user pre-commit
pre-commit install
```

配置在 `.pre-commit-config.yaml`，包含：
- `ruff` — 与 `ci-unit.yml` 相同 ruleset（E/F/W，排除 ML 代码常见 E501/E741 等）
- `mlgg-lint-selfcheck` — 用 28 条 AST 规则审查 `mlgg-lint` 自身源码（dog-fooding）
- `docs-consistency` — SKILL.md / README(_EN).md / agents/reviewer.yaml 变更时校验 12 维评分权重一致

---

## 命令参考

| 目标 | 命令 |
|:-----|:--------|
| 审计外部项目 | `python3 scripts/reporting/generate_audit_report.py --project-dir /path` |
| 交互式探索 | `python3 scripts/orchestration/mlgg.py play` |
| 引导式首跑 | `python3 scripts/orchestration/mlgg.py onboarding --project-root /tmp/demo --mode guided --yes` |
| 发布级判定 | `python3 scripts/orchestration/mlgg.py workflow --request <project>/configs/request.json --strict` |
| 环境检查 | `python3 scripts/orchestration/mlgg.py doctor` |
| 初始化项目 | `python3 scripts/orchestration/mlgg.py init --project-root /tmp/project` |
| 安全数据划分 | `python3 scripts/orchestration/mlgg.py split -- --input data.csv --patient-id-col id --target-col y` |
| 训练模型 | `python3 scripts/orchestration/mlgg.py train --interactive` |
| 静态 Lint | `python3 -m mlgg_lint /path/to/code/` |
| 下载数据集 | `python3 examples/download_real_data.py heart` |
| DAG 可视化 | `python3 scripts/orchestration/run_dag_pipeline.py --show-dag` |
| 导出审查提示词 | `python3 scripts/reporting/export_review_prompt.py` |
| 批量期刊审查 | `python3 scripts/orchestration/mlgg.py batch-review --manifest manifest.json` |

---

## 文献基础

<details>
<summary><strong>按阶段分类的完整文献表（点击展开）</strong></summary>

### 阶段一：样本量与队列

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| Riley triple criteria | Riley RD et al. *Stat Med.* 2019;38(7):1276-1296 | `riley_sample_size()` |
| Sample size tutorial | Riley RD et al. *BMJ.* 2020;368:m441 | 绑定准则报告 |
| EPV >= 10 (legacy) | Peduzzi P et al. *J Clin Epidemiol.* 1996;49(12):1373-1379 | 后备检查 |

### 阶段二：数据划分

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| Patient-level split | Steyerberg EW. *Clinical Prediction Models.* 2019 Ch.5 | MLGG-S01 |
| Temporal split | Futoma J et al. *Lancet Digit Health.* 2020;2(9):e489 | MLGG-S02 |

### 阶段三：预处理

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| Fit on train only | Kaufman S et al. *ACM TKDD.* 2012;6(4):1-21 | MLGG-P01/P03/P04 |
| Tiered missingness | Madley-Dowd P et al. *J Clin Epidemiol.* 2019;110:63-73 | MLGG-P06 |
| SMOTE harms calibration | van den Goorbergh RWM et al. *JAMIA.* 2022;29(9):1525-1534 | MLGG-P02 |

### 阶段四：特征筛选

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| Elastic Net | Zou H, Hastie T. *JRSS-B.* 2005;67(2):301-320 | alpha/C 联合 CV |
| Stability selection | Meinshausen N, Buhlmann P. *JRSS-B.* 2010;72(4):417-473 | 100 次子采样，阈值 0.6 |
| Group LASSO | Yuan M, Lin Y. *JRSS-B.* 2006;68(1):49-67 | OneHot 分组 |
| No univariate screening | Heinze G et al. *Biometrical J.* 2018;60(3):431-449 | MLGG-F04 |

### 阶段五：模型训练

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| Valid performance > gap | Yang Z et al. *KDD 2023* | MLGG-M04 |
| Optimism correction | Steyerberg EW. *Clinical Prediction Models.* 2019 Ch.17 | `bootstrap_optimism_correction()` |

### 阶段六：评估

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| Calibration triple | Van Calster B et al. *BMC Med.* 2019;17:230 | `calibration_metrics()` |
| MCC over F1 | Chicco D, Jurman G. *BMC Genomics.* 2020;21:6 | MLGG-E02 |
| LR+/LR- for clinical decisions | Deeks JJ, Altman DG. *BMJ.* 2004;329:168-169 | MLGG-E02 |
| DCA | Vickers AJ, Elkin EB. *Med Decis Making.* 2006;26(6):565-574 | `calibration_dca_gate` |
| NRI / IDI | Pencina MJ et al. *Stat Med.* 2008;27(2):157-172 | `compute_nri_idi()` |
| 5-domain evaluation | Van Calster B et al. *BMC Med.* 2019;17:230 + Steyerberg EW. *Clinical Prediction Models.* 2019 | 框架覆盖 |

### 阶段七：可解释性

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| SHAP theory | Lundberg SM, Lee SI. *NeurIPS 2017* | `shap_interpretability_gate` |
| TreeSHAP | Lundberg SM et al. *Nature MI.* 2020;2:56-67 | TreeExplainer |
| Proportional normalization | Ponce-Bobadilla AV et al. *CTS.* 2024;17(11):e70056 | L1 归一化 |
| Rashomon effect | Breiman L. *Stat Sci.* 2001;16(3):199-231 | Multi-model ensemble |

### 阶段九：报告与合规

| 方法论决策 | 文献来源 | MLGG 实现 |
|:---------|:----------|:-------------------|
| TRIPOD+AI 2024 | Collins GS et al. *BMJ.* 2024;385:e078378 | 27-item checklist |
| PROBAST+AI 2025 | Moons KGM et al. *BMJ.* 2025;388:e082505 | 4-domain ROB |
| Leakage taxonomy | Kapoor S, Narayanan A. *Patterns.* 2023;4(9):100804 | 33 门全覆盖 |

### 基础综述

| 文献 | 核心论点 |
|:----------|:-------------|
| Chekroud AM et al. *Science.* 2024;383:164-167 | "Illusory generalizability" &mdash; ML models accurate within training trial, random outside |
| Wynants L et al. *BMJ.* 2020;369:m1328 | COVID prediction models: 94% high ROB by PROBAST; systematic evidence of widespread bias |
| Collins GS, Dhiman P, Ma J, et al. *BMJ.* 2024;384:e074819 | Calibration-in-the-large, calibration slope, bootstrap internal validation; split-sample NOT recommended |

</details>

---

## Claude Code 集成

MLGG 提供 Claude Code slash command `/mlgg`。激活后 Claude 切换为 Nature Methods / JAMA 级别审稿人，引导用户完成 9 阶段工作流，实时检查方法学。

```bash
# In Claude Code terminal:
/mlgg
```

AI 会自动：
- 主动提问引导 9 个阶段
- 引用 119 篇同行评审论文（452 个结构化审稿意见）作为论据
- 自动检测代码中的常见泄漏模式
- 生成结构化审计报告和修复方案

---

## CI/CD

| 流水线 | 触发条件 | 范围 | 超时 |
|:---------|:--------|:------|:--------|
| **ci-unit** | Push / PR | 单元测试，Python 3.10-3.12 | 20 分钟 |
| **ci-security** | Push / PR | 安全测试、门控验证、知识库完整性、TRIPOD/PROBAST 检查 | 30 分钟 |
| **ci-full** | 每夜 (3am) | 完整入门演示、发布基准 | 360 分钟 |
| **ci-extended** | 每周 (周日 4am) | 扩展观测基准 | 480 分钟 |

---

## 许可证与引用

**PolyForm Noncommercial License 1.0.0** &mdash; See [LICENSE](./LICENSE).

### 学术引用（必须）

```bibtex
@software{mlgg2026,
  title   = {ML Governance Guard (MLGG): Publication-Grade Integrity Standard
             for Medical Prediction Models},
  author  = {Weng, Can},
  year    = {2026},
  version = {1.0},
  url     = {https://github.com/Furinaaa-Cancan/medical-ml-governance-guard},
  note    = {33 fail-closed audit gates, 9-phase workflow,
             TRIPOD+AI 2024 / PROBAST+AI 2025 compliant}
}
```

### 使用权限

| 用途 | 是否允许 | 条件 |
|:----|:-------:|:----------|
| 个人学习与研究 | 允许 | 无需授权 |
| **以下所有其他用途** | **需授权** | **请先联系作者** |
| 学术论文中使用 MLGG 方法论 | 需授权 | 联系作者获得书面许可 + 必须引用 |
| 教学/课堂/培训 | 需授权 | 联系作者 |
| 衍生项目（开源或闭源） | 需授权 | 联系作者 |
| 企业/机构内部使用 | 需授权 | 联系作者 |
| 商业用途 | **禁止** | 需单独商业授权 |
| 未授权的方法论复制 | **禁止** | 视为学术不端 |

**除个人学习与研究外，任何形式的使用均需事先获得作者书面授权。** 未经授权的使用（包括但不限于学术发表、教学引用、二次开发、机构部署）均违反本许可证。未引用的方法论复制视为学术不端，将向相关期刊编辑部举报。

联系方式：通过 [GitHub Issues](https://github.com/Furinaaa-Cancan/medical-ml-governance-guard/issues) 或作者主页联系。

---

<a name="english-version"></a>

## English Version

> **[Read the full English version here (README_EN.md)](./README_EN.md)**
