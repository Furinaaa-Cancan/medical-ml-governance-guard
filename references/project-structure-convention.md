# MLGG Project Directory Structure Convention

> 标准化的项目目录结构，确保分析流程可读、可复现、可审计。
> 所有 MLGG 新建项目应遵循此结构。

## 目录结构

```
<project_root>/
├── config.py                      # 全局唯一硬编码来源（路径、种子、列名、超参搜索空间）
│
├── 00_database/
│   ├── raw/                       # 原始数据（只读，不可修改）
│   └── docs/                      # 数据字典、变量说明、伦理批件
│
├── 01_exploration/
│   ├── scripts/                   # 描述统计、EPV检查、缺失分析、正类比例
│   └── results/                   # 描述统计表、缺失热力图等
│
├── 02_splitting/
│   ├── scripts/                   # 患者级 + 时序划分
│   └── results/                   # train.csv, valid.csv, test.csv
│
├── 03_preprocessing/
│   ├── scripts/                   # 缺失填补、编码、标准化、Pipeline 构建
│   └── results/                   # pipeline.pkl, 编码映射等
│
├── 04_feature_selection/
│   ├── scripts/                   # 单因素分析、LASSO、共线性检查、VIF
│   └── results/                   # 筛选后特征列表、单因素结果表
│
├── 05_modeling/
│   ├── scripts/                   # 多模型训练、超参调优、阈值选择
│   └── results/                   # 调参日志、最优超参、验证集结果
│
├── 06_evaluation/
│   ├── scripts/                   # 指标面板、Bootstrap CI、校准曲线、DCA
│   └── results/                   # 评估报告、ROC/PRC 数据
│
├── 07_interpretability/
│   ├── scripts/                   # SHAP、LIME、PDP、特征重要性、个案解释
│   └── results/                   # SHAP summary/force/dependence 图数据
│
├── 08_fairness/
│   ├── scripts/                   # 亚组分析（性别/年龄/种族）、公平性指标
│   └── results/                   # 亚组指标表、差异检验结果
│
├── 09_reporting/
│   ├── scripts/                   # TRIPOD+AI 清单生成、最终图表排版
│   └── results/                   # 清单文件、审稿回复模板
│
└── outputs/                       # 跨阶段汇总 — 论文直接引用
    ├── figures/                   # 最终图（ROC、校准、SHAP、DCA 等）
    ├── tables/                    # 最终表（Table 1、指标汇总等）
    └── models/                    # 最终模型文件（含签名）
```

## 规则

### 必须遵守

1. **`00_database/raw/` 只读** — 原始数据在整个项目生命周期内不可修改、不可覆盖。
2. **每个阶段文件夹必须包含 `scripts/` 和 `results/`** 两个子目录，代码与产物分离。
3. **`scripts/` 只放 `.py` 脚本** — 不混入数据文件或输出产物。
4. **`results/` 存该阶段中间产物** — csv, pkl, png, json 等。
5. **`outputs/` 是最终产物汇总** — 论文图表和最终模型从此目录引用。
6. **`config.py` 集中管理所有配置** — 路径、随机种子、列名定义、划分比例、Bootstrap 次数等，各阶段脚本 `import config` 使用，禁止硬编码散落。
7. **阶段间数据传递** — 通过上一阶段 `results/` 的产物文件，不跨阶段直接引用中间变量。

### 建议遵守

8. 每个 `scripts/` 目录下的主脚本命名与阶段文件夹一致（如 `01_exploration/scripts/explore.py`）。
9. 长流程脚本拆分为多个子脚本时，用数字前缀排序（如 `01_univariate.py`, `02_lasso.py`）。
10. `results/` 中的关键输出文件附带生成时间戳或 git commit hash，保障可溯源。

## MLGG Phase 映射

| 目录 | MLGG Phase | 关键检查点 |
|------|-----------|-----------|
| 01_exploration | Phase 1: Data Understanding | EPV ≥ 10, 样本量充足 |
| 02_splitting | Phase 2: Data Splitting | 无患者重叠, 正类比例一致 |
| 03_preprocessing | Phase 3: Preprocessing | fit() 仅在训练集 |
| 04_feature_selection | Phase 3 延伸 | 特征选择仅在训练集 (MLGG-F03) |
| 05_modeling | Phase 4: Model Training | 测试集未参与任何选择 |
| 06_evaluation | Phase 5: Evaluation | 单次最终测试集评估 |
| 07_interpretability | Phase 5 延伸 | 解释性分析基于训练集 SHAP |
| 08_fairness | Phase 6 前置 | 亚组指标差异 (MLGG-Q01) |
| 09_reporting | Phase 6: Reporting | TRIPOD+AI 合规 (MLGG-T01) |
