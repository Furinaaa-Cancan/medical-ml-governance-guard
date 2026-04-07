<p align="center">
  <br>
  <img src="https://img.shields.io/badge/MLGG-v1.0-FF6B35?style=for-the-badge&labelColor=1a1a2e" alt="MLGG v1.0">
  <br><br>
  <strong style="font-size: 2.5em;">ML Leakage Guard</strong>
  <br>
  <em>Publication-Grade Integrity Standard for Medical Prediction Models</em>
  <br><br>
  <a href="https://polyformproject.org/licenses/noncommercial/1.0.0/"><img src="https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/tests-3400%2B%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/gates-33%20fail--closed-critical" alt="Gates">
  <img src="https://img.shields.io/badge/datasets-14%20medical-purple" alt="Datasets">
  <img src="https://img.shields.io/badge/code-138K%20lines-informational" alt="Code">
  <a href="https://doi.org/10.1136/bmj-2023-078378"><img src="https://img.shields.io/badge/TRIPOD%2BAI-2024-blue" alt="TRIPOD+AI"></a>
  <a href="https://doi.org/10.1136/bmj-2024-082505"><img src="https://img.shields.io/badge/PROBAST%2BAI-2025-blue" alt="PROBAST+AI"></a>
</p>

---

<p align="center">
<strong>33 道 fail-closed 门控</strong> &middot; <strong>9 阶段工作流</strong> &middot; <strong>12 维量化评分</strong> &middot; <strong>3 级合规认证</strong>
<br>
<strong>20 个模型族</strong> &middot; <strong>14 个真实医学数据集 (526K 行)</strong> &middot; <strong>31 条方法论规则</strong>
<br><br>
<em>从原始数据到 TRIPOD+AI 合规发表的完整防泄漏管线。<br>每条规则来自实际踩坑，每个阈值有文献引用。</em>
</p>

---

