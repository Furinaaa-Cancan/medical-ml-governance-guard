# Examples

本目录包含三类内容：

## 1. 医学数据集 (`*.csv`, 16 个)

| 数据集 | 行数 | 来源 | 用途 |
|--------|------|------|------|
| heart_disease.csv | 297 | UCI Cleveland | 快速验证 |
| breast_cancer.csv | 569 | UCI WDBC | 快速验证 |
| pima_diabetes.csv | 768 | Kaggle | 快速验证 |
| nhanes_diabetes.csv | 16K | CDC NHANES | Codebook RAG 验证 |
| brfss2022_diabetes.csv | 100K | CDC BRFSS | 大规模横截面 |
| diabetes_130_readmission.csv | 101K | UCI | 再入院预测 |
| sepsis_survival.csv | 129K | UCI | ICU 脓毒症 |
| ... | | | |

## 2. 数据下载器 (`download_*.py`, 4 个)

```bash
python3 examples/download_real_data.py heart          # UCI 数据集
python3 examples/download_cdc_data.py brfss           # CDC BRFSS/NHIS/COVID
python3 examples/download_nhanes.py --cycles both     # NHANES 糖尿病队列
python3 examples/download_nci_gdc.py                  # NCI 癌症生存
```

## 3. 项目模板 (2 个完整项目)

| 目录 | 用途 |
|------|------|
| `demo_diabetes130/` | **参考实现** — UCI Diabetes 130 数据集的完整 9 阶段流程 |
| `template/` | **可复用脚手架** — 空的 9 阶段项目结构，`cp -r` 后填入自己的数据 |
