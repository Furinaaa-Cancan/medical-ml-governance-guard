"""
01_exploration/scripts/explore.py
=================================
Phase 1: Data Understanding
- 基本信息、样本量、患者数
- 目标变量定义与正类比例
- 缺失值分析
- 特征概览
- EPV 检查 (MLGG-Z01)
- 数值变量描述统计
- 类别变量频率统计

输出 → 01_exploration/results/
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import config


def load_data() -> pd.DataFrame:
    """加载原始数据，排除不合格人群，创建二分类标签。"""
    df = pd.read_csv(config.RAW_DATA)
    n_raw = len(df)

    # Cohort exclusion: remove records not in target population
    mask = ~df["discharge_disposition_id"].isin(config.EXCLUDE_DISCHARGE_DISPOSITION)
    mask &= ~df["gender"].isin(config.EXCLUDE_GENDER)
    mask &= ~df["admission_type_id"].isin(config.EXCLUDE_ADMISSION_TYPE)
    df = df[mask].reset_index(drop=True)

    print(f"  Cohort exclusion: {n_raw} → {len(df)} ({n_raw - len(df)} excluded)")
    print(f"    Expired/Hospice: {(~mask).sum()} records")

    df[config.LABEL_COL] = (df[config.ORIGINAL_TARGET] == config.POSITIVE_CLASS).astype(int)
    return df


def basic_info(df: pd.DataFrame) -> pd.DataFrame:
    """基本数据集信息。"""
    info = {
        "总记录数": len(df),
        "总列数": df.shape[1],
        "唯一患者数": df[config.ID_COL].nunique(),
        "唯一 encounter 数": df[config.ENCOUNTER_COL].nunique(),
        "多次入院患者数": (df.groupby(config.ID_COL).size() > 1).sum(),
        "正类数 (readmitted <30d)": df[config.LABEL_COL].sum(),
        "负类数": (df[config.LABEL_COL] == 0).sum(),
        "正类比例": round(df[config.LABEL_COL].mean(), 4),
    }
    return pd.DataFrame(list(info.items()), columns=["指标", "值"])


def missing_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """缺失值分析（该数据集用 '?' 表示缺失）。"""
    records = []
    for col in df.columns:
        n_question = (df[col] == "?").sum()
        n_null = df[col].isnull().sum()
        n_miss = n_question + n_null
        records.append({
            "column": col,
            "n_missing": n_miss,
            "pct_missing": round(n_miss / len(df) * 100, 2),
        })
    miss_df = pd.DataFrame(records).sort_values("n_missing", ascending=False)
    miss_df = miss_df[miss_df["n_missing"] > 0].reset_index(drop=True)
    return miss_df


def epv_check(df: pd.DataFrame) -> pd.DataFrame:
    """Events Per Variable 检查 (MLGG-Z01)。"""
    exclude = set(config.DROP_COLS + [config.LABEL_COL])
    feature_cols = [c for c in df.columns if c not in exclude]
    n_events = df[config.LABEL_COL].sum()
    n_features = len(feature_cols)
    epv = n_events / n_features if n_features > 0 else 0

    epv_info = {
        "正类事件数": n_events,
        "候选特征数": n_features,
        "EPV": round(epv, 1),
        "EPV >= 10": "YES" if epv >= 10 else "NO",
    }
    return pd.DataFrame(list(epv_info.items()), columns=["指标", "值"])


def numeric_summary(df: pd.DataFrame) -> pd.DataFrame:
    """数值变量描述统计。"""
    exclude = set(config.DROP_COLS + [config.LABEL_COL])
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c not in exclude]
    return df[num_cols].describe().T.round(2)


def categorical_summary(df: pd.DataFrame) -> pd.DataFrame:
    """类别变量频率概览（每列 unique 数 + top 3 值）。"""
    exclude = set(config.DROP_COLS + [config.LABEL_COL])
    cat_cols = [c for c in df.select_dtypes(exclude=[np.number]).columns if c not in exclude]

    records = []
    for col in cat_cols:
        vc = df[col].value_counts()
        top3 = vc.head(3)
        top3_str = ", ".join([f"{v}({c})" for v, c in top3.items()])
        records.append({
            "column": col,
            "n_unique": df[col].nunique(),
            "top_3": top3_str,
        })
    return pd.DataFrame(records)


def target_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """原始目标变量分布。"""
    vc = df[config.ORIGINAL_TARGET].value_counts()
    dist = pd.DataFrame({"category": vc.index, "count": vc.values})
    dist["pct"] = (dist["count"] / dist["count"].sum() * 100).round(2)
    return dist


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("Loading data...")
    df = load_data()

    # 1. 基本信息
    info_df = basic_info(df)
    info_df.to_csv(os.path.join(results_dir, "basic_info.csv"), index=False)
    print("\n=== Basic Info ===")
    print(info_df.to_string(index=False))

    # 2. 目标变量分布
    target_df = target_distribution(df)
    target_df.to_csv(os.path.join(results_dir, "target_distribution.csv"), index=False)
    print("\n=== Target Distribution ===")
    print(target_df.to_string(index=False))

    # 3. 缺失值分析
    miss_df = missing_analysis(df)
    miss_df.to_csv(os.path.join(results_dir, "missing_analysis.csv"), index=False)
    print("\n=== Missing Values ===")
    print(miss_df.to_string(index=False))

    # 4. EPV 检查
    epv_df = epv_check(df)
    epv_df.to_csv(os.path.join(results_dir, "epv_check.csv"), index=False)
    print("\n=== EPV Check (MLGG-Z01) ===")
    print(epv_df.to_string(index=False))

    # 5. 数值变量描述统计
    num_df = numeric_summary(df)
    num_df.to_csv(os.path.join(results_dir, "numeric_summary.csv"))
    print("\n=== Numeric Summary ===")
    print(num_df.to_string())

    # 6. 类别变量概览
    cat_df = categorical_summary(df)
    cat_df.to_csv(os.path.join(results_dir, "categorical_summary.csv"), index=False)
    print("\n=== Categorical Summary ===")
    print(cat_df.to_string(index=False))

    print(f"\n✅ Phase 1 results saved to: {results_dir}")


if __name__ == "__main__":
    main()