## 目录

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
- [31 条方法论规则](#31-条方法论规则)
- [20 个模型族](#20-个模型族)
- [14 个医学数据集](#14-个医学数据集)
- [20 条静态分析规则 (R001-R020)](#20-条静态分析规则-r001-r020)
- [19 项分析工具](#19-项分析工具)
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

医学 ML 论文中数据泄漏的发生率远超预期。86% 已发表预测模型存在高偏倚风险 (Van Calster 2026, Annual Review of Statistics)。

| 常见错误 | 后果 | MLGG 阻止方式 |
|:---------|:-----|:-------------|
| 全数据上标准化后再划分 | 性能虚抬，审稿人看不出来 | Gate P01: Pipeline 隔离审计 |
| 死亡患者纳入再入院预测 | 结局结构性不可能，AUROC 被污染 | Gate C01: 队列定义审查 |
| 名义变量用 OrdinalEncoder | LR 系数失去临床意义 (实测 AUROC +0.02) | Gate P05: 强制 OneHot |
| 只报 AUROC 不报 MCC 和 LR+/LR- | AUROC 0.65 看起来可以，但 MCC 0.12 说明近乎随机 | Gate E02: 完整 14 指标面板 |
| 用 train-test gap 选模型 | 无文献支撑，可能选到次优模型 | Gate M04: 验证集 PR-AUC + one-SE |
| 特征选择用全数据 | 信息从测试集泄漏到训练集 | Gate F03: 训练集独占约束 |
| HbA1c 既定义糖尿病又作为预测特征 | 完美泄漏，模型学到的是定义本身 | Gate C02: 定义列强制排除 |
| Bootstrap CI 用正态近似 | 小样本/非对称分布不可靠 | Gate E01: 强制 percentile bootstrap |

> **MLGG 不是又一个 ML 工具包。** 它是一套可机器验证的方法学标准——33 道 fail-closed 门控，任何一道不过就不能声称 publication-grade。

---

## 系统能力总览

```
原始数据 ──→ 9-Phase 工作流 ──→ 33 道门控审计 ──→ 合规证书 ──→ 可发表报告
```

| 模块 | 说明 | 规模 |
|:-----|:-----|:-----|
| **33 道安全门控** | fail-closed DAG 架构，覆盖泄漏/可解释性/公平性/校准/鲁棒性/TRIPOD+AI/PROBAST+AI | 9 层并行执行 |
| **12 维量化评分** | 数据完整性/泄漏防护/管线隔离/模型选择/统计有效性/泛化证据/临床完整性/报告标准/可复现性/安全性/公平性/样本量 | 0-100 分 |
| **3 级合规** | L1 (12 门, 泄漏审计) / L2 (25 门, 统计有效) / L3 (全部 33 门, 发布级) | 渐进认证 |
| **20 个模型族** | LR (L1/L2/ElasticNet) / SVM / RF / XGBoost / CatBoost / LightGBM / KNN / MLP / TabPFN + 集成 | 自动超参搜索 |
| **14 个真实数据集** | UCI / CDC / NCI / Vanderbilt 官方数据 | 总计 526K 行 |
| **多模型 SHAP 引擎** | 多族 L1 归一化集成 + Kendall tau 一致性 + 4 张发表级 CSV | RF/XGB/CatBoost/LGBM/LR |
| **学术合规引擎** | TRIPOD+AI 2024 (27 项) / PROBAST+AI 2025 (4 域) / STARD-AI | 58 条文献知识库 |
| **20 条 Lint 规则** | 静态分析检测代码级泄漏反模式 (R001-R020) | .py + .ipynb |
| **安全加固层** | HMAC-SHA256 / AES-256-GCM / 链式审计日志 / 路径穿越防护 / 受限反序列化 | fail-closed |
| **19 个分析工具** | Riley 样本量 / 校准三件套 / NRI-IDI / 学习曲线 / VIF / MNAR 敏感性 / 时序漂移 / ... | 100% 覆盖 Nature ML Checklist |

---

## 快速开始

### 方式一：Claude Code（推荐 — AI 审稿人全程引导）

```bash
# 1. Clone
git clone https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard.git
cd medical-ml-leakage-guard

# 2. Open Claude Code
claude

# 3. Just tell it what you want:
#    "Help me predict diabetes with this CSV"
#    "Review my code for data leakage"
#    "My model AUC is 0.85, what do I need for Nature Medicine?"
#
# Or type /mlgg to activate full methodology guidance mode.
# The AI will guide you through the 9-Phase workflow,
# check methodology errors in real-time, and cite
# 107 peer review papers as evidence.
```

### 方式二：命令行

```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-optional.txt  # XGBoost, CatBoost, LightGBM, SHAP, ...

# Verify installation
python3 scripts/orchestration/mlgg.py doctor

# Interactive pixel-art terminal UI (5-min full experience)
python3 scripts/orchestration/mlgg.py play

# Guided onboarding from scratch
python3 scripts/orchestration/mlgg.py onboarding \
  --project-root /tmp/mlgg_demo --mode guided --yes

# Audit any existing ML project (zero config)
python3 scripts/tools/generate_audit_report.py --project-dir /path/to/project

# Publication-grade strict pipeline
python3 scripts/orchestration/mlgg.py workflow \
  --request configs/request.json --strict
```

### 方式三：自有 CSV 最短严格闭环

```bash
# 1. Init project
python3 scripts/orchestration/mlgg.py init --project-root /tmp/project

# 2. Safe split
python3 scripts/orchestration/mlgg.py split -- \
  --input /path/to/data.csv \
  --output-dir /tmp/project/data \
  --patient-id-col patient_id --target-col y --time-col event_time \
  --strategy grouped_temporal

# 3. Interactive training
python3 scripts/orchestration/mlgg.py train --interactive

# 4. Strict audit (bootstrap baseline)
python3 scripts/orchestration/mlgg.py workflow \
  --request /tmp/project/configs/request.json \
  --strict --allow-missing-compare

# 5. Strict rerun with comparison
python3 scripts/orchestration/mlgg.py workflow \
  --request /tmp/project/configs/request.json \
  --strict \
  --compare-manifest /tmp/project/evidence/manifest_baseline.bootstrap.json
```

---

## 9 阶段工作流

MLGG 强制按 9 个阶段顺序执行，每个阶段有明确检查点，不通过不进入下一阶段。

```
  Phase 1            Phase 2            Phase 3            Phase 4
  Cohort      ────>  Splitting   ────>  Preprocessing ──>  Feature
  Definition         Protocol           Pipeline           Selection
  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐
  │ EPV      │       │ Patient │       │ Fit on  │       │ ElasticN│
  │ Riley    │       │ disjoint│       │ train   │       │ Stability│
  │ Missing  │       │ Temporal│       │ only    │       │ Ridge   │
  │ Types    │       │ order   │       │ OneHot  │       │ control │
  └────┬─────┘       └────┬────┘       └────┬────┘       └────┬────┘
       │                  │                  │                  │
       v                  v                  v                  v
  Phase 5            Phase 6            Phase 7            Phase 8
  Training    ────>  Evaluation  ────>  Interpret-  ────>  Fairness
  & Selection        & Calibration      ability            & Equity
  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐
  │ >=3 fam │       │ 14 metr │       │ Multi   │       │ EqOdds  │
  │ One-SE  │       │ Boot CI │       │ model   │       │ Disparate│
  │ Optimism│       │ DCA+NRI │       │ SHAP    │       │ Subgroup│
  │ LrnCurve│       │ Calibr  │       │ Kendall │       │ DCA     │
  └────┬─────┘       └────┬────┘       └────┬────┘       └────┬────┘
       │                  │                  │                  │
       └──────────────────┴────────┬─────────┴──────────────────┘
                                   v
                            Phase 9: Reporting
                            ┌─────────────────┐
                            │ TRIPOD+AI 2024  │
                            │ PROBAST+AI 2025 │
                            │ L1 / L2 / L3    │
                            │ 12-Dim Score    │
                            └─────────────────┘
```

---

### 阶段一：队列定义与样本量

> **Script**: `cohort_definition_gate.py` &nbsp;|&nbsp; **Layer**: 0 &nbsp;|&nbsp; **Rules**: C01, F05, Z01

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

> **Script**: `split_data.py` &nbsp;|&nbsp; **Gates**: `split_protocol_gate` + `leakage_gate` &nbsp;|&nbsp; **Rules**: S01, S02

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

> **Script**: `train_select_evaluate.py` Pipeline &nbsp;|&nbsp; **Rules**: P01-P06

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

#### 3.4 SMOTE 立场

van den Goorbergh 2022 (JAMIA) 证明 SMOTE 严重损害风险预测模型的概率校准。MLGG 默认不使用 SMOTE，改用 `class_weight="balanced"` + 事后 Platt scaling 校准。

---

### 阶段四：特征筛选

> **Script**: `train_select_evaluate.py` &nbsp;|&nbsp; **Rules**: F01-F06

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

> **Script**: `train_select_evaluate.py` &nbsp;|&nbsp; **Gate**: `model_selection_audit_gate` &nbsp;|&nbsp; **Rules**: M01-M04, R01

#### 5.1 候选模型族（MLGG-M03：>= 3）

MLGG 支持 20 个模型族 (详见 [20 Model Families](#20-model-families) 节)。推荐至少比较：
- **Logistic Regression** (L1/L2/ElasticNet) &mdash; 线性基线，系数可直接解释
- **Random Forest** &mdash; 非线性 + 交互，天然处理缺失
- **XGBoost / LightGBM** &mdash; 梯度提升，通常性能最优

每族定义超参数网格，通过 Optuna TPE sampler 或 Grid Search 在**验证集**上调优。

#### 5.2 模型选择标准（MLGG-M04, Yang KDD 2023）

**不使用 train-test gap 选模型。** Yang et al. 2023 证明验证集性能是更可靠的模型选择准则：

```
 WRONG:  Select model with smallest |AUC_train - AUC_test|
 MLGG:   Select model with highest validation PR-AUC (one-SE rule tiebreak)
```

**One-SE Rule**: 在最优性能的 1 个标准误范围内，选择复杂度最低的模型 (偏好 LR > RF > XGBoost)：

```python
best_se = best_std / sqrt(n_folds)
threshold = best_mean - best_se
eligible = [m for m in candidates if m.mean >= threshold]
selected = min(eligible, key=complexity_rank)
```

#### 5.3 阈值选择（MLGG-M02）

在**验证集**上通过 F-beta 最大化 + 临床约束确定最优分类阈值。阈值绝不在测试集上选择 (MLGG-M01 零容忍)。

默认临床约束：

| 临床指标 | 默认下限 | 含义 |
|:---------|:---------|:-----|
| Sensitivity | >= 0.70 | 漏诊率上限 |
| NPV | >= 0.70 | 阴性预测值下限 |
| Specificity | >= 0.60 | 误诊率上限 |
| PPV | >= 0.50 | 阳性预测值下限 |

#### 5.4 Bootstrap Optimism Correction（Steyerberg 2019 Ch.17）

内部验证方法，估计模型性能的"乐观偏差"：

```
For each of B bootstrap resamples (B >= 100):
    1. Fit model on bootstrap sample
    2. Score on bootstrap sample -> apparent_i
    3. Score on original training set -> test_i
    4. optimism_i = apparent_i - test_i

corrected = apparent_original - mean(optimism_i)
```

输出 `bootstrap_optimism_correction` 块：apparent / optimism / corrected (pr_auc, roc_auc, brier)。

#### 5.5 学习曲线（Figueroa 2012）

评估模型是否已"收敛" &mdash; 训练数据再增加是否还能提升性能：

- 在 {10%, 20%, 30%, 50%, 70%, 85%, 100%} 训练集比例上分别训练
- 收敛判定：最后 3 个点的相对标准差 < 2%
- 输出 `learning_curve` 块：每个点的 train_score / valid_score + converged flag

#### 5.6 定义列强制排除

`--definition-cols HbA1c,fasting_glucose` &mdash; 结局定义列被**强制排除**，不再是建议。防止最常见的医学 ML 泄漏：用于定义结局的变量混入预测特征。

---

### 阶段六：评估与校准

> **Script**: `train_select_evaluate.py` + 13 道统计门控 &nbsp;|&nbsp; **Rules**: E01-E06

#### 6.1 完整 14 指标面板（MLGG-E02）

测试集一次性使用，报告 5 域 14 项指标 (对标 Lancet Digital Health 2025 评估框架)：

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
| Permutation resamples | 300 | 置换检验 null distribution |
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

> **Gate**: `shap_interpretability_gate` &nbsp;|&nbsp; **Layer**: 5

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
| Kendall tau | 两个模型的特征重要性排名相关 | tau < 0.3 | tau < 0.5 |
| Top-N Jaccard | Top-10 特征集合重叠度 | &mdash; | Jaccard < 0.3 |
| Direction consistency | 所有模型 signed SHAP 同向? | &mdash; | `mixed` 方向 |
| Extreme concentration | 单特征 > 50% 总重要性 | &mdash; | WARNING |

#### 7.5 四张发表级 CSV 表格

| Table | File | Purpose | Columns |
|:------|:-----|:--------|:--------|
| **A** | `shap_table_a_ensemble_importance.csv` | Paper main table | Rank, Feature, Ensemble_Proportion, Direction, per-model Proportions |
| **B** | `shap_table_b_per_model_detail.csv` | Reviewer supplementary | Feature, per-model MeanAbsSHAP / Proportion / SignedSHAP / Rank |
| **C** | `shap_table_c_rank_agreement.csv` | Methodology evidence | Model_A, Model_B, Kendall_tau, P_Value, Top10_Overlap, Jaccard |
| **D** | `shap_table_d_case_explanations.csv` | Clinical narrative | Case_Index, Risk_Category, Y_True, Score, Top-3 driver features |

每张 CSV 首行为方法论注释 (`# Method: ...`)，可被 `pd.read_csv(comment="#")` 跳过。

---

### 阶段八：公平性与亚组分析

> **Gate**: `fairness_equity_gate` &nbsp;|&nbsp; **Rules**: Q01, Q02

#### 8.1 亚组分析（MLGG-Q01, TRIPOD+AI Item 16b）

按保护属性 (race, gender, age) 分组，每组独立计算：AUROC, PR-AUC, Sensitivity, Specificity, PPV, FPR, prevalence。

#### 8.2 公平性阈值

| 指标 | WARNING | FAIL | 定义 |
|:-----|:--------|:-----|:-----|
| Equalized odds gap (sensitivity) | > 0.10 | > 0.15 | 各亚组灵敏度的最大差距 |
| Disparate impact ratio (80% rule) | < 0.85 | < 0.80 | 少数群体/多数群体阳性预测率比 |
| Subgroup PR-AUC minimum | < 0.50 | < 0.40 | 任何亚组的最低性能 |
| FPR parity gap (HEAL) | > 0.10 | > 0.15 | 各亚组假阳性率的最大差距 |
| FNR parity gap (HEAL) | > 0.10 | > 0.15 | 各亚组假阴性率的最大差距 |

#### 8.3 小亚组处理（MLGG-Q02）

| 亚组大小 | 处理方式 |
|:---------|:---------|
| n < 20 | 不计算公平性指标 |
| n 20-50 | 计算但标记"不稳定" |
| n 50-200 | 计算，发出 WARNING |
| n >= 200 | 完全可靠 |

#### 8.4 不可能定理声明

当报告 >= 3 个公平性指标时，自动提示 Chouldechova 2017 / Kleinberg 2016 不可能定理：除基率相等或完美预测外，不可能同时满足所有公平性标准。

---

### 阶段九：报告与合规

> **Gates**: `publication_gate` + `self_critique_gate` + `security_audit_gate` &nbsp;|&nbsp; **Rule**: T01

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

| Level | Name | Gates | Applicable Scene | TRIPOD+AI | PROBAST ROB |
|:------|:-----|:------|:-----------------|:----------|:-----------|
| **L1** | Leakage Audit | 12 | Conference paper, preliminary report | &mdash; | &mdash; |
| **L2** | Statistically Valid | 25 | Professional journals (JAMIA, npj DM) | >= 17/27 | low/unclear |
| **L3** | Publication-Grade | **All 33** | Nature Medicine, Lancet, JAMA, BMJ | >= 23/27 | **low** |

**L1 Gates (12)**: request_contract, manifest, execution_attestation, leakage, split_protocol, covariate_shift, definition_guard, feature_lineage, imbalance, missingness, tuning, reporting_bias

**L2 adds (13)**: model_selection_audit, feature_engineering_audit, clinical_metrics, prediction_replay, generalization_gap, seed_stability, calibration_dca, ci_matrix, metric_consistency, evaluation_quality, permutation, sample_size, robustness

**L3 adds (8)**: distribution_generalization, external_validation, fairness_equity, cohort_definition, shap_interpretability, publication, self_critique, security_audit

#### 9.4 结构化局限性讨论

必须覆盖：数据来源局限、时间有效性、编码体系变化 (ICD-9 -> ICD-10)、外部效度、公平性局限、DCA 临床效用结论。如 DCA 显示无净效用，必须诚实报告 &mdash; 不隐瞒负面结果。

---

## 33 道安全门控 (Gate DAG)

33 道门控按有向无环图 (DAG) 分 9 层执行。同层可并行，全部通过才能声称 L3 Publication-Grade。

```
Layer 0  CONTRACT        cohort_definition  |  request_contract
   |
Layer 1  MANIFEST        manifest_lock
   |
Layer 2  ATTESTATION     execution_attestation
   |
Layer 3  DATA (4 ||)     leakage  |  split_protocol  |  covariate_shift  |  reporting_bias
   |
Layer 4  POLICY (5 ||)   definition_guard  |  feature_lineage  |  imbalance  |  missingness  |  tuning
   |
Layer 5  MODEL (4 ||)    model_selection_audit  |  feature_engineering  |  clinical_metrics  |  shap
   |
Layer 6  STATS (13 ||)   calibration_dca  |  ci_matrix  |  distribution  |  eval_quality
                          external_validation  |  fairness  |  gap  |  metric_consistency
                          permutation  |  prediction_replay  |  robustness  |  sample_size  |  seed
   |
Layer 7  AGGREGATION     publication_gate
   |
Layer 8  FINAL (2 ||)    self_critique  |  security_audit
```

<details>
<summary><strong>Full 33-Gate Detail Table (Click to expand)</strong></summary>

| # | Layer | Gate | What It Checks | Output Report |
|:--|:------|:-----|:---------------|:-------------|
| 1 | 0 | `cohort_definition_gate` | EPV adequacy, Riley triple criteria, data types, missingness, suspicious correlations | `cohort_definition_report.json` |
| 2 | 0 | `request_contract_gate` | Request JSON schema, file paths, anti-downgrade protection | `request_contract_report.json` |
| 3 | 1 | `manifest_lock` | SHA-256 fingerprint of all data/config/evaluation/gate scripts | `manifest.json` |
| 4 | 2 | `execution_attestation_gate` | Cryptographic signatures, timestamps, key assurance, witness quorum | `execution_attestation_report.json` |
| 5 | 3 | `leakage_gate` | Row-hash overlap, patient ID overlap, temporal boundary violation, 7-category feature name regex | `leakage_report.json` |
| 6 | 3 | `split_protocol_gate` | Patient-disjoint splits, temporal ordering, prevalence checks, minimum split sizes | `split_protocol_report.json` |
| 7 | 3 | `covariate_shift_gate` | Jensen-Shannon divergence per feature, prevalence drift, missingness drift | `covariate_shift_report.json` |
| 8 | 3 | `reporting_bias_gate` | TRIPOD+AI 2024 (17 items) + PROBAST+AI 2025 (6 domains) + STARD-AI checklists | `reporting_bias_report.json` |
| 9 | 4 | `definition_variable_guard` | Block outcome-definition variables (HbA1c, fasting_glucose) from features | `definition_guard_report.json` |
| 10 | 4 | `feature_lineage_gate` | Block post-index-time derived features from training | `lineage_report.json` |
| 11 | 4 | `imbalance_policy_gate` | Class imbalance strategy, train-only resampling, prevalence verification | `imbalance_policy_report.json` |
| 12 | 4 | `missingness_policy_gate` | Missing data strategy, MICE scale protection, imputer isolation | `missingness_policy_report.json` |
| 13 | 4 | `tuning_leakage_gate` | Hyperparameter tuning protocol, test set isolation, CV nesting | `tuning_leakage_report.json` |
| 14 | 5 | `model_selection_audit_gate` | One-SE rule replay, >= 3 candidates, logistic baseline, fingerprint verification | `model_selection_audit_report.json` |
| 15 | 5 | `feature_engineering_audit_gate` | Feature group provenance, train-only scope, stability evidence | `feature_engineering_audit_report.json` |
| 16 | 5 | `clinical_metrics_gate` | 14-metric panel completeness, confusion matrix consistency, clinical floor validation | `clinical_metrics_report.json` |
| 17 | 5 | `shap_interpretability_gate` | Multi-model SHAP ensemble, Kendall tau agreement, 4 publication CSV tables | `shap_interpretability_report.json` |
| 18 | 6 | `calibration_dca_gate` | ECE, slope/intercept, O:E ratio, CITL, DCA net benefit, per-cohort validation | `calibration_dca_report.json` |
| 19 | 6 | `ci_matrix_gate` | Bootstrap CI matrix across all splits and external cohorts | `ci_matrix_gate_report.json` |
| 20 | 6 | `distribution_generalization_gate` | Cross-split distribution shift, feature-level JSD, transport readiness | `distribution_generalization_report.json` |
| 21 | 6 | `evaluation_quality_gate` | CI width <= 0.20, resamples >= 200, baseline delta >= 0.01 | `evaluation_quality_report.json` |
| 22 | 6 | `external_validation_gate` | External cohort metrics, transport gap, >= 100 events per cohort | `external_validation_gate_report.json` |
| 23 | 6 | `fairness_equity_gate` | Equalized odds, disparate impact, subgroup performance floors, HEAL FPR/FNR | `fairness_equity_report.json` |
| 24 | 6 | `generalization_gap_gate` | Train-valid-test performance gaps (PR-AUC, F2-beta, Brier) | `generalization_gap_report.json` |
| 25 | 6 | `metric_consistency_gate` | Metric value consistency between request and evaluation report | `metric_consistency_report.json` |
| 26 | 6 | `permutation_significance_gate` | Permutation null distribution significance test | `permutation_report.json` |
| 27 | 6 | `prediction_replay_gate` | Row-level prediction trace metric replay (tolerance 1e-6) | `prediction_replay_report.json` |
| 28 | 6 | `robustness_gate` | Time-slice and patient subgroup performance stability | `robustness_gate_report.json` |
| 29 | 6 | `sample_size_gate` | EPV >= 10, shrinkage >= 0.90, external >= 100 events, CI precision | `sample_size_report.json` |
| 30 | 6 | `seed_stability_gate` | Multi-seed variance (PR-AUC std <= 0.03, >= 5 seeds strict) | `seed_stability_report.json` |
| 31 | 7 | `publication_gate` | Aggregate L1/L2/L3 compliance, manifest baseline comparison, quality score | `publication_gate_report.json` |
| 32 | 8 | `self_critique_gate` | 12-dimension quality score + actionable recommendations | `self_critique_report.json` |
| 33 | 8 | `security_audit_gate` | HMAC model signatures, evidence integrity, dependency authenticity, sensitive data scan | `security_audit_report.json` |

</details>

---

## 12 维量化评分

每个维度独立评分，加权求和得出总分 (0-100)：

| # | Dimension | Weight | What It Measures |
|:--|:----------|:------:|:-----------------|
| 1 | Data Integrity | 12 | Split isolation, patient non-overlap, temporal correctness, row deduplication |
| 2 | Leakage Prevention | 15 | Target leakage, definition variables, post-index features, feature name patterns |
| 3 | Pipeline Isolation | 12 | Train-only preprocessing, imputer/scaler/resampling scope enforcement |
| 4 | Model Selection Rigor | 10 | Candidate pool diversity, one-SE rule, test isolation, baseline comparison |
| 5 | Statistical Validity | 12 | Bootstrap CI, permutation tests, calibration triple, DCA, metric consistency |
| 6 | Generalization Evidence | 10 | Train-test gap, external cohorts, transport CI, seed stability |
| 7 | Clinical Completeness | 7 | Full 14-metric panel (MCC, LR+/LR-), confusion matrix, threshold feasibility |
| 8 | Reporting Standards | 7 | TRIPOD+AI 2024, PROBAST+AI 2025, exclusion criteria, limitations |
| 9 | Reproducibility | 6 | Seed locking, version tracking, execution attestation, manifest fingerprint |
| 10 | Security & Provenance | 3 | HMAC-SHA256 signing, AES-256-GCM, audit chain, restricted deserialization |
| 11 | Fairness & Equity | 3 | Subgroup analysis, equalized odds, disparate impact, HEAL FPR/FNR |
| 12 | Sample Size Adequacy | 3 | EPV criteria, Riley triple, shrinkage factor, effective sample size |

  **评分解读**：

| Range | Level | Meaning |
|:------|:------|:--------|
| >= 90 | L3 | Top-tier journal ready (Nature Medicine, Lancet, JAMA, BMJ) |
| 75-89 | L2 | Needs supplementation (professional journals) |
| 60-74 | L1 | Major defects (conference papers only) |
| < 60 | &mdash; | Unpublishable |

---

## 31 条方法论规则

<details>
<summary><strong>Complete Rule Table (Click to expand)</strong></summary>

| ID | Severity | Rule | Literature |
|:---|:---------|:-----|:-----------|
| **C01** | CRITICAL | Define eligible cohort &mdash; exclude records with structurally impossible outcomes | TRIPOD+AI 2024 Item 4a |
| **S01** | CRITICAL | Split by patient ID &mdash; same patient never across splits | Steyerberg 2019 Ch.5 |
| **S02** | CRITICAL | Test set time must be later than training set | Futoma 2020 (Lancet DH) |
| **P01** | CRITICAL | Preprocessors fit on train only | Kaufman 2012 (ACM TKDD) |
| **P02** | CRITICAL | SMOTE on train only; caution: harms calibration | van den Goorbergh 2022 (JAMIA) |
| **P03** | CRITICAL | No global cleaning before split | |
| **P04** | CRITICAL | Imputation statistics from train only | |
| **P05** | CRITICAL | Nominal -> OneHotEncoder; ordinal -> OrdinalEncoder (monotonicity verified) | AUROC +0.02 empirical |
| **P06** | WARNING | Missingness tiered by mechanism, not fixed threshold | Madley-Dowd 2019 |
| **F01** | CRITICAL | Target variable never as feature | |
| **F02** | CRITICAL | No future information in features | |
| **F03** | CRITICAL | Feature selection on train only | |
| **F04** | WARNING | Univariate screening deprecated &mdash; use Elastic Net or Ridge | Heinze 2018 |
| **F05** | CRITICAL | Define prediction time point; classify all features temporally | TRIPOD+AI Item 4b |
| **F06** | WARNING | Elastic Net grouped selection + Stability Selection + Ridge control | Zou 2005, Meinshausen 2010 |
| **M01** | CRITICAL | Never tune on test set | |
| **M02** | CRITICAL | Threshold selected on validation set | |
| **M03** | WARNING | Compare >= 3 model families | TRIPOD+AI Item 7b |
| **M04** | CRITICAL | Model selection by validation performance, not train-test gap | Yang 2023 (KDD) |
| **E01** | CRITICAL | All primary metrics need 95% CI (bootstrap >= 1000) | Efron 1993 |
| **E02** | CRITICAL | Full 14-metric panel: discrimination + classification (MCC, LR+/LR-) + calibration + DCA | Van Calster 2019, Chicco 2020 |
| **E03** | WARNING | Calibration ECE < 0.06 | |
| **E04** | WARNING | Train-test gap for diagnostics only, not selection | Steyerberg 2019 |
| **E05** | WARNING | class_weight="balanced" requires post-hoc calibration | Platt 2000 |
| **E06** | WARNING | Bootstrap optimism correction (>= 100 resamples) | Steyerberg 2019 Ch.17 |
| **Z01** | WARNING | Sample size: EPV >= 10 (simple); strict = Riley 2019 | Peduzzi 1996, Riley 2019 |
| **R01** | INFO | Set random_state for reproducibility | |
| **R02** | WARNING | Multi-seed stability (>= 5 seeds, std < 0.03) | Riley 2023 (Biom J) |
| **T01** | WARNING | TRIPOD+AI 2024 compliance | Collins 2024 (BMJ) |
| **Q01** | WARNING | Subgroup analysis (gender/age/race) | TRIPOD+AI Item 16b |
| **Q02** | WARNING | Subgroup metrics need Bootstrap CI; n < 200 flagged as unreliable | Steyerberg 2019 Ch.25 |

</details>

---

## 20 个模型族

| Family | Alias | Type | Notes |
|:-------|:------|:-----|:------|
| `logistic_l1` | `lr_l1` | Logistic Regression | L1 penalty (sparse) |
| `logistic_l2` | `lr_l2` | Logistic Regression | L2 penalty (Ridge) |
| `logistic_elasticnet` | `lr_en` | Logistic Regression | L1+L2 hybrid |
| `random_forest_balanced` | `rf` | Random Forest | Balanced class weight |
| `extra_trees_balanced` | `extra_trees` | Extra Trees | Balanced class weight |
| `hist_gradient_boosting_l2` | `hgb` | Gradient Boosting | sklearn HistGB |
| `adaboost` | &mdash; | AdaBoost | Binary classification |
| `xgboost` | `xgb` | XGBoost | Requires xgboost package |
| `catboost` | &mdash; | CatBoost | Requires catboost package |
| `lightgbm` | `lgbm` | LightGBM | Requires lightgbm package |
| `svm_linear` | `svm_lin` | SVM | Linear kernel |
| `svm_rbf` | `svm` | SVM | RBF kernel |
| `knn` | &mdash; | K-Nearest Neighbors | Distance-based |
| `gaussian_nb` | &mdash; | Naive Bayes | Gaussian assumption |
| `mlp` | &mdash; | MLP | Neural network |
| `tabpfn` | &mdash; | TabPFN | Foundation model |
| `decision_tree` | `dt` | Decision Tree | Single tree baseline |
| `soft_voting` | `voting` | Soft Voting Ensemble | Top-K ensemble |
| `weighted_voting` | &mdash; | Weighted Voting | Performance-weighted |
| `stacking` | `stack` | Stacking | Meta-learner ensemble |

Complexity ranking: Gaussian NB (1) < LR (2-4) < DT (5) < KNN (6) < SVM (7-8) < RF/Trees (9-10) < Boosting (11-14) < MLP (15) < TabPFN (17) < Ensemble (15000+).

---

## 14 个医学数据集

<details>
<summary><strong>Large Datasets (>10K rows)</strong></summary>

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
<summary><strong>Small UCI Datasets</strong></summary>

```bash
python3 examples/download_real_data.py heart    # 297 rows
python3 examples/download_real_data.py breast   # 569 rows
python3 examples/download_real_data.py pima     # 768 rows
```

</details>

<details>
<summary><strong>Pre-bundled Datasets</strong></summary>

- `chronic_kidney_disease.csv` &mdash; UCI CKD (400 rows)
- `support2.csv` &mdash; Vanderbilt SUPPORT2 ICU prognosis (9K rows)
- `diabetes_130_readmission.csv` &mdash; UCI diabetes readmission (compact)
- `covid19_hospitalization.csv` &mdash; COVID-19 hospitalization prediction

</details>

All data from official sources (CDC / UCI / NCI-NIH / Vanderbilt). No registration required. Total: 526K rows.

---

## 20 条静态分析规则 (R001-R020)

| Category | Rules | Severity |
|:---------|:------|:---------|
| **Data Leakage** | R001 fit-before-split, R002 scaler-on-test, R003 SMOTE-on-test, R005 threshold-on-test, R006 feature-selection-full, R007 target-as-feature, R017 early-stop-on-test, R020 global-clean-before-split | ERROR |
| **Split Issues** | R004 split-without-group, R008 temporal-shuffle, R015 small-test-set | WARNING |
| **Cross-Validation** | R011 CV-internal-SMOTE, R012 accuracy-on-imbalanced | ERROR/WARNING |
| **Evaluation Misuse** | R010 train-metric-as-final, R013 hardcoded-threshold | WARNING |
| **Preprocessing** | R014 LabelEncoder-on-features, R018 scaling-before-trees | WARNING/INFO |
| **Reproducibility** | R016 no-random-state | INFO |
| **Statistical Rigor** | R009 no-CI, R019 multiple-comparison | INFO |

```bash
# Run lint on any Python project
python3 -m mlgg_lint /path/to/code/
```

---

## 19 项分析工具

| Tool | Function | Reviewer Question | Literature |
|:-----|:---------|:-----------------|:-----------|
| Riley Sample Size | `riley_sample_size()` | "Sample size justification?" | Riley 2019 |
| Calibration Triple | `calibration_metrics()` | "Calibration slope/intercept?" | Van Calster 2019 |
| Calibration per-bin CI | `calibration_bin_ci()` | "Calibration curve with CI?" | NC Reviewer #2 |
| NRI / IDI | `compute_nri_idi()` | "How much better than baseline?" | Pencina 2008 |
| Learning Curve | `learning_curve_data()` | "Enough data?" | Figueroa 2012 |
| VIF Collinearity | `compute_vif()` | "Feature collinearity?" | PMC4888898 |
| Nonlinearity Test | `check_nonlinearity()` | "Linear assumption valid?" | Harrell 2015 |
| Coefficient Export | `export_model_coefficients()` | "Model coefficients?" | NC Reviewer #1 |
| MNAR Sensitivity | `mnar_sensitivity_analysis()` | "What if MAR is wrong?" | PMC10481859 |
| Temporal Drift | `temporal_drift_analysis()` | "Model stable after deployment?" | PMC8627243 |
| Model Card | `generate_model_card()` | "Structured model documentation?" | Mitchell 2019 |
| Imputation Sensitivity | `imputation_sensitivity()` | "Conclusions change with different imputation?" | Pop Health 2024 |
| Subgroup DCA | `subgroup_dca()` | "Clinical utility for minorities?" | Nature CS 2025 |
| Baseline Comparisons | `baseline_comparisons()` | "Better than random/prevalence?" | NC ML Checklist |
| Feature Ablation | `feature_ablation()` | "Remove key feature: what happens?" | NC ML Checklist |
| Compute Resources | `compute_resource_report()` | "Training resources used?" | NC ML Checklist |
| Rubin's Rules | `rubins_rules_combine()` | "Multiple imputation combination?" | Rubin 1987 |
| Robustness Stress Test | `robustness_stress_test()` | "Stable against outliers/noise?" | Original |
| Bootstrap Optimism | `bootstrap_optimism_correction()` | "Internal validation bias?" | Steyerberg 2019 |

100% coverage of [Nature Portfolio ML Checklist V1.1](https://www.nature.com/documents/machine-learning-checklist.pdf) (30 items).

---

## 安全加固层

| Component | Implementation | Status |
|:----------|:--------------|:-------|
| Model signing | HMAC-SHA256 with timing-safe `hmac.compare_digest()` | fail-closed |
| Evidence encryption | AES-256-GCM (no fallback &mdash; requires `cryptography` package) | fail-closed |
| Audit chain | Append-only JSONL with chained HMAC hashes, fsync per entry | tamper-evident |
| Deserialization | `RestrictedUnpickler` with module allowlist + callable blocklist | sandboxed |
| Path traversal | `safe_path()` with symlink resolve + forbidden prefix check + sandbox enforcement | defended |
| Attestation | OpenSSL detached signatures + witness quorum (min 2) + key rotation (180 days) | multi-sig |
| Sensitive data | 18-pattern scan (API keys, PEM blocks, PHI fields, SSN, credit card) | auto-detect |
| Key protection | `.mlgg_model_key` chmod 0o600, `.gitignore` protected, upward search with fallback warning | hardened |

---

## 项目结构

```
scripts/
  core/               Framework internals
    _gate_framework.py   Gate base class, report envelope, issue management
    _gate_utils.py       Shared numeric helpers, metric panel, calibration, audit chain
    _gate_registry.py    33-gate DAG with dependency graph and layer parallelism
    _security.py         HMAC, AES-256-GCM, restricted unpickler, path traversal defense
    _audit_shared.py     Audit report shared utilities
    _peer_review_retrieval.py   Peer review knowledge base retrieval
  gates/              33 fail-closed gate scripts
  orchestration/      CLI entrypoints and pipeline runners
    mlgg.py              Unified CLI (20+ subcommands)
    run_dag_pipeline.py  Parallel DAG executor with checkpoint/resume
    run_strict_pipeline.py  Sequential strict executor
    run_productized_workflow.py  doctor -> preflight -> strict -> summary
    mlgg_onboarding.py   Guided novice onboarding
    mlgg_interactive.py  Interactive wizard
    mlgg_pixel.py        Pixel-art terminal UI
  tools/              Reports, training, splitting, utilities
    train_select_evaluate.py  7000-line training engine (20 model families)
    split_data.py        Safe data splitting
    generate_audit_report.py  12-dimension audit report generator
    audit_external_project.py  External project auditor
    ...33 more tool scripts
tests/                4000+ pytest tests (85%+ coverage)
examples/             14 medical datasets + 9-phase template
experiments/          E2E benchmark suite (4 UCI datasets, adversarial checks)
references/           60+ JSON knowledge bases
  disease-definition-knowledge-base.json   Disease definitions (ICD, labs, meds)
  error-knowledge-base.json                99 error diagnosis entries
  literature-knowledge-base.json           58 literature citations
  tripod-ai-official-checklist.json        TRIPOD+AI 2024 machine-verifiable
  probast-ai-signalling-questions.json     PROBAST+AI 2025 4-domain assessment
  peer_reviews/peer-review-kb.json         107 papers, 375 structured concerns
plugin/               Static analysis lint (R001-R020, .py + .ipynb)
  mlgg_lint/rules/     20 rule implementations
  vscode/              VS Code extension
docs/                 Architecture documentation
.github/workflows/    CI/CD (unit / security / nightly full / weekly extended)
```

---

## 安装指南

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard.git
cd medical-ml-leakage-guard
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

# Optional model backends
python3 -m pip install -r requirements-optional.txt

# Verify
python3 scripts/orchestration/mlgg.py doctor
```

  **环境要求**: Python 3.10+, numpy, pandas, scikit-learn, scipy, joblib.

  **可选**: xgboost, catboost, lightgbm, tabpfn, optuna, shap, flask, cryptography.

---

## 命令参考

| Goal | Command |
|:-----|:--------|
| Audit external project | `python3 scripts/tools/generate_audit_report.py --project-dir /path` |
| Interactive exploration | `python3 scripts/orchestration/mlgg.py play` |
| Guided first run | `python3 scripts/orchestration/mlgg.py onboarding --project-root /tmp/demo --mode guided --yes` |
| Publication-grade verdict | `python3 scripts/orchestration/mlgg.py workflow --request <project>/configs/request.json --strict` |
| Environment check | `python3 scripts/orchestration/mlgg.py doctor` |
| Initialize project | `python3 scripts/orchestration/mlgg.py init --project-root /tmp/project` |
| Safe data split | `python3 scripts/orchestration/mlgg.py split -- --input data.csv --patient-id-col id --target-col y` |
| Train models | `python3 scripts/orchestration/mlgg.py train --interactive` |
| Static lint | `python3 -m mlgg_lint /path/to/code/` |
| Download dataset | `python3 examples/download_real_data.py heart` |
| DAG visualization | `python3 scripts/orchestration/run_dag_pipeline.py --show-dag` |
| Export review prompt | `python3 scripts/tools/export_review_prompt.py` |
| Batch journal review | `python3 scripts/orchestration/mlgg.py batch-review --manifest manifest.json` |

---

## 文献基础

<details>
<summary><strong>Complete Literature Table by Phase (Click to expand)</strong></summary>

### Phase 1: Sample Size & Cohort

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| Riley triple criteria | Riley RD et al. *Stat Med.* 2019;38(7):1276-1296 | `riley_sample_size()` |
| Sample size tutorial | Riley RD et al. *BMJ.* 2020;368:m441 | Binding criterion report |
| EPV >= 10 (legacy) | Peduzzi P et al. *J Clin Epidemiol.* 1996;49(12):1373-1379 | Backup check |

### Phase 2: Splitting

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| Patient-level split | Steyerberg EW. *Clinical Prediction Models.* 2019 Ch.5 | MLGG-S01 |
| Temporal split | Futoma J et al. *Lancet Digit Health.* 2020;2(9):e489 | MLGG-S02 |

### Phase 3: Preprocessing

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| Fit on train only | Kaufman S et al. *ACM TKDD.* 2012;6(4):1-21 | MLGG-P01/P03/P04 |
| Tiered missingness | Madley-Dowd P et al. *J Clin Epidemiol.* 2019;110:63-73 | MLGG-P06 |
| SMOTE harms calibration | van den Goorbergh RWM et al. *JAMIA.* 2022;29(9):1525-1534 | MLGG-P02 |

### Phase 4: Feature Selection

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| Elastic Net | Zou H, Hastie T. *JRSS-B.* 2005;67(2):301-320 | alpha/C joint CV |
| Stability selection | Meinshausen N, Buhlmann P. *JRSS-B.* 2010;72(4):417-473 | 100 subsamples, threshold 0.6 |
| Group LASSO | Yuan M, Lin Y. *JRSS-B.* 2006;68(1):49-67 | OneHot grouped |
| No univariate screening | Heinze G et al. *Biometrical J.* 2018;60(3):431-449 | MLGG-F04 |

### Phase 5: Training

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| Valid performance > gap | Yang Z et al. *KDD 2023* | MLGG-M04 |
| Optimism correction | Steyerberg EW. *Clinical Prediction Models.* 2019 Ch.17 | `bootstrap_optimism_correction()` |

### Phase 6: Evaluation

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| Calibration triple | Van Calster B et al. *BMC Med.* 2019;17:230 | `calibration_metrics()` |
| MCC over F1 | Chicco D, Jurman G. *BMC Genomics.* 2020;21:6 | MLGG-E02 |
| LR+/LR- for clinical decisions | Deeks JJ, Altman DG. *BMJ.* 2004;329:168-169 | MLGG-E02 |
| DCA | Vickers AJ, Elkin EB. *Med Decis Making.* 2006;26(6):565-574 | `calibration_dca_gate` |
| NRI / IDI | Pencina MJ et al. *Stat Med.* 2008;27(2):157-172 | `compute_nri_idi()` |
| 5-domain evaluation | Van Calster B et al. *Lancet Digit Health.* 2025 | Framework coverage |

### Phase 7: Interpretability

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| SHAP theory | Lundberg SM, Lee SI. *NeurIPS 2017* | `shap_interpretability_gate` |
| TreeSHAP | Lundberg SM et al. *Nature MI.* 2020;2:56-67 | TreeExplainer |
| Proportional normalization | Ponce-Bobadilla AV et al. *CTS.* 2024;17(11):e70056 | L1 normalization |
| Rashomon effect | Breiman L. *Stat Sci.* 2001;16(3):199-231 | Multi-model ensemble |

### Phase 9: Reporting

| Decision | Reference | MLGG Implementation |
|:---------|:----------|:-------------------|
| TRIPOD+AI 2024 | Collins GS et al. *BMJ.* 2024;385:e078378 | 27-item checklist |
| PROBAST+AI 2025 | Moons KGM et al. *BMJ.* 2025;388:e082505 | 4-domain ROB |
| Leakage taxonomy | Kapoor S, Narayanan A. *Patterns.* 2023;4(9):100804 | 33-gate coverage |

### Foundational Reviews

| Reference | Core Argument |
|:----------|:-------------|
| Chekroud AM et al. *Science.* 2024;383:164-167 | "Illusory generalizability" &mdash; ML models accurate within training trial, random outside |
| Van Calster B et al. *Ann Rev Stat.* 2026;13 | 12 "enemies" of reliable prediction models; 86% published models high ROB |
| Dhiman P et al. *J Clin Epidemiol.* 2025;179:111967 | Median peer review 243 words; <20% check generalizability; calibration rarely reviewed |

</details>

---

## Claude Code 集成

MLGG provides Claude Code slash command `/mlgg`. When activated, Claude operates as a Nature Methods / JAMA-level reviewer, guiding users through the 9-Phase workflow with real-time methodology checks.

```bash
# In Claude Code terminal:
/mlgg
```

The AI will:
- Guide through 9 phases with proactive questioning
- Cite 107 peer review papers (375 structured concerns) as evidence
- Auto-detect common leakage patterns in code
- Generate structured audit reports with remediation plans

---

## CI/CD

| Pipeline | Trigger | Scope | Timeout |
|:---------|:--------|:------|:--------|
| **ci-unit** | Push / PR | Unit tests, Python 3.10-3.12 | 20 min |
| **ci-security** | Push / PR | Security tests, gate validation, KB integrity, TRIPOD/PROBAST checks | 30 min |
| **ci-full** | Nightly (3am) | Full onboarding demo, release benchmarks | 360 min |
| **ci-extended** | Weekly (Sun 4am) | Extended observational benchmarks | 480 min |

---

## 许可证与引用

**PolyForm Noncommercial License 1.0.0** &mdash; See [LICENSE](./LICENSE).

### 学术引用（必须）

```bibtex
@software{mlgg2026,
  title   = {ML Leakage Guard (MLGG): Publication-Grade Integrity Standard
             for Medical Prediction Models},
  author  = {Weng, Can},
  year    = {2026},
  version = {1.0},
  url     = {https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard},
  note    = {33 fail-closed audit gates, 9-phase workflow,
             TRIPOD+AI 2024 / PROBAST+AI 2025 compliant}
}
```

### 使用权限

| Use | Allowed | Condition |
|:----|:-------:|:----------|
| Personal learning & research | Yes | No restriction |
| Academic paper using MLGG validation | Yes | **Must cite** |
| Classroom teaching | Yes | Credit source |
| Open-source noncommercial derivative | Yes | Same license + cite |
| Claude Code `/mlgg` Skill | Yes | Only authorized public channel |
| Commercial use | **No** | Requires separate commercial license |
| Uncited methodology reproduction | **No** | Academic misconduct |

Commercial use is **strictly prohibited**. Uncited reproduction of MLGG methodology constitutes academic misconduct and will be reported to journal editors.

---

<a name="english-version"></a>

## English Version

> This README is written in Chinese as the primary language. All code, commands, and file structures are language-neutral. Click any section link below to jump to the detailed Chinese documentation.

**ML Leakage Guard (MLGG)** is a publication-grade integrity standard for medical binary classification models, providing:

- **33 fail-closed audit gates** in a 9-layer DAG &mdash; covering data leakage, interpretability, fairness, calibration, robustness, TRIPOD+AI 2024, and PROBAST+AI 2025
- **9-phase guided workflow**: Cohort Definition -> Splitting -> Preprocessing -> Feature Selection -> Training -> Evaluation -> Interpretability -> Fairness -> Reporting
- **12-dimension quality scoring** (0-100) with weighted rubric
- **3 conformance levels**: L1 (12 gates, leakage audit) / L2 (25 gates, statistically valid) / L3 (all 33, publication-grade)
- **20 model families** with automatic hyperparameter tuning
- **14 real medical datasets** (526K rows) from CDC / UCI / NCI / Vanderbilt
- **Multi-model SHAP engine** with L1-normalized ensemble and Kendall tau agreement
- **Security layer**: HMAC-SHA256 / AES-256-GCM / tamper-evident audit chain
- **30+ peer-reviewed references** grounding every methodology decision

### Section Navigation

| English | Chinese Section (click to jump) |
|:--------|:-------------------------------|
| Why MLGG | [为什么需要 MLGG](#为什么需要-mlgg) |
| System Overview | [系统能力总览](#系统能力总览) |
| Quick Start | [快速开始](#快速开始) |
| Phase 1: Cohort & Sample Size | [阶段一：队列定义与样本量](#阶段一队列定义与样本量) |
| Phase 2: Data Splitting | [阶段二：数据划分](#阶段二数据划分) |
| Phase 3: Preprocessing | [阶段三：预处理](#阶段三预处理) |
| Phase 4: Feature Selection | [阶段四：特征筛选](#阶段四特征筛选) |
| Phase 5: Training & Selection | [阶段五：模型训练与选择](#阶段五模型训练与选择) |
| Phase 6: Evaluation & Calibration | [阶段六：评估与校准](#阶段六评估与校准) |
| Phase 7: Multi-Model SHAP | [阶段七：多模型 SHAP 可解释性](#阶段七多模型-shap-可解释性) |
| Phase 8: Fairness & Equity | [阶段八：公平性与亚组分析](#阶段八公平性与亚组分析) |
| Phase 9: Reporting & Compliance | [阶段九：报告与合规](#阶段九报告与合规) |
| 33-Gate DAG | [33 道安全门控](#33-道安全门控-gate-dag) |
| 12-Dimension Scoring | [12 维量化评分](#12-维量化评分) |
| 31 Methodology Rules | [31 条方法论规则](#31-条方法论规则) |
| 20 Model Families | [20 个模型族](#20-个模型族) |
| 14 Medical Datasets | [14 个医学数据集](#14-个医学数据集) |
| Static Analysis (R001-R020) | [20 条静态分析规则](#20-条静态分析规则-r001-r020) |
| 19 Analysis Tools | [19 项分析工具](#19-项分析工具) |
| Security Layer | [安全加固层](#安全加固层) |
| Project Structure | [项目结构](#项目结构) |
| Installation | [安装指南](#安装指南) |
| Commands | [命令参考](#命令参考) |
| Literature | [文献基础](#文献基础) |
| Claude Code | [Claude Code 集成](#claude-code-集成) |
| License & Citation | [许可证与引用](#许可证与引用) |

### License & IP (English Summary)

**PolyForm Noncommercial License 1.0.0.** Commercial use is **strictly prohibited**. Academic use **requires citation** (see BibTeX in [许可证与引用](#许可证与引用)). Uncited reproduction of MLGG methodology in publications constitutes academic misconduct. The Claude Code `/mlgg` Skill is the **only authorized public distribution channel**.
