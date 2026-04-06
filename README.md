# ML Leakage Guard (MLGG) — 医学预测模型完整性标准

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue.svg)](https://polyformproject.org/licenses/noncommercial/1.0.0/)
[![Tests](https://img.shields.io/badge/tests-3400%2B%20passed-brightgreen)]()
[![Gate Coverage](https://img.shields.io/badge/gate%20coverage-%E2%89%A586%25-blue)]()
[![MLGG Standard v1.0](https://img.shields.io/badge/MLGG%20Standard-v1.0-orange)]()
[![TRIPOD+AI 2024](https://img.shields.io/badge/TRIPOD%2BAI-2024-blue)](https://doi.org/10.1136/bmj-2023-078378)
[![PROBAST+AI 2025](https://img.shields.io/badge/PROBAST%2BAI-2025-blue)](https://doi.org/10.1136/bmj-2024-082505)

面向医学二分类预测的发布级防泄漏工作流。33 道 fail-closed 门控，14 个真实医学数据集（526K 行），12 维量化评分，可机器校验的合规证书。

> 医学 ML 数据泄漏导致性能虚高和不安全的临床决策。MLGG 提供可机器验证的标准来预防、检测和报告这些问题——从原始数据到 TRIPOD+AI 合规发表。内置多模型 SHAP 可解释性引擎，输出发表级特征重要性表格。

**[English Version / 英文版](#english-version)**

---

## 为什么需要 MLGG？

医学 ML 论文中数据泄漏的发生率远超预期。常见问题包括：

- 在全数据上做标准化后再划分（**预处理泄漏**）——审稿人可能看不出来，但模型性能被虚抬
- 死亡患者纳入再入院预测队列（**队列定义错误**）——结局结构性不可能，AUROC 被污染
- 药物变化列用 OrdinalEncoder 编码（**假有序性**）——LR 系数失去临床意义
- 只报 AUROC 不报 MCC 和 LR+/LR-（**指标盲区**）——AUROC 0.65 看起来可以，但 MCC 0.12 说明近乎随机
- 用 train-test gap 硬阈值选模型（**无文献支撑**）——可能选到次优模型

**MLGG 的存在就是为了系统性地防止这些问题**——每条规则都来自实际踩坑，每个阈值都有文献引用。

---

## 目录

- [为什么需要 MLGG？](#为什么需要-mlgg)
- [系统能力总览](#系统能力总览)
- [快速开始](#快速开始)
- [9-Phase 工作流](#9-phase-工作流)
- [33 道安全门控 (Gate DAG)](#32-道安全门控-gate-dag)
- [SHAP 多模型可解释性](#shap-多模型可解释性)
- [31 条方法论规则](#31-条方法论规则)
- [参考实现：30 天再入院预测](#参考实现30-天再入院预测)
- [安装指南](#安装指南)
- [命令参考](#命令参考)
- [14 个医学数据集](#14-个医学数据集)
- [静态分析规则 R001-R020](#静态分析规则-r001-r020)
- [项目结构](#项目结构)
- [文献基础](#文献基础)
- [Claude Code 集成](#claude-code-集成)
- [CI/CD](#cicd)
- [许可证、知识产权与使用条款](#许可证知识产权与使用条款)
- [English Version](#english-version)

---

## 系统能力总览

```
原始数据 → 33 道审计门控 → 合规证书 → 可发表报告
```

| 模块 | 说明 | 规模 |
|------|------|------|
| **33 道安全门控** | fail-closed DAG 架构，覆盖泄漏检测 / 可解释性 / 公平性 / 样本量 / 校准 / 鲁棒性 / TRIPOD+AI / PROBAST+AI | 32 个独立 CLI 脚本 |
| **12 维量化评分** (0-100) | 数据完整性 / 泄漏防护 / 管线隔离 / 模型选择 / 统计有效性 / 泛化证据 / 临床完整性 / 报告标准 / 可复现性 / 安全性 / 公平性 / 样本量 | ≥90 顶刊级 |
| **3 级合规** | L1（12 门，泄漏审计）/ L2（25 门，统计有效）/ L3（全部 33 门，发布级） | 渐进认证 |
| **20 个模型族** | LR(L1/L2/ElasticNet) / SVM / RF / XGBoost / CatBoost / LightGBM / KNN / MLP / TabPFN + 集成 | 自动超参搜索 |
| **14 个真实数据集** | UCI / CDC / NCI / Vanderbilt 官方数据 | 总计 526K 行 |
| **多模型 SHAP 引擎** | 多族 SHAP 比例归一化集成 + Kendall tau 一致性检验 + 4 张发表级 CSV 表格 | RF/XGB/CatBoost/LGBM/LR |
| **学术合规引擎** | TRIPOD+AI 2024（27 项）/ PROBAST+AI 2025（4 域 34 问）/ STARD-AI | 58 条文献知识库 |
| **20 条 Lint 规则** | 静态分析检测代码级数据泄漏反模式 (R001-R020) | 支持 .py + .ipynb |
| **安全加固层** | HMAC-SHA256 / AES-256-GCM / 链式审计日志 / 路径穿越防护 | 10+ 防御机制 |

---

## 快速开始

### 审计任何 ML 项目（无需配置）

```bash
python3 scripts/generate_audit_report.py --project-dir /path/to/your/project
```

输出 `audit-report.md` + `audit-report.json`，包含 TRIPOD+AI 覆盖率、PROBAST+AI 偏倚风险评估、错误根因分析、文献引用和优先修复建议。

### 一条命令跑完整引导（约 5 分钟）

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard.git
cd medical-ml-leakage-guard
python3 -m pip install -r requirements.txt
python3 scripts/mlgg.py onboarding --project-root /tmp/mlgg_demo --mode guided --yes
```

### 交互式像素风终端 UI

```bash
python3 scripts/mlgg.py play
```

<details>
<summary><b>play 模式详细说明</b></summary>

- `play` 是交互式快速训练/评估入口，适合探索与教学
- 输出中的"快速就绪检查"**不是** 33 关发布门结论
- 内置模型族：`logistic_l1/l2/elasticnet`、`random_forest`、`extra_trees`、`hist_gradient_boosting`、`adaboost`、`svm_linear`、`svm_rbf`，支持集成模型 `soft_voting/weighted_voting/stacking`
- 小样本数据建议使用 `--strict-small-sample`
- 在列/模型选择菜单中按 `/` 搜索，`Enter` 结束搜索，`c` 清空过滤
- 需要发布级结论请使用 `workflow --strict`

</details>

---

## 9-Phase 工作流

MLGG 强制按以下 9 个阶段顺序执行，每个阶段有明确的检查点，不通过不进入下一阶段。

```
Phase 1  数据理解        定义队列、预测时间点、EPV
    ↓
Phase 2  数据划分        患者级 + 时序划分 (60/20/20)
    ↓
Phase 3  预处理          语义编码 + 分层缺失策略
    ↓
Phase 4  特征筛选        Elastic Net CV + Stability Selection + Ridge 对照
    ↓
Phase 5  模型训练        ≥3 模型族 + bootstrap optimism correction
    ↓
Phase 6  模型评估        完整指标面板 + 校准 + DCA
    ↓
Phase 7  可解释性        SHAP + 跨模型一致性验证
    ↓
Phase 8  公平性          亚组分析 + Bootstrap CI
    ↓
Phase 9  报告            TRIPOD+AI 清单 + 局限性讨论
```

### Phase 1: 数据理解与队列定义

**脚本**：`cohort_definition_gate.py` | **门控**：Layer 0 | **MLGG 规则**：C01, F05, Z01

**1.1 队列定义（MLGG-C01）**

排除结局结构性不可能的记录。例如在再入院预测中，死亡/临终关怀患者不可能再入院，纳入会虚抬 AUROC（实测 +0.004）。排除规则必须在任何分析之前确定，且记录排除人数和理由（TRIPOD+AI Item 4a）。

**1.2 样本量充分性 — Riley 三准则（Riley 2019, Stat Med）**

传统 EPV ≥ 10 规则已被证明"过于简化且缺乏证据支撑"（Riley 2019 原文）。MLGG 实现 Riley 三准则：

| 准则 | 公式（简化形式） | 含义 |
|------|----------------|------|
| C1 收缩因子 | n ≥ p / ((1 - S) × φ), S ≥ 0.9 | 预测系数收缩不超过 10% |
| C2 Optimism | n ≥ p / 0.05 | R² 的表观值与调整值之差 ≤ 0.05 |
| C3 精度 | n ≥ φ(1-φ) / (0.05/1.96)² | 总体风险估计 95% CI 半宽 ≤ 0.05 |

取三者最大值为最小样本量。其中 p = 候选参数数，φ = 事件率。EPV < 5 直接 FAIL，5-10 WARNING。

**1.3 数据类型自动检测**

每列按基数和类型分类为 `numeric`（高基数连续）、`binary`（2 值）、`categorical`（3-20 值）、`constant`（0-1 值）、`id_or_text`（高基数非数值）。输出 `feature_profile.csv`，包含每列的缺失率、唯一值数、描述统计。

**1.4 缺失值概况**

按特征统计缺失率。>50% 缺失的特征自动标记（MLGG-P06 分层缺失策略的输入）。检测纵向/横截面：如果患者 ID 有重复行，标记为纵向数据。

---

### Phase 2: 数据划分

**脚本**：`split_data.py` | **门控**：`split_protocol_gate.py` | **MLGG 规则**：S01, S02

**2.1 患者级 disjoint 划分（MLGG-S01）**

同一患者的所有记录（如多次住院）必须归入同一 split。违反此原则会导致模型"记住"患者特征，虚抬测试性能。实现：按 `patient_id` 分组，组为最小不可分割单位。

**2.2 三种划分策略**

| 策略 | 适用数据 | 时间列 | 原理 |
|------|---------|--------|------|
| `grouped_temporal` | 纵向 EHR / 队列 | 必须 | 按患者首次事件时间排序，前 60% train、中 20% valid、后 20% test。保证 train 时间 < valid < test（MLGG-S02）|
| `grouped_random` | 横截面调查（NHANES、BRFSS） | 不需要 | 患者随机打乱后按比例分配。`--cross-sectional` 跳过时序检查 |
| `stratified_grouped` | 横截面 + 需保证正类比例一致 | 不需要 | 按结局标签分层，层内随机分配，各 split 正类率差异 < 3% |

**2.3 安全约束**

- 每 split 最少 20 行、10 正例、10 负例、5 个独立患者
- 正类率漂移 > 10% 发出 WARNING
- 门控检查零容忍：任何患者 ID 跨 split 重叠 → 立即 FAIL

---

### Phase 3: 预处理

**脚本**：`train_select_evaluate.py` Pipeline 内建 | **MLGG 规则**：P01-P06

**3.1 核心原则：所有 fit() 仅在训练集（MLGG-P01/P03/P04）**

预处理管道结构：`Imputer → Scaler → Classifier`，每一步的统计量（中位数、均值、标准差、类别映射）只从训练集计算，验证集和测试集只调用 `.transform()`。这防止了最常见的数据泄漏——预处理泄漏（Kaufman 2012, ACM TKDD）。

**3.2 自动分类变量检测与编码（MLGG-P05）**

| 特征类型 | 检测条件 | 编码方法 | OOD 安全性 |
|----------|---------|---------|-----------|
| Binary（2 值） | `nunique == 2` | 按 train 映射为 0/1，`.fillna(0.0)` | 未见类别 → 0.0 |
| Categorical（3-15 值） | `3 ≤ nunique ≤ 15` | OneHot，train 类别决定 dummy 列 | 未见类别 → 全零行 |
| Numeric（> 15 值或连续） | `nunique > 15` 且 numeric | 保持原值 | N/A |
| High-cardinality（> 15 非数值） | `nunique > 15` 且 string | 保持原值（用户自行处理） | N/A |

**为什么不用 OrdinalEncoder 编码名义变量**：名义变量（如 race=1,2,3,4,5）用 OrdinalEncoder 会让模型假设 race=5 是 race=1 的 5 倍——LR 系数失去临床意义（实测：改为 OneHot 后 LR AUROC +0.02）。

**3.3 分层缺失策略（MLGG-P06, Madley-Dowd 2019）**

不使用固定阈值（如"丢弃 >60% 缺失"），而是按缺失机制分层：

| 层级 | 缺失率范围 | 策略 | 理由 |
|------|-----------|------|------|
| Tier 4 | > 80% | 丢弃原值，保留缺失指示变量 | 原值信息已极度稀疏，但"是否缺失"本身可能有预测价值（如"体重未测量"→门诊 vs 住院） |
| Tier 3 | 40-80% | 插补 + 缺失指示变量 | 插补可能不准，指示变量补偿 |
| Tier 2 | 5-40% | 插补 + 缺失指示变量 | 标准 MAR 处理 |
| Tier 1 | < 5% | 简单插补（中位数/众数） | 缺失太少，不值得复杂处理 |

**3.4 SMOTE 立场**

van den Goorbergh 2022 (JAMIA) 证明 SMOTE 严重损害风险预测模型的概率校准。MLGG 默认不使用 SMOTE，改用 `class_weight="balanced"` + 事后 Platt scaling 校准。

---

### Phase 4: 特征筛选

**脚本**：`train_select_evaluate.py` 内建 | **MLGG 规则**：F01-F06

**4.1 设计哲学**

Harrell 2015 和 Steyerberg 2019 推荐"临床先验预指定 + 惩罚收缩"而非数据驱动筛选。但当候选特征远超临床知识时，MLGG 提供以下有控制的筛选路径。

**4.2 Elastic Net CV（Zou & Hastie 2005）**

联合调优正则化参数 α（L1/L2 混合比）和 C（正则化强度）：
- α ∈ {0.1, 0.3, 0.5, 0.7, 1.0}：0.1 接近 Ridge（保留所有特征），1.0 等价 LASSO（稀疏）
- C ∈ {0.001, 0.01, 0.1, 1.0, 10.0}
- 5 折 StratifiedKFold 内部 CV，选择 PR-AUC 最优组合
- **分组选择**（Yuan & Lin 2006, Group LASSO 思想）：OneHot 产生的 dummy 列属于同一原始变量，必须同进同退。防止选 `race_Caucasian` 但丢 `race_Asian`

**4.3 稳定性选择（Meinshausen & Buhlmann 2010）**

- 100 次子采样（每次抽 50% 训练集）
- 每次拟合 Elastic Net，记录非零特征
- 特征入选概率 = 100 次中被选中的次数 / 100
- 保留入选概率 > 0.6 的特征
- 提供有限样本误选界：期望误选数 E[V] ≤ q² / ((2π - 1) × p)

**4.4 Ridge 对照（Harrell 2015 推荐）**

始终与"不做筛选、只用 Ridge 收缩"的全量模型比较。如果 Elastic Net 选择后 PR-AUC 损失 > 0.005，回退到全量 Ridge。

**4.5 废弃单因素筛选**

Heinze 2018 (Biometrical Journal) 明确反对单因素 p 值筛选：导致多重比较问题、丢弃弱但联合有效的特征、引入选择偏倚。MLGG 只将单因素分析（Mann-Whitney U）作为诊断工具，不用于特征选择决策。

---

### Phase 5: 模型训练与选择

**脚本**：`train_select_evaluate.py` | **MLGG 规则**：M01-M04, R01

**5.1 候选模型族（MLGG-M03：≥ 3 族）**

MLGG 支持 20 个模型族，推荐至少比较：
- **Logistic Regression**（L1/L2/ElasticNet）— 线性基线，系数可直接解释
- **Random Forest** — 非线性 + 交互，天然处理缺失
- **XGBoost / LightGBM** — 梯度提升，通常性能最优
- **（可选）CatBoost / SVM / KNN / MLP / TabPFN**

每族定义超参数网格（如 RF: n_estimators ∈ {300, 500}, max_depth ∈ {4, 5, 6}），通过 Optuna TPE sampler 或 Grid Search 在**验证集**上调优。

**5.2 模型选择标准（MLGG-M04, Yang KDD 2023）**

**不使用 train-test gap** 选模型。Yang et al. 2023 证明验证集性能是更可靠的模型选择准则：

```
✗ 旧做法: 选 gap = |AUC_train - AUC_test| 最小的模型
✓ MLGG:   选 validation PR-AUC 最高的模型（one-SE rule 破平局）
```

one-SE 规则：在最优性能的 1 个标准误范围内，选择复杂度最低的模型（偏好 LR > RF > XGBoost）。

**5.3 阈值选择（MLGG-M02）**

在**验证集**上通过 Youden's J 统计量确定最优分类阈值：

```
J = Sensitivity + Specificity - 1
threshold* = argmax_t J(t)
```

阈值绝不在测试集上选择或调整（MLGG-M01 零容忍）。

**5.4 Bootstrap Optimism Correction（Steyerberg 2019 Ch.17）**

内部验证方法，估计模型性能的"乐观偏差"：
1. 在原训练集上拟合模型，计算 apparent performance
2. 重复 B 次（B ≥ 100）：Bootstrap 重采样 → 拟合 → 在 bootstrap 样本和原样本上分别评估 → 差值 = optimism
3. Optimism-corrected performance = apparent - mean(optimism)

**5.5 学习曲线（Figueroa 2012）**

评估模型是否已"收敛"——训练数据再增加是否还能提升性能。在 {10%, 20%, 30%, 50%, 70%, 85%, 100%} 训练集比例上分别训练，报告 test PR-AUC。若 70%→100% 提升 < 0.005，认为已收敛。

---

### Phase 6: 评估与校准

**脚本**：`train_select_evaluate.py` + 13 道统计门控 | **MLGG 规则**：E01-E06

**6.1 完整指标面板（MLGG-E02）**

测试集一次性使用，报告以下 5 域指标（对标 Lancet Digital Health 2025 评估框架）：

| 域 | 指标 | 目标/解读 |
|----|------|----------|
| **区分度** | AUROC, AUPRC | 模型区分正/负的能力。AUPRC 对不平衡数据更敏感 |
| **校准** | 校准截距(→0)、斜率(→1)、O:E 比(→1)、ECE、Hosmer-Lemeshow χ² | 预测概率与实际风险的一致性（Van Calster 2019） |
| **整体性能** | Brier score, Brier Skill Score, Log loss | BSS = 1 - Brier_model / Brier_prevalence，>0 优于基线 |
| **分类** | Sensitivity, Specificity, PPV, NPV, F1, **MCC**, Balanced Accuracy | MCC 是不平衡数据下唯一可靠的单一分类指标（Chicco 2020） |
| **临床效用** | **LR+/LR-**, DCA 净效用, NRI, IDI | LR+ > 5 有临床价值，LR- < 0.2 可排除（Deeks 2004） |

**为什么必须报 MCC 和 LR+/LR-**：AUROC 0.65 可能看起来"还行"，但 MCC 0.12（接近随机）和 LR+ 1.6（无决策价值）揭示模型真实能力。仅报 AUROC/F1 是选择性报告。

**6.2 校准三件套（Van Calster 2019, BMC Medicine）**

通过 logistic recalibration 拟合 `logit(y) ~ a + b × logit(ŷ)`：

| 指标 | 公式 | 理想值 | 偏离含义 |
|------|------|--------|---------|
| 校准截距 a | logistic 回归截距 | 0 | a < 0 → 系统高估; a > 0 → 系统低估 |
| 校准斜率 b | logistic 回归系数 | 1 | b < 1 → 过拟合（预测过于极端）; b > 1 → 欠拟合 |
| O:E 比 | Σy / Σŷ | 1 | 观察事件数 vs 期望事件数的比 |

**校准层级**（Van Calster 2016, J Clin Epidemiol）：weak（截距+斜率正确）→ moderate（分组一致性，Hosmer-Lemeshow）→ strong（逐点一致性）。MLGG 要求至少达到 moderate。

**6.3 Brier Skill Score**

```
BSS = 1 - Brier_model / Brier_reference
Brier_reference = prevalence × (1 - prevalence)
```

BSS > 0 表示模型优于"只预测基线患病率"。BSS = 0 等价于随机。顶刊要求报告 BSS 而非裸 Brier score。

**6.4 NRI / IDI（Pencina 2008, Statistics in Medicine）**

比较新模型 vs 参考模型（如 LR 基线）的重分类改善：

| 指标 | 含义 |
|------|------|
| Categorical NRI | 在阈值处，新模型正确重分类的净比例 |
| Continuous NRI | 不依赖阈值的重分类改善 |
| IDI (Integrated Discrimination Improvement) | 事件组和非事件组预测概率差的改善量 |

**6.5 Bootstrap 95% CI（MLGG-E01）**

所有主要指标使用 percentile bootstrap（B ≥ 1000）计算 95% CI。不使用正态近似（小样本/非对称分布不可靠）。

**6.6 多种子稳定性（MLGG-R02）**

同一模型用 ≥ 5 个不同随机种子训练，报告测试集 AUROC 标准差。std > 0.02 表示模型不稳定，需要集成或更换架构。

**6.7 事后校准（MLGG-E05）**

`class_weight="balanced"` 会扭曲预测概率（ECE 可达 0.3-0.4）。必须用 Platt scaling（logistic 校准，Platt 2000）或 isotonic regression 在**验证集**上拟合校准器，然后应用于测试集。校准后 ECE 应 < 0.1。

---

### Phase 7: 多模型 SHAP 可解释性

**脚本**：`shap_interpretability_gate.py` | **门控**：Layer 5

**7.1 为什么多模型而非单模型**

不同模型族有不同的归纳偏差：RF 偏好交互特征、XGBoost 偏好非线性分段、LR 只看线性效应。单模型 SHAP 排名反映的是该模型的"世界观"，不是数据的真相（Rashomon 效应，Breiman 2001）。多模型平均更鲁棒。

**7.2 计算流程**

```
对每个模型族 m ∈ {RF, XGB, CatBoost, LGBM, LR, ...}:
  1. 从 Pipeline 中提取 clf，用前序步骤 transform 数据
  2. 选择 Explainer:
     - TreeExplainer（精确，O(TLD)）: RF / XGB / CatBoost / LGBM
     - LinearExplainer（精确，O(M×D)）: LR
     - KernelExplainer（近似，O(2^M)）: SVM / KNN / MLP
  3. 背景数据：训练集子采样（默认 200 行）
  4. 解释数据：测试集子采样（默认 500 行）
  5. 计算 SHAP values → (n_explain × n_features) 矩阵
```

**7.3 比例归一化集成（PMC11513550 方法）**

```
对每个模型 m:
  abs_importance_m = mean(|SHAP_m|, axis=samples)     → (n_features,)
  proportion_m     = abs_importance_m / sum(abs_importance_m)  → sum=1

跨模型集成:
  ensemble_proportion = mean(proportion_m, for all m)  → 等权平均
```

L1 归一化消除模型间尺度差异（RF 的 SHAP 值可能在 [0, 0.02]，XGBoost 在 [0, 0.15]），确保每个模型族对最终排名的投票权相等。

**7.4 跨模型一致性检验**

- **Kendall tau 排名相关**：衡量两个模型的特征重要性排名是否一致。τ > 0.7 = 强一致，0.5-0.7 = 中等，< 0.5 = 弱（需警惕）
- **Top-N Jaccard 重叠**：Top-10 特征集合的 Jaccard 系数。值越高 = 模型共识越强
- **方向一致性**：如果所有模型的 signed SHAP 均 > 0，标记为 `positive`；均 < 0 为 `negative`；有正有负为 `mixed`（需关注）

**7.5 输出 4 张发表级 CSV 表格**

| 表 | 文件 | 用途 | 列 |
|----|------|------|-----|
| **A** | `shap_table_a_ensemble_importance.csv` | 论文主表 | Rank, Feature, Ensemble_Proportion, Direction, 各模型 Proportion |
| **B** | `shap_table_b_per_model_detail.csv` | 审稿人补充表 | Feature, 每模型 MeanAbsSHAP/Proportion/SignedSHAP/Rank |
| **C** | `shap_table_c_rank_agreement.csv` | 方法学证据 | Model_A, Model_B, Kendall_τ, P_Value, Top10_Overlap, Jaccard |
| **D** | `shap_table_d_case_explanations.csv` | 临床叙事 | Case_Index, Risk_Category, Y_True, Score, Top-3 驱动特征 |

每张 CSV 首行为方法论注释（`# Method: ...`），可被 `pd.read_csv(comment="#")` 跳过。

---

### Phase 8: 公平性与亚组分析

**门控**：`fairness_equity_gate.py` | **MLGG 规则**：Q01, Q02

**8.1 亚组分析（MLGG-Q01, TRIPOD+AI Item 16b）**

按保护属性（race、gender、age）分组，每组独立计算：AUROC、AUPRC、Sensitivity、Specificity、PPV、FPR、prevalence。

**8.2 小亚组不可靠标记（MLGG-Q02）**

n < 200 的亚组标记为"估计不可靠"（Steyerberg 2019 Ch.25 外部验证样本量指导）。不作为比较依据。

**8.3 差异标记**

- AUROC max-min 差异 > 0.05 → WARNING
- Sensitivity max-min 差异 > 0.10 → WARNING
- 所有差异指标附 Bootstrap CI

---

### Phase 9: 报告与合规

**门控**：`publication_gate.py` + `self_critique_gate.py` | **MLGG 规则**：T01

**9.1 TRIPOD+AI 2024 清单（Collins 2024, BMJ）**

27 项逐项核对，机器验证每项是否有对应证据文件。未满足项标记为 `incomplete`。

**9.2 PROBAST+AI 2025 偏倚风险（Moons 2025, Ann Intern Med）**

4 域评估：Participants & Data → Predictors → Outcome → Analysis。16 个信号问题，每域判定 low / high / unclear。

**9.3 局限性结构化讨论**

必须覆盖：数据来源局限、时间有效性、编码体系变化（如 ICD-9 → ICD-10）、外部效度、公平性局限、DCA 临床效用结论。如 DCA 显示无净效用，必须诚实报告——不隐瞒负面结果。

---

## 33 道安全门控 (Gate DAG)

32 道门控按 DAG（有向无环图）分 9 层执行。同层可并行，每层必须完成后才能执行下一层。全部通过才能声称 Publication-Grade (L3)。

```
Layer 0  契约验证          cohort_definition_gate | request_contract_gate
    ↓
Layer 1  指纹锁定          manifest_lock
    ↓
Layer 2  执行证明          execution_attestation_gate
    ↓
Layer 3  数据验证          leakage_gate | split_protocol_gate | covariate_shift_gate | reporting_bias_gate
    ↓
Layer 4  策略审计          definition_variable_guard | feature_lineage_gate | imbalance_policy_gate | missingness_policy_gate | tuning_leakage_gate
    ↓
Layer 5  模型审计          model_selection_audit_gate | feature_engineering_audit_gate | clinical_metrics_gate | shap_interpretability_gate
    ↓
Layer 6  统计验证          calibration_dca_gate | ci_matrix_gate | distribution_generalization_gate | evaluation_quality_gate | external_validation_gate | fairness_equity_gate | generalization_gap_gate | metric_consistency_gate | permutation_significance_gate | prediction_replay_gate | robustness_gate | sample_size_gate | seed_stability_gate
    ↓
Layer 7  发布聚合          publication_gate
    ↓
Layer 8  终审              self_critique_gate | security_audit_gate
```

<details>
<summary><b>33 道门控详细说明（点击展开）</b></summary>

### Layer 0: 契约验证

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 0 | `cohort_definition_gate.py` | **Phase 1**: 队列定义、EPV 充分性、数据类型检测、缺失值概况 | `cohort_definition_report.json` |
| 1 | `request_contract_gate.py` | 验证请求 JSON 模式、文件路径、发布策略反降级保护 | `request_contract_report.json` |

### Layer 1: 指纹锁定

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 2 | `manifest_lock.py` | SHA-256 加密锁定所有数据/配置/评估/门控脚本指纹，支持基线对比 | `manifest.json` |

### Layer 2: 执行证明

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 3 | `execution_attestation_gate.py` | 验证签名运行证明、工件哈希、密钥有效性、时间戳、见证人仲裁 | `execution_attestation_report.json` |

### Layer 3: 数据验证（4 门并行）

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 4 | `leakage_gate.py` | 检查划分污染、患者 ID 重叠、时间边界违规 | `leakage_report.json` |
| 5 | `split_protocol_gate.py` | 强制划分协议一致性、时序/分组安全保障 | `split_protocol_report.json` |
| 6 | `covariate_shift_gate.py` | 检测训练集 vs 验证集的协变量漂移和划分可分性风险 | `covariate_shift_report.json` |
| 7 | `reporting_bias_gate.py` | TRIPOD+AI / PROBAST+AI / STARD-AI 清单硬门控 | `reporting_bias_report.json` |

### Layer 4: 策略审计（5 门并行）

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 8 | `definition_variable_guard.py` | 阻止疾病定义变量泄漏（如用确诊标志作为预测特征） | `definition_guard_report.json` |
| 9 | `feature_lineage_gate.py` | 阻止血缘衍生特征泄漏（特征来自索引时间之后的数据） | `lineage_report.json` |
| 10 | `imbalance_policy_gate.py` | 验证类别不平衡策略和训练集独占重采样策略 | `imbalance_policy_report.json` |
| 11 | `missingness_policy_gate.py` | 验证缺失数据策略、MICE 规模保护、插补器隔离 | `missingness_policy_report.json` |
| 12 | `tuning_leakage_gate.py` | 验证超参调优和测试集隔离协议 | `tuning_leakage_report.json` |

### Layer 5: 模型审计（4 门并行）

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 13 | `model_selection_audit_gate.py` | 审计候选池、one-SE 回放、测试集隔离的模型选择 | `model_selection_audit_report.json` |
| 14 | `feature_engineering_audit_gate.py` | 审计特征组来源、训练集独占范围、稳定性证据 | `feature_engineering_audit_report.json` |
| 15 | `clinical_metrics_gate.py` | 验证临床指标完整性和混淆矩阵一致性 | `clinical_metrics_report.json` |
| 16 | `shap_interpretability_gate.py` | 多模型 SHAP 集成重要性 + 跨模型一致性 + 个案解释 + 4 张 CSV | `shap_interpretability_report.json` |

### Layer 6: 统计验证（13 门并行）

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 17 | `calibration_dca_gate.py` | 概率校准和决策曲线分析 | `calibration_dca_report.json` |
| 18 | `ci_matrix_gate.py` | 所有划分和队列的主要指标 Bootstrap CI 矩阵 | `ci_matrix_gate_report.json` |
| 19 | `distribution_generalization_gate.py` | 训练集 vs 验证集分布漂移评估和迁移准备度 | `distribution_generalization_report.json` |
| 20 | `evaluation_quality_gate.py` | 强制主要指标 CI 质量和基线改善要求 | `evaluation_quality_report.json` |
| 21 | `external_validation_gate.py` | 外部队列（跨时期/跨机构）指标验证 | `external_validation_gate_report.json` |
| 22 | `fairness_equity_gate.py` | 亚组公平性和健康公平审计 | `fairness_equity_report.json` |
| 23 | `generalization_gap_gate.py` | 训练/验证/测试的过拟合差距 fail-closed 检查 | `generalization_gap_report.json` |
| 24 | `metric_consistency_gate.py` | 从评估报告提取并验证指标一致性 | `metric_consistency_report.json` |
| 25 | `permutation_significance_gate.py` | 基于置换的伪造显著性检验 | `permutation_report.json` |
| 26 | `prediction_replay_gate.py` | 从预测轨迹回放验证指标可复现性 | `prediction_replay_report.json` |
| 27 | `robustness_gate.py` | 亚组鲁棒性分析 | `robustness_gate_report.json` |
| 28 | `sample_size_gate.py` | 样本量充分性（EPV / Riley 标准） | `sample_size_report.json` |
| 29 | `seed_stability_gate.py` | 多种子稳定性分析 | `seed_stability_report.json` |

### Layer 7: 发布聚合

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 30 | `publication_gate.py` | 聚合所有门控结果为最终发布就绪判定 | `publication_gate_report.json` |

### Layer 8: 终审

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 31 | `self_critique_gate.py` | 12 维量化评分 + 审稿人级自我批评 | `self_critique_report.json` |
| 32 | `security_audit_gate.py` | 加密模型签名 + 工件完整性 + 敏感数据保护 | `security_audit_report.json` |

### 三级合规要求

| 等级 | 名称 | 要求门控数 | strict 模式 | TRIPOD+AI 覆盖 | PROBAST ROB | 适用场景 |
|------|------|-----------|------------|---------------|------------|---------|
| **L1** | 泄漏审计 | 12 门 | 否 | — | — | 会议论文、初步报告 |
| **L2** | 统计有效 | 25 门 | 否 | ≥17/27 | low/unclear | 专业期刊（JAMIA, npj Digital Medicine） |
| **L3** | 发布级 | **全部 33 门** | **是** | ≥23/27 | **low** | Nature Medicine, Lancet, JAMA, BMJ |

### 12 维评分体系 (0-100 分)

| # | 维度 | 权重 | 评估内容 |
|---|------|------|---------|
| 1 | 数据完整性 | 12 | 划分隔离、患者不重叠、时序正确、行无重复 |
| 2 | 泄漏防护 | 15 | 目标泄漏、定义变量泄漏、血缘泄漏、索引后泄漏 |
| 3 | 管线隔离 | 12 | 预处理器、插补器、重采样的训练集独占约束 |
| 4 | 模型选择严谨性 | 10 | 候选池、one-SE 规则、禁止偷看测试集、基线比较器 |
| 5 | 统计有效性 | 12 | Bootstrap CI、置换检验、校准、DCA、指标一致性 |
| 6 | 泛化证据 | 10 | 训练-测试差距、外部队列、迁移 CI、种子稳定性 |
| 7 | 临床完整性 | 7 | 完整指标面板、混淆矩阵一致性、阈值可行性 |
| 8 | 报告标准 | 7 | TRIPOD+AI、PROBAST+AI、排除标准、局限性文档 |
| 9 | 可复现性 | 6 | 种子记录、版本追踪、执行证明、指纹锁定 |
| 10 | 安全与溯源 | 3 | 模型签名、工件完整性、敏感数据保护 |
| 11 | 公平与公正 | 3 | 亚组性能差异、人口学偏倚、健康公平审计 |
| 12 | 样本量充分性 | 3 | EPV 标准、Riley 标准、有效样本量相对于模型复杂度 |

**评分解读**：≥90 顶刊级 (L3) / 75-89 需补充 (L2) / 60-74 重大缺陷 (L1) / <60 不可发表

</details>

---

## SHAP 多模型可解释性

MLGG 内置多模型 SHAP 可解释性引擎（`shap_interpretability_gate.py`），核心方法论：

### 方法

1. **多族独立计算**：对模型池中每个族（RF / XGBoost / CatBoost / LightGBM / LR 等）使用最优 Explainer（TreeExplainer / LinearExplainer / KernelExplainer）独立计算 SHAP values
2. **比例归一化集成**：每模型 `mean(|SHAP|)` → L1 归一化为比例（sum=1）→ 跨模型等权平均。消除不同模型族的尺度差异，每族投票权相等
3. **双轨报告**：绝对值比例（哪些特征重要）+ 带符号均值（特征推高还是推低风险）
4. **一致性检验**：Kendall tau 排名相关 + Top-N Jaccard 重叠系数

**理论基础**：不同模型族有不同的归纳偏差（RF 偏好交互、XGB 偏好非线性分段、LR 只看线性），单模型 SHAP 反映模型"世界观"而非数据真相。多模型平均更鲁棒（Rashomon 效应，Breiman 2001）。归一化方法参考 PMC11513550。

### 输出表格

| 表格 | 文件名 | 内容 | 用途 |
|------|--------|------|------|
| **Table A** | `shap_table_a_ensemble_importance.csv` | Rank / Feature / Ensemble_Proportion / Direction / 各模型 Proportion | 论文主表 |
| **Table B** | `shap_table_b_per_model_detail.csv` | 每模型 MeanAbsSHAP / Proportion / SignedSHAP / Rank | 审稿人补充表 |
| **Table C** | `shap_table_c_rank_agreement.csv` | Model A / Model B / Kendall τ / p-value / Top-N Overlap / Jaccard | 方法学证据 |
| **Table D** | `shap_table_d_case_explanations.csv` | Case / Risk / y_true / Score / Top-3 驱动特征 + SHAP | 临床叙事 |

### 使用

```bash
# 训练时生成模型池
python3 scripts/train_select_evaluate.py \
  --model-pool-out evidence/model_pool.pkl \
  ... # 其他训练参数

# 运行 SHAP 门控
python3 scripts/shap_interpretability_gate.py \
  --model-pool evidence/model_pool.pkl \
  --train-data data/train.csv \
  --test-data data/test.csv \
  --target-col y \
  --background-samples 200 \
  --explain-samples 500 \
  --top-n 20 \
  --report evidence/shap_interpretability_report.json \
  --strict
```

### 验证检查

| 代码 | 严重度 | 含义 |
|------|--------|------|
| `SHAP_RANK_DISAGREEMENT` | WARN/ERR | 模型间 Kendall tau 低于阈值 |
| `SHAP_SUSPICIOUS_TOP_FEATURE` | WARN | Top 特征匹配 post-outcome 模式 |
| `SHAP_EXTREME_CONCENTRATION` | WARN | 单特征占 >50% 总重要性 |
| `SHAP_ALL_ZEROS` | ERR | 某模型 SHAP 全零 |
| `SHAP_NAN_DETECTED` | ERR | SHAP 计算产生 NaN |
| `SHAP_SINGLE_MODEL` | WARN | 只有 1 个模型族 |
| `SHAP_FEATURE_MISMATCH` | ERR | 模型与数据列不匹配 |

---

## 31 条方法论规则

<details>
<summary><b>完整规则表（点击展开）</b></summary>

| ID | 严重度 | 规则 | 文献来源 |
|----|--------|------|----------|
| **C01** | CRITICAL | 定义合格队列——排除结局结构性不可能的记录 | 本项目实证：AUROC 被死亡患者虚抬 0.004 |
| **S01** | CRITICAL | 按患者 ID 划分——同一患者不跨 split | |
| **S02** | CRITICAL | 测试集时间必须晚于训练集 | |
| **P01** | CRITICAL | 预处理器仅在训练集上 fit | |
| **P02** | CRITICAL | SMOTE 仅在训练集。慎用：损害校准 | van den Goorbergh 2022 (JAMIA) |
| **P03** | CRITICAL | 划分前禁止全局清洗 | |
| **P04** | CRITICAL | 插补统计量仅来自训练集 | |
| **P05** | CRITICAL | 名义 → OneHotEncoder；有序 → OrdinalEncoder（需实证验证单调性） | 本项目：LR AUROC +0.02 |
| **P06** | WARNING | 缺失按机制分层，不用固定丢弃阈值 | Madley-Dowd 2019, Sperrin 2020 |
| **F01** | CRITICAL | 禁止目标变量作为特征 | |
| **F02** | CRITICAL | 禁止未来信息 | |
| **F03** | CRITICAL | 特征选择仅在训练集 | |
| **F04** | WARNING | ~~单因素筛选~~已废弃，用 Elastic Net 或 Ridge | Heinze 2018, Harrell 2015 |
| **F05** | CRITICAL | 定义预测时间点；分类所有特征的时间归属；比较入院时 vs 出院时模型 | TRIPOD+AI Item 4b |
| **F06** | WARNING | Elastic Net 分组选择 + Stability Selection + Ridge 对照 | Zou & Hastie 2005, Meinshausen 2010 |
| **M01** | CRITICAL | 禁止在测试集调参 | |
| **M02** | CRITICAL | 阈值在验证集选择（Youden's J 或成本敏感方法） | |
| **M03** | WARNING | 比较 ≥3 个模型族 | |
| **M04** | CRITICAL | 模型选择用 validation 性能，不用 train-test gap | Yang et al. KDD 2023 |
| **E01** | CRITICAL | 所有主要指标需 95% CI（bootstrap ≥1000） | |
| **E02** | CRITICAL | 完整指标面板：区分度 + 分类（含 MCC, LR+/LR-）+ 校准三件套 + DCA | Van Calster 2019, Chicco 2020 |
| **E03** | WARNING | 校准 ECE < 0.1 | |
| **E04** | WARNING | Train-test gap 仅作诊断报告，不作选择标准 | Steyerberg 2019 |
| **E05** | WARNING | class_weight="balanced" 需事后校准 | |
| **E06** | WARNING | Bootstrap optimism correction（≥100 次重采样） | Steyerberg 2019, Harrell 2015 |
| **Z01** | WARNING | 样本量：EPV ≥ 10（简化）；严格用 Riley 2019 标准 | Peduzzi 1996, Riley 2019 |
| **R01** | INFO | 设置 random_state | |
| **R02** | WARNING | 多种子稳定性（≥5 seeds, std < 0.02） | |
| **T01** | WARNING | TRIPOD+AI 2024 合规 | Collins et al. 2024 (BMJ) |
| **Q01** | WARNING | 亚组分析（性别/年龄/种族） | |
| **Q02** | WARNING | 亚组指标需 Bootstrap CI；n < 200 标为不可靠 | |

</details>

---

## 参考实现

`examples/medical_ml_demo/` — UCI 糖尿病 130 家医院数据集（99,330 例）的完整 9-Phase 分析。最优模型 LightGBM AUROC 0.647 (95% CI: 0.631-0.661)，MCC 0.122。诚实结论：校准良好但区分度不足以支撑独立临床决策。详见该目录下 README。

---

## 19 项框架级分析工具

`_gate_utils.py` + `cohort_definition_gate.py` 提供 19 个即调即用的分析函数，100% 覆盖 [Nature Portfolio ML Checklist V1.1](https://www.nature.com/documents/machine-learning-checklist.pdf) 全部 30 项检查：

| 工具 | 函数 | 审稿人常问 | NC Checklist | 文献 |
|------|------|-----------|:---:|------|
| **Riley 样本量** | `riley_sample_size()` | "样本量论证？" | — | Riley 2019 (Stat Med) |
| **校准三件套** | `calibration_metrics()` | "校准斜率/截距？" | 4A | Van Calster 2019 (BMC Med) |
| **校准 per-bin CI** | `calibration_bin_ci()` | "校准曲线有 CI 吗？" | 4A | NC Reviewer #2 |
| **NRI / IDI** | `compute_nri_idi()` | "比基线模型好多少？" | 4D | Pencina 2008 (Stat Med) |
| **学习曲线** | `learning_curve_data()` | "数据量够吗？" | — | Figueroa 2012 |
| **VIF 共线性** | `compute_vif()` | "特征间共线性？" | — | PMC4888898 |
| **非线性检验** | `check_nonlinearity()` | "线性假设合理吗？" | — | Harrell 2015 |
| **系数导出** | `export_model_coefficients()` | "模型系数是什么？" | — | NC Reviewer #1 |
| **MNAR 敏感性** | `mnar_sensitivity_analysis()` | "MAR 假设如果错了？" | — | PMC10481859 |
| **时序漂移** | `temporal_drift_analysis()` | "模型部署后还准吗？" | — | PMC8627243 |
| **Model Card** | `generate_model_card()` | "结构化模型文档？" | **3B** | Mitchell 2019 |
| **插补敏感性** | `imputation_sensitivity()` | "换插补方法结论变吗？" | — | Pop Health Metrics 2024 |
| **亚组 DCA** | `subgroup_dca()` | "少数族裔有临床效用吗？" | — | Nature Comp Sci 2025 |
| **基线对比** | `baseline_comparisons()` | "比随机/prevalence 好多少？" | **4D** | NC ML Checklist V1.1 |
| **特征消融** | `feature_ablation()` | "去掉关键特征性能怎么变？" | **4F** | NC ML Checklist V1.1 |
| **计算资源** | `compute_resource_report()` | "训练用了多少资源？" | **5A/5B** | NC ML Checklist V1.1 |
| **Rubin's Rules** | `rubins_rules_combine()` | "多重插补怎么合并？" | — | Rubin 1987 |
| **鲁棒性压力测试** | `robustness_stress_test()` | "对异常值/噪声稳定吗？" | — | 原创 |
| **Bootstrap Optimism** | `bootstrap_optimism_correction()` | "内部验证的乐观偏差？" | — | Steyerberg 2019 Ch.17 |

VIF、非线性检验自动集成在 Phase 4。其余可按需调用。

---

## 安装指南

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard.git
cd medical-ml-leakage-guard
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

# 可选：模型后端
python3 -m pip install -r requirements-optional.txt

# 验证安装
python3 scripts/mlgg.py doctor
```

**环境要求**：Python 3.10+，`numpy`，`pandas`，`scikit-learn`，`scipy`，`joblib`。可选：`xgboost`，`catboost`，`lightgbm`，`tabpfn`，`optuna`，`shap`。

---

## 命令参考

| 目标 | 命令 |
|------|------|
| 审计外部项目 | `python3 scripts/generate_audit_report.py --project-dir /path` |
| 交互式探索 | `python3 scripts/mlgg.py play` |
| 引导式首跑 | `python3 scripts/mlgg.py onboarding --project-root /tmp/demo --mode guided --yes` |
| 发布级判定 | `python3 scripts/mlgg.py workflow --request <project>/configs/request.json --strict` |
| 环境检查 | `python3 scripts/mlgg.py doctor` |
| 初始化项目 | `python3 scripts/mlgg.py init --project-root /tmp/project` |
| 静态 Lint | `python3 -m mlgg_lint /path/to/code/` |
| 下载数据集 | `python3 examples/download_real_data.py heart` |

<details>
<summary><b>选择建议</b></summary>

| 场景 | 推荐 |
|------|------|
| 首次使用，想探索 | `play` |
| 构建发表级模型 | `onboarding --mode guided` → `workflow --strict` |
| 审查他人代码 | `generate_audit_report.py` 或 `mlgg_lint` |
| 教学 / 课堂 | `play --strict-small-sample` |

</details>

<details>
<summary><b>自有 CSV 最短严格闭环</b></summary>

```bash
# 1) 初始化项目
python3 scripts/mlgg.py init --project-root /tmp/mlgg_project

# 2) 安全分割
python3 scripts/mlgg.py split -- \
  --input /path/to/your_data.csv \
  --output-dir /tmp/mlgg_project/data \
  --patient-id-col patient_id --target-col y --time-col event_time \
  --strategy grouped_temporal

# 3) 交互训练
python3 scripts/mlgg.py train --interactive

# 4) 严格审计（bootstrap 基线）
python3 scripts/mlgg.py workflow \
  --request /tmp/mlgg_project/configs/request.json \
  --strict --allow-missing-compare

# 5) 严格对比复跑
python3 scripts/mlgg.py workflow \
  --request /tmp/mlgg_project/configs/request.json \
  --strict \
  --compare-manifest /tmp/mlgg_project/evidence/manifest_baseline.bootstrap.json
```

</details>

---

## 14 个医学数据集

<details>
<summary><b>大型数据集（>10K 行）</b></summary>

```bash
python3 examples/download_real_data.py diabetes130_full   # UCI 101K 再入院
python3 examples/download_real_data.py sepsis_survival    # UCI 129K 脓毒症存活
python3 examples/download_real_data.py rhc                # Vanderbilt 5.7K ICU 死亡率
python3 examples/download_cdc_data.py brfss               # CDC BRFSS 100K 糖尿病
python3 examples/download_cdc_data.py nhis                # CDC NHIS 28K 糖尿病
python3 examples/download_cdc_data.py covid               # CDC COVID-19 100K 住院
python3 examples/download_nhanes.py --cycles both         # CDC NHANES 16K 糖尿病
python3 examples/download_nci_gdc.py                      # NCI/NIH 25K 癌症存活
```

</details>

<details>
<summary><b>小型 UCI 数据集</b></summary>

```bash
python3 examples/download_real_data.py heart    # 297 行
python3 examples/download_real_data.py breast   # 569 行
python3 examples/download_real_data.py pima     # 768 行
```

</details>

<details>
<summary><b>其他内置数据集（已预置在 examples/ 下）</b></summary>

以下数据集已随仓库提供，无需额外下载：
- `chronic_kidney_disease.csv` — UCI 慢性肾病 (400 行)
- `support2.csv` — Vanderbilt SUPPORT2 ICU 预后 (9K 行)
- `diabetes_130_readmission.csv` — UCI 糖尿病再入院精简版
- `covid19_hospitalization.csv` — COVID-19 住院预测

</details>

所有数据均来自官方机构（CDC / UCI / NCI-NIH / Vanderbilt），无需注册，一键下载。总计 526K 行。

---

## 静态分析规则 R001-R020

<details>
<summary><b>完整规则表（点击展开）</b></summary>

| 类别 | 规则 | 严重度 |
|------|------|--------|
| **数据泄漏** | R001 fit-before-split, R002 scaler-on-test, R003 SMOTE-on-test, R005 threshold-on-test, R006 feature-selection-full, R007 target-as-feature, R017 early-stop-on-test, R020 global-clean-before-split | ERROR |
| **划分问题** | R004 split-without-group, R008 temporal-shuffle, R015 small-test-set | WARNING |
| **交叉验证** | R011 CV-internal-SMOTE, R012 accuracy-on-imbalanced | ERROR/WARNING |
| **评估误用** | R010 train-metric-as-final, R013 hardcoded-threshold | WARNING |
| **预处理** | R014 LabelEncoder-on-features, R018 scaling-before-trees | WARNING/INFO |
| **可复现性** | R016 no-random-state | INFO |
| **统计严谨性** | R009 no-CI, R019 multiple-comparison | INFO |

</details>

---

## 项目结构

```
scripts/              门控脚本、训练、编排器
tests/                pytest 测试（4000+）
examples/             数据集下载器 + 参考实现 (medical_ml_demo)
experiments/          E2E 基准实验
references/           JSON 模板、知识库、标准
docs/                 架构文档
plugin/               Plugin Lint（R001-R020）
.github/workflows/    CI/CD 流水线
```

<details>
<summary><b>关键参考文件</b></summary>

| 文件 | 用途 |
|------|------|
| `references/mlgg-standard-specification.json` | 完整 33 门标准定义 |
| `references/missingness-policy.example.json` | 分层缺失策略 v2.0（9 篇文献引用） |
| `references/project-structure-convention.md` | 标准化 00-09 目录规范 |
| `references/literature-knowledge-base.json` | 58 条文献知识库 |
| `references/error-knowledge-base.json` | 99 条错误诊断知识库 |
| `references/tripod-ai-official-checklist.json` | TRIPOD+AI 2024 可机器验证清单 |

</details>

---

## 文献基础

MLGG 的每一个方法论决策都有同行评审文献支撑。以下按流程阶段列出核心引用和具体对应关系。

### Phase 1: 样本量与队列定义

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| 最小样本量三准则（收缩因子 ≥ 0.9、R² optimism ≤ 0.05、风险精度） | Riley RD, et al. *Minimum sample size for developing a multivariable prediction model: PART II.* **Statistics in Medicine.** 2019;38(7):1276-1296. [doi:10.1002/sim.7992](https://doi.org/10.1002/sim.7992) | `riley_sample_size()` in `cohort_definition_gate.py` |
| 样本量计算实操教程 | Riley RD, et al. *Calculating the sample size required for developing a clinical prediction model.* **BMJ.** 2020;368:m441. [doi:10.1136/bmj.m441](https://doi.org/10.1136/bmj.m441) | `cohort_definition_gate.py` 报告绑定准则 |
| EPV ≥ 10 经典规则（已知局限性） | Peduzzi P, et al. *A simulation study of the number of events per variable in logistic regression analysis.* **J Clin Epidemiol.** 1996;49(12):1373-1379. | 作为后备检查保留，Riley 三准则优先 |
| 队列排除逻辑（结局结构性不可能记录） | TRIPOD+AI 2024, Item 4a — Study participants | `cohort_definition_gate.py` + MLGG-C01 |

### Phase 2: 数据划分

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| 患者级划分（同一患者不跨 split） | Steyerberg EW. *Clinical Prediction Models.* 2nd ed. **Springer**; 2019. Ch. 5. | `split_data.py` MLGG-S01 |
| 时序划分（测试集时间晚于训练集） | Futoma J, et al. *The myth of generalisability in clinical research.* **Lancet Digit Health.** 2020;2(9):e489. | `split_data.py` MLGG-S02 |
| 横截面数据 stratified grouped random split | Harrell FE. *Regression Modeling Strategies.* 2nd ed. **Springer**; 2015. Ch. 5. | `split_data.py --cross-sectional` |

### Phase 3: 预处理

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| 所有 fit() 仅在训练集 | Kaufman S, et al. *Leakage in data mining: formulation, detection, and avoidance.* **ACM TKDD.** 2012;6(4):1-21. | MLGG-P01/P03/P04 |
| 缺失值按机制分层（非固定阈值丢弃） | Madley-Dowd P, et al. *The proportion of missing data should not be used to guide decisions on multiple imputation.* **J Clin Epidemiol.** 2019;110:63-73. [doi:10.1016/j.jclinepi.2019.02.016](https://doi.org/10.1016/j.jclinepi.2019.02.016) | MLGG-P06, 4 层缺失策略 |
| 多重插补指南 | Sterne JAC, et al. *Multiple imputation for missing data in epidemiological and clinical research.* **BMJ.** 2009;338:b2393. [doi:10.1136/bmj.b2393](https://doi.org/10.1136/bmj.b2393) | `missingness_policy_gate.py` |
| 缺失指示变量方法 | Groenwold RHH, et al. *Missing covariate data in clinical research: when and when not to use the missing-indicator method.* **CMAJ.** 2012;184(11):1265-1269. | 缺失 indicator 列策略 |
| SMOTE 损害校准——慎用 | van den Goorbergh RWM, et al. *The harm of class imbalance corrections for risk prediction models.* **JAMIA.** 2022;29(9):1525-1534. [doi:10.1093/jamia/ocac093](https://doi.org/10.1093/jamia/ocac093) | MLGG-P02, 默认不用 SMOTE |
| 名义 → OneHot，有序 → OrdinalEncoder | TRIPOD+AI 2024, Item 7a — Handling of predictors | MLGG-P05, `encode_categorical_features()` |

### Phase 4: 特征筛选

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| Elastic Net 正则化 | Zou H, Hastie T. *Regularization and variable selection via the elastic net.* **JRSS-B.** 2005;67(2):301-320. | `train_select_evaluate.py` α/λ 联合 CV |
| 稳定性选择（有限样本误选控制） | Meinshausen N, Buhlmann P. *Stability selection.* **JRSS-B.** 2010;72(4):417-473. [doi:10.1111/j.1467-9868.2010.00740.x](https://doi.org/10.1111/j.1467-9868.2010.00740.x) | 100 次子采样，阈值 0.6 |
| Group LASSO（OneHot dummies 分组选择） | Yuan M, Lin Y. *Model selection and estimation in regression with grouped variables.* **JRSS-B.** 2006;68(1):49-67. | 特征按原始变量分组选择/丢弃 |
| 废弃单因素筛选 | Heinze G, et al. *Variable selection — a review and recommendations for the practicing statistician.* **Biometrical Journal.** 2018;60(3):431-449. [doi:10.1002/bimj.201700067](https://doi.org/10.1002/bimj.201700067) | MLGG-F04, 单因素只做诊断不做选择 |
| 首选临床先验 + 惩罚收缩 | Harrell FE. *Regression Modeling Strategies.* 2nd ed. **Springer**; 2015. Ch. 4. | Ridge 全量对照 |

### Phase 5: 模型训练与选择

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| 模型选择用验证集性能（非 train-test gap） | Yang Z, et al. *Toward understanding generalization in discrete search spaces.* **KDD 2023.** | MLGG-M04, `--selection-data=valid` |
| Bootstrap optimism correction 内部验证 | Steyerberg EW. *Clinical Prediction Models.* 2nd ed. **Springer**; 2019. Ch. 17. | Phase 5 内建 |
| 比较 ≥3 个模型族 | TRIPOD+AI 2024, Item 7b — Model building procedures | MLGG-M03 |
| 阈值选择（Youden's J） | Fluss R, et al. *Estimation of the Youden Index and its associated cutoff point.* **Biometrical Journal.** 2005;47(4):458-472. | MLGG-M02, 验证集上选择 |

### Phase 6: 评估与校准

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| 校准三件套（截距→0，斜率→1，O:E→1） | Van Calster B, et al. *Calibration: the Achilles heel of predictive analytics.* **BMC Medicine.** 2019;17:230. [doi:10.1186/s12916-019-1466-7](https://doi.org/10.1186/s12916-019-1466-7) | `calibration_metrics()` in `_gate_utils.py` |
| 校准层级（weak → moderate → strong） | Van Calster B, et al. *A calibration hierarchy for risk models was defined.* **J Clin Epidemiol.** 2016;74:167-176. [doi:10.1016/j.jclinepi.2015.12.005](https://doi.org/10.1016/j.jclinepi.2015.12.005) | Hosmer-Lemeshow 检验 (moderate) + 分 bin 校准 |
| MCC 优于 F1（不平衡数据） | Chicco D, Jurman G. *The advantages of the Matthews correlation coefficient over F1 score and accuracy.* **BMC Genomics.** 2020;21:6. [doi:10.1186/s12864-019-6413-7](https://doi.org/10.1186/s12864-019-6413-7) | MLGG-E02, 完整指标面板必含 MCC |
| 似然比 LR+/LR- 用于临床决策 | Deeks JJ, Altman DG. *Diagnostic tests 4: likelihood ratios.* **BMJ.** 2004;329:168-169. | MLGG-E02, LR+ 和 LR- 为必报指标 |
| Decision Curve Analysis (DCA) | Vickers AJ, Elkin EB. *Decision curve analysis: a novel method for evaluating prediction models.* **Medical Decision Making.** 2006;26(6):565-574. [doi:10.1177/0272989X06295361](https://doi.org/10.1177/0272989X06295361) | `calibration_dca_gate.py` |
| Bootstrap CI ≥ 1000 次 | Efron B, Tibshirani RJ. *An Introduction to the Bootstrap.* **Chapman & Hall**; 1993. | MLGG-E01, 所有主要指标 |
| Brier Skill Score（相对基线改善） | Steyerberg EW, et al. *Assessing the performance of prediction models.* **Epidemiology.** 2010;21(1):128-138. | `calibration_metrics()` BSS 计算 |
| 性能评估 5 域框架（区分度/校准/整体/分类/临床效用） | Van Calster B, et al. *Evaluation of performance measures in predictive AI models to support medical decisions.* **Lancet Digital Health.** 2025. [doi:10.1016/j.landig.2025.100916](https://doi.org/10.1016/j.landig.2025.100916) | 框架覆盖全部 5 域 |
| NRI / IDI 重分类改善 | Pencina MJ, et al. *Evaluating the added predictive ability of a new marker.* **Statistics in Medicine.** 2008;27(2):157-172. [doi:10.1002/sim.2929](https://doi.org/10.1002/sim.2929) | `compute_nri_idi()` in `_gate_utils.py` |
| class_weight="balanced" 需事后校准 | Platt JC. *Probabilistic outputs for SVMs.* In: *Advances in Large Margin Classifiers*. MIT Press; 2000:61-74. | MLGG-E05, Platt scaling / isotonic |

### Phase 7: 可解释性

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| SHAP 理论基础 | Lundberg SM, Lee SI. *A unified approach to interpreting model predictions.* **NeurIPS 2017.** [arXiv:1705.07874](https://arxiv.org/abs/1705.07874) | `shap_interpretability_gate.py` |
| TreeSHAP 精确算法 | Lundberg SM, et al. *From local explanations to global understanding with explainable AI for trees.* **Nature Machine Intelligence.** 2020;2:56-67. [doi:10.1038/s42256-019-0138-9](https://doi.org/10.1038/s42256-019-0138-9) | TreeExplainer for RF/XGB/CatBoost/LGBM |
| SHAP 比例归一化跨模型集成 | Ponce-Bobadilla AV, et al. *Practical guide to SHAP analysis: Explaining supervised ML model predictions in drug development.* **Clinical and Translational Science.** 2024;17(11):e70056. [PMC11513550](https://pmc.ncbi.nlm.nih.gov/articles/PMC11513550/) | L1 归一化 → 等权平均 |
| 多模型平均消除归纳偏差 | Breiman L. *Statistical modeling: the two cultures.* **Statistical Science.** 2001;16(3):199-231. | Rashomon 效应，多族 SHAP 集成 |
| 多准则排名聚合 | Emond EJ, Mason DW. *A new rank correlation coefficient with application to the consensus ranking problem.* **J Multi-Criteria Decision Analysis.** 2002;11(1):17-28. | Kendall tau + Top-N Jaccard |

### Phase 8: 公平性

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| 亚组性能差异报告 | TRIPOD+AI 2024, Item 16b — Subgroup analyses | MLGG-Q01 |
| 小亚组不可靠标记（n < 200） | Steyerberg EW. *Clinical Prediction Models.* 2nd ed. 2019. Ch. 25 (external validation sample size). | MLGG-Q02 |

### Phase 9: 报告标准

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| TRIPOD+AI 2024 清单（27 项） | Collins GS, et al. *TRIPOD+AI statement: updated guidance for reporting clinical prediction models.* **BMJ.** 2024;385:e078378. [doi:10.1136/bmj-2023-078378](https://doi.org/10.1136/bmj-2023-078378) | `reporting_bias_gate.py`, `publication_gate.py` |
| PROBAST+AI 2025 偏倚风险评估（4 域 16/18 信号问题） | Moons KGM, et al. *PROBAST+AI: an updated quality, risk of bias, and applicability assessment tool.* **BMJ.** 2025;388:e082505. [doi:10.1136/bmj-2024-082505](https://doi.org/10.1136/bmj-2024-082505) | `self_critique_gate.py` 12 维评分 |
| STARD-AI 诊断准确性研究报告 | Defined in Sounderajah V, et al. *Developing specific reporting guidelines for diagnostic accuracy studies assessing AI interventions.* **Nature Medicine.** 2020;26:807-808. | `reporting_bias_gate.py` 清单检查 |

### 安全与可复现性

| 方法论决策 | 文献来源 | MLGG 实现 |
|-----------|---------|-----------|
| 数据泄漏系统分类 | Kapoor S, Narayanan A. *Leakage and the reproducibility crisis in machine-learning-based science.* **Patterns.** 2023;4(9):100804. [doi:10.1016/j.patter.2023.100804](https://doi.org/10.1016/j.patter.2023.100804) | 33 道 gate 全覆盖 |
| 学习曲线评估模型收敛 | Figueroa RL, et al. *Predicting sample size required for classification performance.* **BMC Med Inform Decis Mak.** 2012;12:8. [doi:10.1186/1472-6947-12-8](https://doi.org/10.1186/1472-6947-12-8) | `learning_curve_data()` in `_gate_utils.py` |
| HMAC-SHA256 模型签名 | NIST FIPS 198-1 — *The Keyed-Hash Message Authentication Code.* 2008. | `_security.py` 签名验证 |

### 顶刊方法论综述（MLGG 设计理论基础）

| 文献 | 核心论点 | 与 MLGG 关系 |
|------|---------|-------------|
| Chekroud AM, et al. *Illusory generalizability of clinical prediction models.* **Science.** 2024;383(6679):164-167. [doi:10.1126/science.adg8538](https://doi.org/10.1126/science.adg8538) | ML 模型在训练试验内高准确度，但外推至其他试验等于随机。"虚幻的泛化性"。 | MLGG 要求外部验证 + 跨时间/跨机构队列 + 泛化差距门控 |
| Van Calster B, van Smeden M, Steyerberg EW, et al. *The Enemies of Reliable and Useful Clinical Prediction Models.* **Annual Review of Statistics and Its Application.** 2026;13. [doi:10.1146/annurev-statistics-042324-123749](https://doi.org/10.1146/annurev-statistics-042324-123749) | 系统总结 12 个"敌人"：样本量不足、过拟合、选择偏倚、校准忽视等。86% 已发表模型存在高偏倚风险。 | MLGG 33 道门控逐一针对这 12 个敌人设计 |
| Nature Medicine 2025 — *Clinical implementation of an AI-based prediction model for colorectal cancer surgery.* [doi:10.1038/s41591-025-03942-x](https://doi.org/10.1038/s41591-025-03942-x) | 首个 Nature Med 发表的 AI 预测模型从开发到临床实施的完整案例（AUROC 0.79，前后对照 OR 0.63）。 | MLGG 方法论流程对标此论文的开发→验证→实施路径 |
| Feng G, et al. *Twelve practical recommendations for developing and applying clinical predictive models.* **The Innovation Medicine.** 2024;2(4):100105. [doi:10.59717/j.xinn-med.2024.100105](https://doi.org/10.59717/j.xinn-med.2024.100105) | 12 条实操建议覆盖数据准备、模型开发、验证、报告。 | 与 MLGG 31 条规则高度互补，MLGG 提供机器可验证的实现 |
| Vickers AJ, et al. *Understanding algorithmic fairness for clinical prediction in terms of subgroup net benefit and health equity.* **Epidemiology.** 2025. [arXiv:2412.07879](https://arxiv.org/abs/2412.07879) | 提出用亚组净效用而非传统公平性指标（如均等化几率）评估临床 AI 公平性。 | `subgroup_dca()` 直接实现此框架 |
| Dhiman P, et al. *Peer review of prediction model studies in oncology needs improvement.* **J Clin Epidemiol.** 2025;179:111967. [doi:10.1016/j.jclinepi.2025.111967](https://doi.org/10.1016/j.jclinepi.2025.111967) | 系统分析 BMC 期刊审稿报告：中位仅 243 词，<20% 审稿人检查泛化性/局限性，校准几乎未被审查。 | MLGG 33 门控强制检查审稿人最常遗漏的 12 项 |
| Riley RD, et al. *Stability of clinical prediction models developed using statistical or machine learning methods.* **Biometrical Journal.** 2023;65(8):e2200302. [doi:10.1002/bimj.202200302](https://doi.org/10.1002/bimj.202200302) | 预测模型的预测风险不稳定性常被忽视，应通过 bootstrap 评估。 | `seed_stability_gate` + 多种子稳定性 |

---

## Claude Code 集成

MLGG 提供 Claude Code slash command `/mlgg`，激活后 Claude 切换为 Nature Methods / JAMA 级别审稿人，引导用户完成 9-Phase 工作流。

```
# 在 Claude Code 终端中输入：
/mlgg
```

Skill 定义文件：`~/.claude/commands/mlgg.md`，包含全部 31 条方法论规则及其严重度和文献引用。

---

## CI/CD

| 流水线 | 触发条件 | 范围 |
|--------|---------|------|
| Smoke | Push / PR | 核心门控烟雾测试 |
| Full | 每夜 | 全部 4000+ 测试 |
| Extended | 每周 | 全数据集 E2E 基准 |
| Security | 多 Python 版本 | 依赖审计 + 安全测试 |

---

## 许可证、知识产权与使用条款

### 许可证

**PolyForm Noncommercial License 1.0.0** — 详见 [LICENSE](./LICENSE) 文件。

### 禁止事项（Prohibited Uses）

以下行为被**明确禁止**，违反者将被视为侵犯知识产权：

1. **禁止商业用途**：不得将本项目的代码、方法论、门控逻辑、评分体系用于任何商业产品、SaaS 服务、付费咨询、商业培训或任何直接/间接获取经济利益的活动。
2. **禁止方法论抄袭**：不得在学术论文中未经引用而复制、改写或实质性借鉴本项目的方法论体系，包括但不限于：
   - 33 道门控 DAG 架构及其分层设计
   - 12 维量化评分体系及权重分配
   - 多模型 SHAP 比例归一化集成方法
   - Riley 三准则 + Van Calster 校准三件套 + NRI/IDI 的组合评估框架
   - 9-Phase 工作流及各阶段方法论规则（MLGG-C01 至 MLGG-Q02）
   - 分类变量自动检测编码 + 横截面数据支持的技术实现
3. **禁止闭源衍生**：不得基于本项目创建闭源衍生作品。所有衍生作品必须以相同或更严格的非商业许可证开源。
4. **禁止去除归属**：不得移除、隐藏或篡改代码中的版权声明、许可证文件、作者信息或本 README 中的引用要求。

### 允许事项（Permitted Uses）

| 用途 | 是否允许 | 条件 |
|------|:--------:|------|
| 个人学习与研究 | **允许** | 无需授权 |
| 学术论文中使用 MLGG 进行模型验证 | **允许** | **必须引用**（见下方格式） |
| 教学课堂演示 | **允许** | 注明来源 |
| 开源非商业衍生项目 | **允许** | 相同许可证 + 引用 |
| **Claude Code `/mlgg` Skill 公开使用** | **允许** | 这是唯一授权的公开分发渠道 |
| 商业用途 | **禁止** | 需单独商业授权，联系作者 |
| 未引用的方法论复制 | **禁止** | 视为学术不端 |

### 学术引用（必须）

在任何学术出版物中使用 MLGG 框架、方法论、或基于 MLGG 产生的结果时，**必须**引用以下内容：

```bibtex
@software{mlgg2026,
  title     = {ML Leakage Guard (MLGG): Publication-Grade Integrity Standard 
               for Medical Prediction Models},
  author    = {Weng, Can},
  year      = {2026},
  version   = {1.0},
  url       = {https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard},
  note      = {33 fail-closed audit gates, 9-phase workflow, 
               TRIPOD+AI 2024 / PROBAST+AI 2025 compliant}
}
```

**论文正文中的引用格式**：

> 模型验证使用 ML Leakage Guard (MLGG) v1.0 标准进行 [引用]，通过全部 33 道门控审计，达到 L3-Publication-Grade 合规等级。

**部分使用时**也必须注明：

> 数据划分和评估方法参考 MLGG 标准 [引用] 中的 Phase 2 (MLGG-S01/S02) 和 Phase 6 (MLGG-E01/E02) 规范。

### `/mlgg` Skill 公开使用声明

Claude Code `/mlgg` slash command（定义在 `~/.claude/commands/mlgg.md`）是**唯一授权的公开使用渠道**。用户可以通过此 Skill 获取 MLGG 方法论指导，但不得将 Skill 输出的内容未经引用地用于学术发表。

### 侵权与执行

- 发现未引用的方法论抄袭将向相关期刊编辑部举报学术不端
- 发现商业使用将依据 PolyForm Noncommercial License 条款追究法律责任
- 社区成员发现侵权行为可通过 GitHub Issues 报告

---

<a name="english-version"></a>
## English Version

> This README is written in Chinese as the primary language. All code, commands, and file structures are language-neutral.

### What is MLGG?

**ML Leakage Guard (MLGG)** is a publication-grade integrity standard for medical binary classification models. It provides:

- **33 fail-closed audit gates** organized in a 9-layer DAG, covering data leakage, interpretability, fairness, sample size, calibration, robustness, TRIPOD+AI 2024, and PROBAST+AI 2025
- **9-phase guided workflow**: Data Understanding → Splitting → Preprocessing → Feature Selection → Modeling → Evaluation → **Interpretability (Multi-model SHAP)** → Fairness → Reporting
- **Multi-model SHAP engine**: Proportional-normalized ensemble feature importance across RF/XGB/CatBoost/LightGBM/LR, with Kendall tau agreement testing and 4 publication-grade CSV tables
- **12-dimension scoring** (0-100): Data Integrity, Leakage Prevention, Pipeline Isolation, Model Selection, Statistical Validity, Generalization, Clinical Completeness, Reporting Standards, Reproducibility, Security, Fairness, Sample Size
- **3 conformance levels**: L1 (12 gates, leakage-audited) / L2 (25 gates, statistically valid) / L3 (all 33 gates, publication-grade)
- **14 real medical datasets** from CDC / UCI / NCI / Vanderbilt (526K rows total)
- **31 methodology rules** grounded in 18+ peer-reviewed references (Steyerberg 2019, Harrell 2015, Madley-Dowd 2019, Van Calster 2019, Riley 2019, Collins 2024, Lundberg 2017/2020, etc.)

### Why MLGG?

Data leakage in medical ML papers is more common than expected. MLGG systematically prevents issues like preprocessing before splitting, deceased patients in readmission cohorts, ordinal encoding of nominal variables, and AUROC-only reporting that masks MCC near zero.

### Reference Implementation

The `examples/medical_ml_demo/` directory contains a complete 9-phase analysis on UCI Diabetes 130-US Hospitals (99,330 encounters). Key finding: **AUROC 0.647 masks MCC 0.12 and LR+ 1.6** — the model is well-calibrated (slope 1.06, ECE 0.009) but lacks discrimination for clinical decisions. This honest conclusion is consistent with the literature (published AUROC for 30-day readmission: 0.60-0.72).

### Section Navigation

| Section | Jump to |
|---------|---------|
| Why MLGG? | [为什么需要 MLGG？](#为什么需要-mlgg) |
| System capabilities | [系统能力总览](#系统能力总览) |
| Quick start | [快速开始](#快速开始) |
| 9-Phase workflow | [9-Phase 工作流](#9-phase-工作流) |
| 32 audit gates (DAG) | [32 道安全门控](#32-道安全门控-gate-dag) |
| 31 methodology rules | [31 条方法论规则](#31-条方法论规则) |
| Reference implementation | [参考实现](#参考实现30-天再入院预测) |
| Installation | [安装指南](#安装指南) |
| Commands | [命令参考](#命令参考) |
| Datasets (14) | [14 个医学数据集](#14-个医学数据集) |
| Lint rules (R001-R020) | [静态分析规则](#静态分析规则-r001-r020) |
| Project structure | [项目结构](#项目结构) |
| Literature foundation | [文献基础](#文献基础) |
| Claude Code `/mlgg` | [Claude Code 集成](#claude-code-集成) |
| CI/CD | [CI/CD](#cicd) |
| License, IP & terms | [许可证、知识产权与使用条款](#许可证知识产权与使用条款) |

### License & Intellectual Property

**PolyForm Noncommercial License 1.0.0.** Commercial use is **strictly prohibited**. Academic use **requires citation** (see BibTeX above). Uncited reproduction of MLGG methodology in publications constitutes academic misconduct and will be reported to journal editors. The Claude Code `/mlgg` Skill is the **only authorized public distribution channel**. All derivative works must be open-sourced under the same or stricter noncommercial license. See the Chinese section above for full terms.
