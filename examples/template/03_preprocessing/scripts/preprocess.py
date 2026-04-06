"""
Phase 3: Preprocessing

Methodology: MLGG Standard (Kaufman 2012, van den Goorbergh 2022,
             Madley-Dowd 2019)

Checkpoint (MLGG):
  - MLGG-P01: All fit() on training set ONLY?
  - MLGG-P03: No global cleaning before split?
  - MLGG-P04: Imputer statistics from training set only?
  - MLGG-P05: Encoding matches variable semantics?
  - MLGG-P06: Tiered missingness strategy?

Input:  02_splitting/results/train.csv, valid.csv, test.csv
Output: 03_preprocessing/results/processed_data.npz, feature_names.json,
        encoding_groups.json, column_types.json, missingness_report.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, OrdinalEncoder
from sklearn.impute import SimpleImputer
import joblib


# ─── Load & Separate ─────────────────────────────────────────

def load_splits():
    """Load train/valid/test from Phase 2."""
    train = pd.read_csv(cfg.SPLIT_RESULTS / "train.csv")
    valid = pd.read_csv(cfg.SPLIT_RESULTS / "valid.csv")
    test = pd.read_csv(cfg.SPLIT_RESULTS / "test.csv")
    return train, valid, test


def separate_xy(df):
    """Separate features and label. Drop ID and time columns.

    MLGG-F05: If temporal feature lists are configured, enforce whitelist.
    """
    drop_cols = [cfg.PATIENT_ID_COL, cfg.TIME_COL, cfg.LABEL_COL]
    drop_cols = [c for c in drop_cols if c and c in df.columns]
    X = df.drop(columns=drop_cols)
    y = df[cfg.LABEL_COL].values

    allowed = cfg.ADMISSION_FEATURES or cfg.DISCHARGE_FEATURES
    if allowed:
        available = [c for c in allowed if c in X.columns]
        dropped = set(X.columns) - set(available)
        if dropped:
            print(f"[MLGG-F05] Temporal filter: dropped {len(dropped)} "
                  f"post-prediction features")
        X = X[available]
    elif X.shape[1] > 0:
        print("[MLGG-F05] WARNING: No temporal feature list configured. "
              "All features assumed available at prediction time.")

    return X, y


# ─── Column Type Detection (MLGG-P05) ────────────────────────

def classify_columns(X_train):
    """Classify columns by cardinality and dtype (MLGG-P05).

    Key rule: dtype determines whether low-cardinality columns are
    categorical (nominal → OneHot) or numeric (ordinal/count → keep).

    | Condition                                    | Type             | Encoding    |
    |----------------------------------------------|------------------|-------------|
    | nunique <= 1                                 | constant         | drop        |
    | in ORDINAL_COLUMNS config                    | ordinal          | verified    |
    | nunique == 2                                 | binary           | 0/1         |
    | 3 <= nunique <= MAX and string/object dtype   | categorical      | OneHot      |
    | 3 <= nunique <= MAX and numeric dtype         | numeric          | passthrough |
    | nunique > MAX and numeric dtype               | numeric          | passthrough |
    | nunique > MAX and string/object dtype          | high_cardinality | passthrough |

    Why numeric low-cardinality stays numeric:
      Count variables (num_medications=0..11) have inherent order.
      OneHot destroys "5 > 3" information, wastes degrees of freedom,
      and inflates EPV denominator. Integer-coded IDs that are actually
      nominal (admission_type_id=1..5) should be declared in
      ORDINAL_COLUMNS or cast to string before Phase 3.
    """
    col_types = {
        "binary": [],
        "categorical": [],
        "ordinal": [],
        "numeric": [],
        "high_cardinality": [],
        "constant": [],
    }

    for col in X_train.columns:
        nunique = X_train[col].nunique()
        is_number = pd.api.types.is_numeric_dtype(X_train[col])

        # Constant or empty
        if nunique <= 1:
            col_types["constant"].append(col)
            continue

        # Configured ordinal (clinically verified)
        if col in cfg.ORDINAL_COLUMNS:
            col_types["ordinal"].append(col)
            continue

        # Binary
        if nunique == 2:
            col_types["binary"].append(col)
            continue

        # Low cardinality: dtype decides categorical vs numeric
        if nunique <= cfg.MAX_ONEHOT_CARDINALITY:
            if is_number:
                # Integer counts, scores, coded ordinals → keep numeric
                col_types["numeric"].append(col)
            else:
                # String/object → truly nominal → OneHot
                col_types["categorical"].append(col)
            continue

        # High cardinality
        if is_number:
            col_types["numeric"].append(col)
        else:
            col_types["high_cardinality"].append(col)

    for t, cols in col_types.items():
        if cols:
            print(f"  {t}: {len(cols)} columns")

    return col_types


# ─── Missingness Analysis (MLGG-P06) ─────────────────────────

def analyze_missingness(X_train, col_types):
    """Tiered missingness strategy (Madley-Dowd 2019).

    Tier 1 (<5%):   simple impute
    Tier 2 (5-40%): impute + indicator
    Tier 3 (40-80%): impute + indicator (sensitivity flag)
    Tier 4 (>80%):  drop value, keep indicator only
    """
    all_cols = []
    for cols in col_types.values():
        all_cols.extend(cols)

    miss_rates = {}
    tiers = {"tier1": [], "tier2": [], "tier3": [], "tier4": []}

    for col in all_cols:
        rate = X_train[col].isna().mean()
        miss_rates[col] = rate

        # Manual overrides take priority
        if col in cfg.COLS_DROP_VALUE_KEEP_INDICATOR:
            tiers["tier4"].append(col)
        elif col in cfg.COLS_IMPUTE_WITH_INDICATOR:
            tiers["tier2"].append(col)
        elif col in cfg.COLS_SIMPLE_IMPUTE:
            tiers["tier1"].append(col)
        elif rate > cfg.MISSING_TIER3_UPPER:
            tiers["tier4"].append(col)
        elif rate > cfg.MISSING_TIER2_UPPER:
            tiers["tier3"].append(col)
        elif rate > cfg.MISSING_TIER1_UPPER:
            tiers["tier2"].append(col)
        else:
            tiers["tier1"].append(col)

    for tier, cols in tiers.items():
        if cols:
            print(f"  {tier}: {len(cols)} columns")

    return miss_rates, tiers


# ─── Encoding ────────────────────────────────────────────────

def encode_binary(X_train, X_valid, X_test, cols):
    """Binary: map to 0/1 based on training set mapping. OOD → 0.0."""
    mappings = {}
    for col in cols:
        vals = sorted(X_train[col].dropna().unique())
        if len(vals) != 2:
            continue
        mapping = {vals[0]: 0, vals[1]: 1}
        mappings[col] = mapping
        for df in [X_train, X_valid, X_test]:
            df[col] = df[col].map(mapping).fillna(0.0)
    return mappings


def encode_categorical(X_train, X_valid, X_test, cols):
    """Categorical: OneHot, train categories only. OOD → all-zero row.

    Returns encoding_groups: {original_col: [dummy_col_1, dummy_col_2, ...]}
    """
    encoding_groups = {}
    new_train_parts = [X_train.drop(columns=cols)]
    new_valid_parts = [X_valid.drop(columns=cols)]
    new_test_parts = [X_test.drop(columns=cols)]

    for col in cols:
        categories = sorted(X_train[col].dropna().unique())
        dummy_names = [f"{col}_{cat}" for cat in categories]
        encoding_groups[col] = dummy_names

        for df, parts in [(X_train, new_train_parts),
                          (X_valid, new_valid_parts),
                          (X_test, new_test_parts)]:
            dummies = pd.DataFrame(0.0, index=df.index, columns=dummy_names)
            for cat, dname in zip(categories, dummy_names):
                dummies.loc[df[col] == cat, dname] = 1.0
            parts.append(dummies)

    X_train = pd.concat(new_train_parts, axis=1)
    X_valid = pd.concat(new_valid_parts, axis=1)
    X_test = pd.concat(new_test_parts, axis=1)

    return X_train, X_valid, X_test, encoding_groups


def encode_ordinal(X_train, X_valid, X_test, cols):
    """Ordinal: encode with verified order from config. OOD → NaN."""
    for col in cols:
        order = cfg.ORDINAL_COLUMNS[col]
        mapping = {v: i for i, v in enumerate(order)}
        for df in [X_train, X_valid, X_test]:
            df[col] = df[col].map(mapping)  # OOD stays NaN


# ─── Imputation ──────────────────────────────────────────────

def impute_tiered(X_train, X_valid, X_test, col_types, tiers):
    """Tiered imputation: fit on training set only (MLGG-P01/P04).

    Returns indicator columns added and imputer statistics.
    """
    numeric_like = set(col_types["numeric"] + col_types["binary"] + col_types["ordinal"])
    indicator_cols_added = []
    impute_stats = {}

    # Tier 4: drop original value, keep indicator only
    for col in tiers["tier4"]:
        if col in X_train.columns:
            ind_name = f"{col}_missing"
            for df in [X_train, X_valid, X_test]:
                df[ind_name] = df[col].isna().astype(float)
                df.drop(columns=[col], inplace=True)
            indicator_cols_added.append(ind_name)
            impute_stats[col] = {"tier": 4, "action": "drop_value_keep_indicator"}

    # Tier 2/3: impute + indicator
    for tier_name, tier_cols in [("tier2", tiers["tier2"]), ("tier3", tiers["tier3"])]:
        tier_num = 2 if tier_name == "tier2" else 3
        for col in tier_cols:
            if col not in X_train.columns:
                continue
            # Add indicator
            ind_name = f"{col}_missing"
            for df in [X_train, X_valid, X_test]:
                df[ind_name] = df[col].isna().astype(float)
            indicator_cols_added.append(ind_name)

            # Impute based on type
            if col in numeric_like:
                fill_val = float(X_train[col].median())
                strategy = "median"
            else:
                fill_val = X_train[col].mode().iloc[0] if not X_train[col].mode().empty else 0
                strategy = "mode"
            for df in [X_train, X_valid, X_test]:
                df[col] = df[col].fillna(fill_val)
            impute_stats[col] = {"tier": tier_num, "strategy": strategy, "fill_value": str(fill_val)}

    # Tier 1: simple impute, no indicator
    for col in tiers["tier1"]:
        if col not in X_train.columns:
            continue
        if col in numeric_like:
            fill_val = float(X_train[col].median())
            strategy = "median"
        else:
            fill_val = X_train[col].mode().iloc[0] if not X_train[col].mode().empty else 0
            strategy = "mode"
        for df in [X_train, X_valid, X_test]:
            df[col] = df[col].fillna(fill_val)
        impute_stats[col] = {"tier": 1, "strategy": strategy, "fill_value": str(fill_val)}

    return X_train, X_valid, X_test, indicator_cols_added, impute_stats


# ─── Scaling ─────────────────────────────────────────────────

def scale_numeric(X_train, X_valid, X_test, numeric_cols):
    """StandardScaler on numeric columns. Fit on train only (MLGG-P01)."""
    cols_to_scale = [c for c in numeric_cols if c in X_train.columns]
    if not cols_to_scale:
        return X_train, X_valid, X_test, None

    scaler = StandardScaler()
    X_train[cols_to_scale] = scaler.fit_transform(X_train[cols_to_scale])
    X_valid[cols_to_scale] = scaler.transform(X_valid[cols_to_scale])
    X_test[cols_to_scale] = scaler.transform(X_test[cols_to_scale])

    return X_train, X_valid, X_test, scaler


# ─── Main ─────────────────────────────────────────────────────

def main():
    cfg.PREPROCESS_RESULTS.mkdir(parents=True, exist_ok=True)

    # Load splits
    train, valid, test = load_splits()
    X_train, y_train = separate_xy(train)
    X_valid, y_valid = separate_xy(valid)
    X_test, y_test = separate_xy(test)

    print(f"Input: {X_train.shape[1]} features, "
          f"{len(y_train)} train / {len(y_valid)} valid / {len(y_test)} test")

    # Step 1: Classify column types (MLGG-P05)
    print("\n[MLGG-P05] Column type classification (cardinality-based):")
    col_types = classify_columns(X_train)

    # Drop constants
    if col_types["constant"]:
        print(f"Dropping {len(col_types['constant'])} constant columns: "
              f"{col_types['constant']}")
        for df in [X_train, X_valid, X_test]:
            df.drop(columns=col_types["constant"], inplace=True, errors="ignore")

    # Warn about high-cardinality
    if col_types["high_cardinality"]:
        print(f"WARNING: {len(col_types['high_cardinality'])} high-cardinality string columns "
              f"left as-is: {col_types['high_cardinality'][:5]}")

    # Step 2: Missingness analysis (MLGG-P06)
    print("\n[MLGG-P06] Missingness tiers (Madley-Dowd 2019):")
    miss_rates, tiers = analyze_missingness(X_train, col_types)

    # Step 3: Encoding — fit categories on train only (MLGG-P01/P05)
    print("\n[MLGG-P05] Encoding:")
    binary_mappings = encode_binary(X_train, X_valid, X_test, col_types["binary"])
    print(f"  Binary: {len(binary_mappings)} columns → 0/1")

    X_train, X_valid, X_test, encoding_groups = encode_categorical(
        X_train, X_valid, X_test, col_types["categorical"]
    )
    n_dummies = sum(len(v) for v in encoding_groups.values())
    print(f"  Categorical: {len(col_types['categorical'])} columns → "
          f"{n_dummies} dummy columns (OneHot)")

    if col_types["ordinal"]:
        encode_ordinal(X_train, X_valid, X_test, col_types["ordinal"])
        print(f"  Ordinal: {len(col_types['ordinal'])} columns (verified order from config)")

    # Step 4: Tiered imputation — statistics from train only (MLGG-P01/P04)
    print("\n[MLGG-P04] Imputation (train-only statistics):")
    X_train, X_valid, X_test, indicator_cols, impute_stats = impute_tiered(
        X_train, X_valid, X_test, col_types, tiers
    )
    if indicator_cols:
        print(f"  Added {len(indicator_cols)} missingness indicator columns")

    # Step 5: Scale numeric columns — fit on train only (MLGG-P01)
    X_train, X_valid, X_test, scaler = scale_numeric(
        X_train, X_valid, X_test, col_types["numeric"]
    )
    print(f"[MLGG-P01] Scaler fitted on training set only")

    # Final feature names (column order after all transformations)
    feature_names = X_train.columns.tolist()
    print(f"\nTotal features after preprocessing: {len(feature_names)}")

    # Verify no NaN remaining
    for name, arr in [("train", X_train), ("valid", X_valid), ("test", X_test)]:
        n_nan = arr.isna().sum().sum() if isinstance(arr, pd.DataFrame) else np.isnan(arr).sum()
        if n_nan > 0:
            raise ValueError(
                f"CRITICAL: {n_nan} NaN values in {name} after preprocessing. "
                f"Check imputation coverage."
            )

    # Convert to numpy for downstream
    X_train_np = X_train.values.astype(np.float64)
    X_valid_np = X_valid.values.astype(np.float64)
    X_test_np = X_test.values.astype(np.float64)

    # ─── Save outputs ────────────────────────────────────────

    np.savez(
        cfg.PREPROCESS_RESULTS / "processed_data.npz",
        X_train=X_train_np, y_train=y_train,
        X_valid=X_valid_np, y_valid=y_valid,
        X_test=X_test_np, y_test=y_test,
    )
    with open(cfg.PREPROCESS_RESULTS / "feature_names.json", "w") as f:
        json.dump(feature_names, f, indent=2)

    with open(cfg.PREPROCESS_RESULTS / "column_types.json", "w") as f:
        json.dump(col_types, f, indent=2)

    # encoding_groups.json — Phase 4 Group LASSO needs this
    with open(cfg.PREPROCESS_RESULTS / "encoding_groups.json", "w") as f:
        json.dump(encoding_groups, f, indent=2)

    # Missingness report — audit trail
    missingness_report = {
        "miss_rates": {k: round(v, 4) for k, v in miss_rates.items()},
        "tiers": {k: v for k, v in tiers.items()},
        "impute_stats": impute_stats,
        "indicator_cols_added": indicator_cols,
        "tier_thresholds": {
            "tier1_upper": cfg.MISSING_TIER1_UPPER,
            "tier2_upper": cfg.MISSING_TIER2_UPPER,
            "tier3_upper": cfg.MISSING_TIER3_UPPER,
        },
    }
    with open(cfg.PREPROCESS_RESULTS / "missingness_report.json", "w") as f:
        json.dump(missingness_report, f, indent=2)

    if scaler is not None:
        joblib.dump(scaler, cfg.PREPROCESS_RESULTS / "scaler.pkl")

    print(f"\nPhase 3 complete. Results in {cfg.PREPROCESS_RESULTS}/")
    print("--- Checkpoint ---")
    print("[x] All fit()/statistics on training set only (MLGG-P01/P04)")
    print("[x] Encoding matches variable semantics (MLGG-P05)")
    print(f"    Binary({len(col_types['binary'])}) → 0/1, "
          f"Categorical({len(col_types['categorical'])}) → OneHot, "
          f"Ordinal({len(col_types['ordinal'])}) → verified order")
    print(f"[x] Tiered missingness strategy (MLGG-P06, Madley-Dowd 2019)")
    print(f"    T1={len(tiers['tier1'])}, T2={len(tiers['tier2'])}, "
          f"T3={len(tiers['tier3'])}, T4={len(tiers['tier4'])}")
    print("[x] encoding_groups.json exported for Phase 4 Group LASSO")


if __name__ == "__main__":
    main()
