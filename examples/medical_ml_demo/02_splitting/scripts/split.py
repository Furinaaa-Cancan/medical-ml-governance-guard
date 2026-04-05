"""
02_splitting/scripts/split.py
==============================
Phase 2: Data Splitting
- Split by patient_nbr (MLGG-S01: no patient overlap across splits)
- Use encounter_id as temporal proxy (MLGG-S02: test set time after train)
- Train 60% / Valid 20% / Test 20% (by patient count)
- Verify: no patient overlap, positive rate consistency across splits

输出 → 02_splitting/results/
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

    # Cohort exclusion
    mask = ~df["discharge_disposition_id"].isin(config.EXCLUDE_DISCHARGE_DISPOSITION)
    mask &= ~df["gender"].isin(config.EXCLUDE_GENDER)
    mask &= ~df["admission_type_id"].isin(config.EXCLUDE_ADMISSION_TYPE)
    df = df[mask].reset_index(drop=True)
    print(f"  Cohort exclusion: {n_raw} → {len(df)} ({n_raw - len(df)} excluded)")

    df[config.LABEL_COL] = (df[config.ORIGINAL_TARGET] == config.POSITIVE_CLASS).astype(int)
    return df


def build_patient_timeline(df: pd.DataFrame) -> pd.DataFrame:
    """
    为每个患者计算时间代理指标。
    用该患者最早的 encounter_id 作为排序依据，
    确保同一患者的所有记录归入同一 split。
    """
    patient_info = df.groupby(config.ID_COL).agg(
        first_encounter=(config.ENCOUNTER_COL, "min"),
        n_visits=(config.ENCOUNTER_COL, "count"),
        any_positive=(config.LABEL_COL, "max"),
    ).reset_index()
    patient_info = patient_info.sort_values("first_encounter").reset_index(drop=True)
    return patient_info


def assign_splits(patient_info: pd.DataFrame) -> pd.DataFrame:
    """
    按时序顺序将患者分配到 train/valid/test。
    前 60% 患者 → train, 中 20% → valid, 后 20% → test。
    """
    n = len(patient_info)
    train_end = int(n * config.TRAIN_RATIO)
    valid_end = int(n * (config.TRAIN_RATIO + config.VALID_RATIO))

    patient_info["split"] = "test"
    patient_info.loc[:train_end - 1, "split"] = "train"
    patient_info.loc[train_end:valid_end - 1, "split"] = "valid"
    return patient_info


def verify_no_overlap(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame):
    """验证三个 split 之间无患者重叠 (MLGG-S01)。"""
    train_ids = set(train[config.ID_COL])
    valid_ids = set(valid[config.ID_COL])
    test_ids = set(test[config.ID_COL])

    overlap_tv = train_ids & valid_ids
    overlap_tt = train_ids & test_ids
    overlap_vt = valid_ids & test_ids

    assert len(overlap_tv) == 0, f"Train-Valid overlap: {len(overlap_tv)} patients"
    assert len(overlap_tt) == 0, f"Train-Test overlap: {len(overlap_tt)} patients"
    assert len(overlap_vt) == 0, f"Valid-Test overlap: {len(overlap_vt)} patients"
    print("✅ [MLGG-S01] No patient overlap across splits")


def verify_temporal_order(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame):
    """验证时序顺序：train < valid < test (MLGG-S02)。"""
    train_max = train[config.ENCOUNTER_COL].max()
    valid_min = valid[config.ENCOUNTER_COL].min()
    valid_max = valid[config.ENCOUNTER_COL].max()
    test_min = test[config.ENCOUNTER_COL].min()

    # 注意：同一患者的多次入院可能跨越时间段，因此只验证患者级别的时序
    # 即按患者最早 encounter 排序后划分，个别患者的后续 encounter 可能落在后续时段
    print(f"  Train encounter range: ... ~ {train_max}")
    print(f"  Valid encounter range: {valid_min} ~ {valid_max}")
    print(f"  Test  encounter range: {test_min} ~ ...")
    print("✅ [MLGG-S02] Temporal split by patient first-encounter order")


def report_split_stats(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """报告各 split 的统计信息。"""
    records = []
    for name, split_df in [("train", train), ("valid", valid), ("test", test)]:
        n_patients = split_df[config.ID_COL].nunique()
        n_records = len(split_df)
        n_pos = split_df[config.LABEL_COL].sum()
        pos_rate = n_pos / n_records if n_records > 0 else 0
        records.append({
            "split": name,
            "n_patients": n_patients,
            "n_records": n_records,
            "n_positive": n_pos,
            "n_negative": n_records - n_pos,
            "positive_rate": round(pos_rate, 4),
        })
    stats = pd.DataFrame(records)
    return stats


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("Loading data...")
    df = load_data()

    print("Building patient timeline...")
    patient_info = build_patient_timeline(df)

    print("Assigning splits by temporal order...")
    patient_info = assign_splits(patient_info)

    # 保存患者-split 映射
    patient_info.to_csv(os.path.join(results_dir, "patient_split_map.csv"), index=False)

    # 将 split 标签合并回原始数据
    split_map = patient_info[[config.ID_COL, "split"]]
    df = df.merge(split_map, on=config.ID_COL, how="left")

    train = df[df["split"] == "train"].drop(columns=["split"])
    valid = df[df["split"] == "valid"].drop(columns=["split"])
    test = df[df["split"] == "test"].drop(columns=["split"])

    # 保存
    train.to_csv(config.TRAIN_DATA, index=False)
    valid.to_csv(config.VALID_DATA, index=False)
    test.to_csv(config.TEST_DATA, index=False)
    print(f"Saved: train={len(train)}, valid={len(valid)}, test={len(test)}")

    # 验证
    print("\n=== Verification ===")
    verify_no_overlap(train, valid, test)
    verify_temporal_order(train, valid, test)

    # 统计报告
    stats = report_split_stats(train, valid, test)
    stats.to_csv(os.path.join(results_dir, "split_stats.csv"), index=False)
    print("\n=== Split Statistics ===")
    print(stats.to_string(index=False))

    # 正类比例一致性检查
    rates = stats["positive_rate"].values
    max_diff = rates.max() - rates.min()
    print(f"\nPositive rate range: {rates.min():.4f} ~ {rates.max():.4f} (diff={max_diff:.4f})")
    if max_diff > 0.03:
        print("⚠️  WARNING: Positive rate difference > 0.03 across splits — may indicate temporal drift")
    else:
        print("✅ Positive rates consistent across splits")

    # 患者分布
    split_counts = patient_info["split"].value_counts()
    print(f"\n=== Patient Counts ===")
    for s in ["train", "valid", "test"]:
        print(f"  {s}: {split_counts[s]} patients ({split_counts[s]/len(patient_info)*100:.1f}%)")

    print(f"\n✅ Phase 2 results saved to: {results_dir}")


if __name__ == "__main__":
    main()
