# ML Leakage Guard (MLGG) — 医学预测模型完整性标准

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue.svg)](https://polyformproject.org/licenses/noncommercial/1.0.0/)
[![Tests](https://img.shields.io/badge/tests-3400%2B%20passed-brightgreen)]()
[![Gate Coverage](https://img.shields.io/badge/gate%20coverage-%E2%89%A586%25-blue)]()
[![MLGG Standard v1.0](https://img.shields.io/badge/MLGG%20Standard-v1.0-orange)]()
[![TRIPOD+AI 2024](https://img.shields.io/badge/TRIPOD%2BAI-2024-blue)](https://doi.org/10.1136/bmj-2023-078378)
[![PROBAST+AI 2025](https://img.shields.io/badge/PROBAST%2BAI-2025-blue)](https://doi.org/10.7326/M18-1376)

面向医学二分类预测的发布级防泄漏工作流。31 道 fail-closed 门控，14 个真实医学数据集（526K 行），12 维量化评分，可机器校验的合规证书。

> 医学 ML 数据泄漏导致性能虚高和不安全的临床决策。MLGG 提供可机器验证的标准来预防、检测和报告这些问题——从原始数据到 TRIPOD+AI 合规发表。

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
- [31 道安全门控 (Gate DAG)](#31-道安全门控-gate-dag)
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
- [许可证与引用](#许可证与引用)
- [English Version](#english-version)

---

## 系统能力总览

```
原始数据 → 31 道审计门控 → 合规证书 → 可发表报告
```

| 模块 | 说明 | 规模 |
|------|------|------|
| **31 道安全门控** | fail-closed DAG 架构，覆盖泄漏检测 / 公平性 / 样本量 / 校准 / 鲁棒性 / TRIPOD+AI / PROBAST+AI | 31 个独立 CLI 脚本 |
| **12 维量化评分** (0-100) | 数据完整性 / 泄漏防护 / 管线隔离 / 模型选择 / 统计有效性 / 泛化证据 / 临床完整性 / 报告标准 / 可复现性 / 安全性 / 公平性 / 样本量 | ≥90 顶刊级 |
| **3 级合规** | L1（12 门，泄漏审计）/ L2（25 门，统计有效）/ L3（全部 31 门，发布级） | 渐进认证 |
| **20 个模型族** | LR(L1/L2/ElasticNet) / SVM / RF / XGBoost / CatBoost / LightGBM / KNN / MLP / TabPFN + 集成 | 自动超参搜索 |
| **14 个真实数据集** | UCI / CDC / NCI / Vanderbilt 官方数据 | 总计 526K 行 |
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
- 输出中的"快速就绪检查"**不是** 31 关发布门结论
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

<details>
<summary><b>各阶段详细说明</b></summary>

**Phase 1: 数据理解**
- 确认数据来源、采集时间、样本量、结局变量定义
- **定义合格队列 (C01)**：排除结局结构性不可能的记录（如死亡患者不能再入院）
- **定义预测时间点 (F05)**：将每个特征标记为"入院时可用"或"出院时才知道"
- 样本量检查：EPV ≥ 10（简化）或 Riley 2019 标准（严格）

**Phase 2: 数据划分**
- 按患者 ID 分组 (S01)，同一患者所有记录归入同一 split
- 时序划分 (S02)，测试集时间晚于训练集
- 无时序数据时按患者 stratified random split
- 报告正类比例时序漂移

**Phase 3: 预处理**
- 所有 fit() 仅在训练集 (P01/P03/P04)
- 编码匹配语义 (P05)：名义变量 → OneHotEncoder；有序变量 → OrdinalEncoder（需实证验证单调性）
- 缺失按机制分层 (P06)：不用固定阈值，按 MCAR/MAR/MNAR 选策略（Madley-Dowd 2019）
- SMOTE 慎用：van den Goorbergh 2022 证明 SMOTE 损害风险预测校准

**Phase 4: 特征筛选**
- 首选临床知识预指定 + 惩罚收缩（Harrell 2015）
- Elastic Net CV：α 和 λ 联合交叉验证，按原始变量分组选择/丢弃
- Stability Selection（Meinshausen 2010）：50+ 次子采样，报告误选界
- Ridge 对照：始终与全量模型比较，如选择导致 >0.005 损失则用全量
- ~~单因素筛选~~已废弃（Heinze 2018）

**Phase 5: 模型训练**
- 比较 ≥3 个模型族（LR, RF, XGBoost, LightGBM 等）
- 模型选择用 validation 性能，**不用** train-test gap（Yang et al. KDD 2023）
- Bootstrap optimism correction 作为内部验证（Steyerberg 2019）
- 阈值在验证集上用 Youden's J 或成本敏感方法选择

**Phase 6: 模型评估**
- 区分度：AUROC, AUPRC
- 分类：Sensitivity, Specificity, PPV, NPV, F1, **MCC**, Balanced Accuracy
- 临床有用性：**LR+/LR-**（似然比）, DCA 净效用
- 概率质量：Brier score, Log loss（原始 + 校准后）
- 校准三件套（Van Calster 2019）：**校准斜率**（→1.0）、**校准截距**（→0.0）、**O/E 比**（→1.0）、ECE
- class_weight="balanced" 必须事后校准（Platt scaling / isotonic）
- 多种子稳定性：≥5 seeds

**Phase 7: 可解释性**
- SHAP values（TreeExplainer / LinearExplainer）
- 跨模型 Top 特征一致性验证
- 个案解释（最高/最低风险患者）

**Phase 8: 公平性**
- 按性别、年龄、种族分组评估
- 亚组指标需 Bootstrap CI（MLGG-Q02）
- n < 200 的亚组标记为不可靠
- 讨论差异原因和缓解策略

**Phase 9: 报告**
- TRIPOD+AI 2024 清单逐项核对
- 局限性结构化讨论
- 外部验证建议
- 如 DCA 无临床效用，诚实报告

</details>

---

## 31 道安全门控 (Gate DAG)

31 道门控按 DAG（有向无环图）分 9 层执行。同层可并行，每层必须完成后才能执行下一层。全部通过才能声称 Publication-Grade (L3)。

```
Layer 0  契约验证          request_contract_gate
    ↓
Layer 1  指纹锁定          manifest_lock
    ↓
Layer 2  执行证明          execution_attestation_gate
    ↓
Layer 3  数据验证          leakage_gate | split_protocol_gate | covariate_shift_gate | reporting_bias_gate
    ↓
Layer 4  策略审计          definition_variable_guard | feature_lineage_gate | imbalance_policy_gate | missingness_policy_gate | tuning_leakage_gate
    ↓
Layer 5  模型审计          model_selection_audit_gate | feature_engineering_audit_gate | clinical_metrics_gate
    ↓
Layer 6  统计验证          calibration_dca_gate | ci_matrix_gate | distribution_generalization_gate | evaluation_quality_gate | external_validation_gate | fairness_equity_gate | generalization_gap_gate | metric_consistency_gate | permutation_significance_gate | prediction_replay_gate | robustness_gate | sample_size_gate | seed_stability_gate
    ↓
Layer 7  发布聚���          publication_gate
    ↓
Layer 8  终审              self_critique_gate | security_audit_gate
```

<details>
<summary><b>31 道门控详细说明（点击展开）</b></summary>

### Layer 0: 契约验证

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
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

### Layer 5: 模型审计（3 门并行）

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 13 | `model_selection_audit_gate.py` | 审计候选池、one-SE 回放、测试集隔离的模型选择 | `model_selection_audit_report.json` |
| 14 | `feature_engineering_audit_gate.py` | 审计特征组来源、训练集独占范围、稳定性证据 | `feature_engineering_audit_report.json` |
| 15 | `clinical_metrics_gate.py` | 验证临床指标完整性和混淆矩阵一致性 | `clinical_metrics_report.json` |

### Layer 6: 统计验证（13 门并行）

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 16 | `calibration_dca_gate.py` | 概率校准和决策曲线分析 | `calibration_dca_report.json` |
| 17 | `ci_matrix_gate.py` | 所有划分和队列的主要指标 Bootstrap CI 矩阵 | `ci_matrix_gate_report.json` |
| 18 | `distribution_generalization_gate.py` | 训练集 vs 验证集分布漂移评估和迁移准备度 | `distribution_generalization_report.json` |
| 19 | `evaluation_quality_gate.py` | 强制主要指标 CI 质量和基线改善要求 | `evaluation_quality_report.json` |
| 20 | `external_validation_gate.py` | 外部队列（跨时期/跨机构）指标验证 | `external_validation_gate_report.json` |
| 21 | `fairness_equity_gate.py` | 亚组公平性和健康公平审计 | `fairness_equity_report.json` |
| 22 | `generalization_gap_gate.py` | 训练/验证/测试的过拟合差距 fail-closed 检查 | `generalization_gap_report.json` |
| 23 | `metric_consistency_gate.py` | 从评估报告提取并验证指标一致性 | `metric_consistency_report.json` |
| 24 | `permutation_significance_gate.py` | 基于置换的伪造显著性检验 | `permutation_report.json` |
| 25 | `prediction_replay_gate.py` | 从预测轨迹回放验证指标可复现性 | `prediction_replay_report.json` |
| 26 | `robustness_gate.py` | 亚组鲁棒性分析 | `robustness_gate_report.json` |
| 27 | `sample_size_gate.py` | 样本量充分性（EPV / Riley 标准） | `sample_size_report.json` |
| 28 | `seed_stability_gate.py` | 多种子稳定性分析 | `seed_stability_report.json` |

### Layer 7: 发布聚合

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 29 | `publication_gate.py` | 聚合所有门控结果为最终发布就绪判定 | `publication_gate_report.json` |

### Layer 8: 终审

| # | 门控脚本 | 功能 | 输出报告 |
|---|---------|------|---------|
| 30 | `self_critique_gate.py` | 12 维量化评分 + 审稿人级自我批评 | `self_critique_report.json` |
| 31 | `security_audit_gate.py` | 加密模型签名 + 工件完整性 + 敏感数据保护 | `security_audit_report.json` |

### 三级合规要求

| 等级 | 名称 | 要求门控数 | strict 模式 | TRIPOD+AI 覆盖 | PROBAST ROB | 适用场景 |
|------|------|-----------|------------|---------------|------------|---------|
| **L1** | 泄漏审计 | 12 门 | 否 | — | — | 会议论文、初步报告 |
| **L2** | 统计有效 | 25 门 | 否 | ≥17/27 | low/unclear | 专业期刊（JAMIA, npj Digital Medicine） |
| **L3** | 发布级 | **全部 31 门** | **是** | ≥23/27 | **low** | Nature Medicine, Lancet, JAMA, BMJ |

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

## 参考实现：30 天再入院预测

`examples/medical_ml_demo/` 包含使用 UCI 糖尿病 130 家医院数据集（99,330 例，69,979 位患者）的完整 9-Phase 分析。

```
examples/medical_ml_demo/
├── config.py                          全局配置（队列排除、缺失策略、特征时间分类）
├── 00_database/                       原始数据（gitignored）
├── 01_exploration/scripts/            EPV、缺失分析、队列排除
├── 02_splitting/scripts/              患者级时序划分
├── 03_preprocessing/scripts/          5 类语义编码 + 分层缺失
├── 04_feature_selection/scripts/      Elastic Net CV + Stability Selection
├── 05_modeling/scripts/               4 模型族 + bootstrap optimism + 入院/出院时对比
├── 06_evaluation/scripts/             完整指标 + Platt 校准 + DCA
├── 07_interpretability/scripts/       4 模型 SHAP + 跨模型一致性
├── 08_fairness/scripts/               种族/性别/年龄亚组分析
├── 09_reporting/scripts/              TRIPOD+AI 清单 + Table 1-3 + limitations
└── outputs/tables/                    发表用表格
```

### 核心结果

| 指标 | 值 | 解读 |
|------|-----|------|
| 最优模型 | LightGBM | |
| Test AUROC (95% CI) | 0.647 (0.631–0.661) | 弱到中等区分度 |
| **MCC** | **0.122** | 接近随机（0=随机，1=完美） |
| **LR+ / LR-** | **1.60 / 0.69** | 无临床决策价值（需 LR+>5, LR-<0.2） |
| 校准斜率 | 1.06 | 良好（Platt scaling 后） |
| O/E 比 | 0.92 | 略低估 |
| ECE（校准后） | 0.009 | 优秀 |
| 入院时 AUROC | 0.606 | 仅入院特征 |
| 出院时 AUROC | 0.647 | 出院信息贡献 +0.034 |
| Stability 稳定特征 | 3/32 组 | number_inpatient, number_diagnoses, age |

**诚实结论**：AUROC 0.647 掩盖了 MCC 0.12 和 LR+ 1.6 的真相。模型概率校准良好，但区分度不足以支撑独立临床决策。这与文献一致——30 天再入院本身极难预测（文献 AUROC 0.60-0.72）。

<details>
<summary><b>开发过程中发现的问题与新增规则</b></summary>

| 问题 | 影响 | 新增规则 |
|------|------|----------|
| 死亡患者纳入队列 | AUROC 虚抬 +0.004 | MLGG-C01 |
| OrdinalEncoder 用于名义变量 | LR AUROC 损失 0.02 | MLGG-P05 |
| 60% 缺失阈值无文献 | 策略缺乏依据 | MLGG-P06 |
| composite score / gap 硬阈值选模型 | 选错模型 | MLGG-M04 |
| class_weight 扭曲概率 | ECE 0.35→0.01 | MLGG-E05 |
| 66% 特征是出院时信息 | 预测时间点未声明 | MLGG-F05 |
| 药物列假设有序 | 无单调关系验证 | MLGG-P05 |
| Meinshausen 误选界公式错误 | E[V]=0（虚假）→ E[V]=0.66 | 代码修复 |
| 只报 ECE 不报校准三件套 | 缺 Van Calster 核心指标 | MLGG-E02 |
| 只报 AUROC/F1 不报 MCC/LR+/LR- | AUROC 掩盖分类无能 | MLGG-E02 |

**每条规则都来自实际踩坑，不是纸上谈兵。**

</details>

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

**环境要求**：Python 3.10+，`numpy`，`pandas`，`scikit-learn`，`scipy`，`joblib`。可选：`xgboost`，`catboost`，`lightgbm`，`tabpfn`，`optuna`。

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
| `references/mlgg-standard-specification.json` | 完整 31 门标准定义 |
| `references/missingness-policy.example.json` | 分层缺失策略 v2.0（9 篇文献引用） |
| `references/project-structure-convention.md` | 标准化 00-09 目录规范 |
| `references/literature-knowledge-base.json` | 58 条文献知识库 |
| `references/error-knowledge-base.json` | 99 条错误诊断知识库 |
| `references/tripod-ai-official-checklist.json` | TRIPOD+AI 2024 可机器验证清单 |

</details>

---

## 文献基础

MLGG 每条规则都有同行评审文献支撑：

| 主题 | 关键文献 |
|------|----------|
| 缺失策略 | Madley-Dowd 2019 (J Clin Epidemiol), Sperrin 2020, Groenwold 2012 (CMAJ), Jakobsen 2017, Sterne 2009 (BMJ) |
| 模型选择 | Yang et al. KDD 2023 — validation performance 优于 generalization gap |
| 内部验证 | Steyerberg 2019 教科书, Harrell 2015 教科书 — bootstrap optimism correction |
| 特征筛选 | Zou & Hastie 2005 (Elastic Net), Meinshausen & Buhlmann 2010 (Stability Selection), Heinze 2018, Yuan & Lin 2006 (Group LASSO) |
| 样本量 | Riley 2019/2020 — 现代标准取代 EPV ≥ 10 |
| 校准 | Van Calster 2019 (BMC Medicine) — slope, intercept, O/E ratio |
| 指标面板 | Chicco & Jurman 2020 — MCC 优于 F1（不平衡数据） |
| 报告标准 | Collins et al. 2024 — TRIPOD+AI statement (BMJ) |
| 过采样危害 | van den Goorbergh 2022 (JAMIA) — SMOTE 损害校准 |

---

## Claude Code 集成

MLGG 提供 Claude Code slash command `/mlgg`，激活后 Claude 切换为 Nature Methods / JAMA 级别审稿人，引导用户完成 9-Phase 工作流。

```
# 在 Claude Code 终端中输入：
/mlgg
```

Skill 定义文件：`~/.claude/commands/mlgg.md`，包含全部 31 条规则及其严重度和文献引用。

---

## CI/CD

| 流水线 | 触发条件 | 范围 |
|--------|---------|------|
| Smoke | Push / PR | 核心门控烟雾测试 |
| Full | 每夜 | 全部 4000+ 测试 |
| Extended | 每周 | 全数据集 E2E 基准 |
| Security | 多 Python 版本 | 依赖审计 + 安全测试 |

---

## 许可证与引用

**许可证**：PolyForm Noncommercial License 1.0.0 — 研究和教育免费使用，商业用途需单独授权。

**引用**：

```
Machine Learning Leakage Guard (MLGG) Standard v1.0.
ml-leakage-guard project, 2026.
https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard
```

论文中引用时请注明 MLGG 版本号和达到的合规等级（如 "MLGG v1.0 L3-Publication-Grade"）。

---

<a name="english-version"></a>
## English Version

> This README is written in Chinese as the primary language. All code, commands, and file structures are language-neutral.

### What is MLGG?

**ML Leakage Guard (MLGG)** is a publication-grade integrity standard for medical binary classification models. It provides:

- **31 fail-closed audit gates** organized in a 9-layer DAG, covering data leakage, fairness, sample size, calibration, robustness, TRIPOD+AI 2024, and PROBAST+AI 2025
- **9-phase guided workflow**: Data Understanding → Splitting → Preprocessing → Feature Selection → Modeling → Evaluation → Interpretability → Fairness → Reporting
- **12-dimension scoring** (0-100): Data Integrity, Leakage Prevention, Pipeline Isolation, Model Selection, Statistical Validity, Generalization, Clinical Completeness, Reporting Standards, Reproducibility, Security, Fairness, Sample Size
- **3 conformance levels**: L1 (12 gates, leakage-audited) / L2 (25 gates, statistically valid) / L3 (all 31 gates, publication-grade)
- **14 real medical datasets** from CDC / UCI / NCI / Vanderbilt (526K rows total)
- **31 methodology rules** grounded in 15+ peer-reviewed references (Steyerberg 2019, Harrell 2015, Madley-Dowd 2019, Van Calster 2019, Riley 2019, Collins 2024, etc.)

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
| 31 audit gates (DAG) | [31 道安全门控](#31-道安全门控-gate-dag) |
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
| License & citation | [许可证与引用](#许可证与引用) |
