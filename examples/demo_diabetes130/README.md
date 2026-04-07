# Medical ML Demo — MLGG 9-Phase 参考实现

UCI 糖尿病 130 家医院数据集上的 30 天再入院预测，完整演示 MLGG 9-Phase 工作流。

## 快速开始

```bash
# 1. 下载数据
python3 run_all.py --download-only

# 2. 运行全流程（约 30-60 分钟）
python3 run_all.py

# 或逐步运行
python3 01_exploration/scripts/explore.py
python3 02_splitting/scripts/split.py
python3 03_preprocessing/scripts/preprocess.py
python3 04_feature_selection/scripts/select_features.py
python3 05_modeling/scripts/train_models.py
python3 06_evaluation/scripts/evaluate.py
python3 06_evaluation/scripts/calibrate.py
python3 07_interpretability/scripts/interpret.py
python3 08_fairness/scripts/fairness.py
python3 09_reporting/scripts/report.py
```

## 数据集

UCI Diabetes 130-US Hospitals (Strack et al. 2014)，需手动下载：

```bash
python3 run_all.py --download-only
```

或手动下载 https://archive.ics.uci.edu/ml/machine-learning-databases/00296/dataset_diabetes.zip 并解压 `diabetic_data.csv` 到 `00_database/raw/`。

## 核心结果

| 指标 | 值 |
|------|-----|
| 最优模型 | LightGBM |
| Test AUROC (95% CI) | 0.647 (0.631-0.661) |
| MCC | 0.122 |
| LR+/LR- | 1.60 / 0.69 |
| 校准斜率 | 1.06 |

详见 `outputs/tables/` 下的完整报告表格。
