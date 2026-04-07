"""
03_preprocessing/scripts/preprocess.py
=======================================
Phase 3: Preprocessing
- Apply tiered missingness strategy (config.MISSINGNESS_STRATEGY)
- Create missing indicators for high-missingness features (MNAR)
- Drop near-zero variance columns
- Encode categorical variables
- Build sklearn Pipeline: imputer → encoder → scaler
- fit on train ONLY, transform on valid/test (MLGG-P01)
- NO SMOTE here — handled in Phase 5 modeling pipeline if needed

输出 → 03_preprocessing/results/
"""

import sys
import os
import json
import pandas as pd
import numpy as np
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import config

from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OrdinalEncoder, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline


def load_splits():
    """加载已划分的 train/valid/test。"""
    train = pd.read_csv(config.TRAIN_DATA)
    valid = pd.read_csv(config.VALID_DATA)
    test = pd.read_csv(config.TEST_DATA)
    return train, valid, test


def add_missing_indicators(df: pd.DataFrame, columns: list, missing_token: str = "?") -> pd.DataFrame:
    """
    为指定列添加 missing indicator (binary)。
    EHR 中 '?' 和 NaN 都视为缺失。
    """
    for col in columns:
        if col in df.columns:
            df[f"{col}_missing"] = ((df[col] == missing_token) | df[col].isna()).astype(int)
    return df


def apply_missingness_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """
    按 config.MISSINGNESS_STRATEGY 四级策略处理缺失值。
    此步骤只做 indicator 添加和列丢弃，不做插补（插补在 Pipeline 中）。
    """
    strategy = config.MISSINGNESS_STRATEGY

    # Tier 4 (>80%): drop original value, keep missing indicator
    tier4_cols = strategy["drop_value_keep_indicator"]
    df = add_missing_indicators(df, tier4_cols)
    df = df.drop(columns=[c for c in tier4_cols if c in df.columns])

    # Tier 3 (40-80%): keep + missing indicator
    tier3_cols = strategy["impute_with_indicator"]
    df = add_missing_indicators(df, tier3_cols)

    # Tier 2 (5-40%): keep + missing indicator
    tier2_cols = strategy["impute_with_indicator_moderate"]
    df = add_missing_indicators(df, tier2_cols)

    # Tier 1 (<5%): simple impute (handled in Pipeline), no indicator needed

    return df


def replace_question_marks(df: pd.DataFrame) -> pd.DataFrame:
    """将 '?' 替换为 NaN，统一缺失表示。"""
    return df.replace("?", np.nan)


def group_icd_codes(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    将 ICD-9 诊断编码按大类分组，减少类别数。
    简化分组：按首字母/前三位数字归类为临床大类。
    """
    def icd_to_group(code):
        if pd.isna(code):
            return "missing"
        code = str(code).strip()
        if code.startswith("V") or code.startswith("v"):
            return "supplementary_V"
        if code.startswith("E") or code.startswith("e"):
            return "external_E"
        try:
            num = float(code)
            if 1 <= num <= 139:
                return "infectious"
            elif 140 <= num <= 239:
                return "neoplasms"
            elif 240 <= num <= 279:
                return "endocrine"
            elif 280 <= num <= 289:
                return "blood"
            elif 290 <= num <= 319:
                return "mental"
            elif 320 <= num <= 389:
                return "nervous"
            elif 390 <= num <= 459:
                return "circulatory"
            elif 460 <= num <= 519:
                return "respiratory"
            elif 520 <= num <= 579:
                return "digestive"
            elif 580 <= num <= 629:
                return "genitourinary"
            elif 630 <= num <= 679:
                return "pregnancy"
            elif 680 <= num <= 709:
                return "skin"
            elif 710 <= num <= 739:
                return "musculoskeletal"
            elif 740 <= num <= 759:
                return "congenital"
            elif 760 <= num <= 779:
                return "perinatal"
            elif 780 <= num <= 799:
                return "symptoms"
            elif 800 <= num <= 999:
                return "injury"
            else:
                return "other"
        except ValueError:
            return "other"

    df[col] = df[col].apply(icd_to_group)
    return df


def drop_non_predictive(df: pd.DataFrame) -> pd.DataFrame:
    """丢弃非预测列和近零方差列。"""
    drop = config.DROP_COLS + config.NEAR_ZERO_VARIANCE_COLS
    existing = [c for c in drop if c in df.columns]
    return df.drop(columns=existing)


def identify_column_types(df: pd.DataFrame):
    """
    按语义将特征分为 5 类，避免 OrdinalEncoder 用于名义变量：
    1. numeric_cols: 真正连续/离散数值 → 中位数插补 + 标准化
    2. nominal_cols: 无序类别 → 众数插补 + OneHotEncoder
    3. ordinal_cols: 有序类别 → 众数插补 + OrdinalEncoder (with explicit order)
    4. binary_cols: 二值类别 → 众数插补 + OrdinalEncoder (0/1, 无有序性问题)
    5. indicator_cols: missing indicator → passthrough
    """
    label = config.LABEL_COL
    all_cols = [c for c in df.columns if c != label]

    # --- 显式定义每个变量的类型 ---

    # 名义变量（无自然顺序）→ OneHotEncoder
    # 包括药物列：No/Steady/Down/Up 没有统一的单调关系
    # (insulin: Down>Up>Steady>No; metformin: No>Down>Steady>Up — 无一致顺序)
    drug_cols_4level = [
        "metformin", "repaglinide", "nateglinide", "chlorpropamide",
        "glimepiride", "glipizide", "glyburide", "pioglitazone",
        "rosiglitazone", "acarbose", "miglitol", "insulin",
        "glyburide-metformin",
    ]
    nominal_set = {
        "race", "gender",
        "admission_type_id", "discharge_disposition_id", "admission_source_id",
        "medical_specialty", "payer_code",
        "diag_1", "diag_2", "diag_3",
    }
    nominal_set.update(drug_cols_4level)

    # 有序变量 → OrdinalEncoder with explicit categories
    # 仅保留有明确自然顺序的变量
    ordinal_set = {"age"}  # age 区间有自然顺序

    # 二值变量 → OrdinalEncoder (0/1, 无有序性问题)
    binary_set = {"change", "diabetesMed"}

    # 本质是类别的 ID 列，转为 string
    id_as_category = {"admission_type_id", "discharge_disposition_id", "admission_source_id"}

    numeric_cols = []
    nominal_cols = []
    ordinal_cols = []
    binary_cols = []
    indicator_cols = []

    for col in all_cols:
        if col.endswith("_missing"):
            indicator_cols.append(col)
        elif col in nominal_set:
            if col in id_as_category:
                df[col] = df[col].astype(str)
            nominal_cols.append(col)
        elif col in ordinal_set:
            ordinal_cols.append(col)
        elif col in binary_set:
            binary_cols.append(col)
        elif df[col].dtype in [np.float64, np.int64, float, int]:
            numeric_cols.append(col)
        else:
            # 未显式分类的 string 列 → 默认名义
            nominal_cols.append(col)

    return numeric_cols, nominal_cols, ordinal_cols, binary_cols, indicator_cols


def build_pipeline(numeric_cols, nominal_cols, ordinal_cols, binary_cols,
                    indicator_cols):
    """
    构建 sklearn ColumnTransformer，正确区分编码方式：
    - 数值：中位数插补 → 标准化
    - 名义类别：众数插补 → OneHotEncoder (drop='if_binary' 避免共线性)
    - 有序类别：众数插补 → OrdinalEncoder (显式指定顺序)
    - 二值类别：众数插补 → OrdinalEncoder (0/1)
    - Missing indicator：passthrough
    """
    numeric_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])

    nominal_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OneHotEncoder(
            drop="if_binary",  # 二值名义变量只保留一列
            sparse_output=False,
            handle_unknown="infrequent_if_exist",
            min_frequency=50,  # 频次 < 50 的类别合并为 "infrequent"
        )),
    ])

    # Ordinal category mappings — explicit order required for each variable
    ORDINAL_CATEGORY_MAP = {
        "age": ["[0-10)", "[10-20)", "[20-30)", "[30-40)", "[40-50)",
                "[50-60)", "[60-70)", "[70-80)", "[80-90)", "[90-100)"],
    }

    ordinal_categories = []
    for col in ordinal_cols:
        if col in ORDINAL_CATEGORY_MAP:
            ordinal_categories.append(ORDINAL_CATEGORY_MAP[col])
        else:
            raise ValueError(
                f"Ordinal column '{col}' has no defined category order in "
                f"ORDINAL_CATEGORY_MAP. Add explicit order or move to nominal_set."
            )

    ordinal_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OrdinalEncoder(
            categories=ordinal_categories,
            handle_unknown="use_encoded_value",
            unknown_value=-1,
        )),
    ])

    binary_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value",
                                    unknown_value=-1)),
    ])

    transformers = [
        ("num", numeric_transformer, numeric_cols),
        ("nominal", nominal_transformer, nominal_cols),
    ]
    if ordinal_cols:
        transformers.append(("ordinal", ordinal_transformer, ordinal_cols))
    if binary_cols:
        transformers.append(("binary", binary_transformer, binary_cols))
    if indicator_cols:
        transformers.append(("indicator", "passthrough", indicator_cols))

    preprocessor = ColumnTransformer(
        transformers=transformers,
        remainder="drop",
    )

    return preprocessor


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("Loading splits...")
    train, valid, test = load_splits()
    print(f"  Train: {train.shape}, Valid: {valid.shape}, Test: {test.shape}")

    # Step 1: Drop non-predictive and near-zero variance columns
    print("\nStep 1: Dropping non-predictive & near-zero variance columns...")
    for name, df in [("train", train), ("valid", valid), ("test", test)]:
        df_clean = drop_non_predictive(df)
        if name == "train":
            train = df_clean
        elif name == "valid":
            valid = df_clean
        else:
            test = df_clean

    # Step 2: Apply missingness strategy (indicators + tier 4 drops)
    print("Step 2: Applying tiered missingness strategy...")
    train = apply_missingness_strategy(train)
    valid = apply_missingness_strategy(valid)
    test = apply_missingness_strategy(test)

    # Step 3: Group ICD codes
    print("Step 3: Grouping ICD-9 diagnosis codes...")
    for diag_col in ["diag_1", "diag_2", "diag_3"]:
        train = group_icd_codes(train, diag_col)
        valid = group_icd_codes(valid, diag_col)
        test = group_icd_codes(test, diag_col)

    # Step 4: Replace '?' with NaN
    print("Step 4: Unifying missing representation (? → NaN)...")
    train = replace_question_marks(train)
    valid = replace_question_marks(valid)
    test = replace_question_marks(test)

    # Step 5: Identify column types (5-way classification)
    numeric_cols, nominal_cols, ordinal_cols, binary_cols, indicator_cols = \
        identify_column_types(train)
    print(f"\n  Numeric features:   {len(numeric_cols)}  → StandardScaler")
    print(f"  Nominal features:   {len(nominal_cols)}  → OneHotEncoder")
    print(f"  Ordinal features:   {len(ordinal_cols)}  → OrdinalEncoder (explicit order)")
    print(f"  Binary features:    {len(binary_cols)}  → OrdinalEncoder (0/1)")
    print(f"  Indicator features: {len(indicator_cols)}  → passthrough")

    # Save column info
    col_info = {
        "numeric_cols": numeric_cols,
        "nominal_cols": nominal_cols,
        "ordinal_cols": ordinal_cols,
        "binary_cols": binary_cols,
        "indicator_cols": indicator_cols,
    }
    with open(os.path.join(results_dir, "column_types.json"), "w") as f:
        json.dump(col_info, f, indent=2)

    # Step 5b: Verify ordinal monotonicity (MLGG-P05 requirement)
    if ordinal_cols:
        from scipy.stats import spearmanr
        print(f"\n  Ordinal monotonicity check (Spearman):")
        for col in ordinal_cols:
            # Encode ordinal temporarily to check correlation with label
            from sklearn.preprocessing import OrdinalEncoder as _OE
            ORDINAL_CATEGORY_MAP = {
                "age": ["[0-10)","[10-20)","[20-30)","[30-40)","[40-50)",
                        "[50-60)","[60-70)","[70-80)","[80-90)","[90-100)"],
            }
            if col in ORDINAL_CATEGORY_MAP:
                _enc = _OE(categories=[ORDINAL_CATEGORY_MAP[col]],
                           handle_unknown="use_encoded_value", unknown_value=-1)
                vals = _enc.fit_transform(train[[col]].astype(str)).ravel()
                mask = vals >= 0
                rho, pval = spearmanr(vals[mask], train[config.LABEL_COL].values[mask])
                status = "✅" if abs(rho) > 0.01 else "⚠️  weak"
                print(f"    {status} {col}: rho={rho:.4f}, p={pval:.2e}")

    # Step 6: Build and fit pipeline on TRAIN ONLY (MLGG-P01)
    print("\nStep 6: Building pipeline (fit on TRAIN ONLY)...")
    preprocessor = build_pipeline(numeric_cols, nominal_cols, ordinal_cols,
                                   binary_cols, indicator_cols)

    y_train = train[config.LABEL_COL].values
    y_valid = valid[config.LABEL_COL].values
    y_test = test[config.LABEL_COL].values

    # Ensure all non-numeric columns are string type
    for col in nominal_cols + ordinal_cols + binary_cols:
        train[col] = train[col].astype(str)
        valid[col] = valid[col].astype(str)
        test[col] = test[col].astype(str)

    X_train = preprocessor.fit_transform(train.drop(columns=[config.LABEL_COL]))
    X_valid = preprocessor.transform(valid.drop(columns=[config.LABEL_COL]))
    X_test = preprocessor.transform(test.drop(columns=[config.LABEL_COL]))

    print(f"  X_train: {X_train.shape}")
    print(f"  X_valid: {X_valid.shape}")
    print(f"  X_test:  {X_test.shape}")

    # Step 7: Save outputs — extract feature names from pipeline
    print("\nStep 7: Saving outputs...")

    # Build feature names from ColumnTransformer
    feature_names = list(numeric_cols)  # numeric names unchanged

    # OneHotEncoder feature names
    ohe = preprocessor.named_transformers_["nominal"].named_steps["encoder"]
    ohe_names = ohe.get_feature_names_out(nominal_cols).tolist()
    feature_names += ohe_names

    # Ordinal + binary names unchanged
    feature_names += ordinal_cols
    feature_names += binary_cols
    feature_names += indicator_cols
    np.savez(
        os.path.join(results_dir, "processed_data.npz"),
        X_train=X_train, y_train=y_train,
        X_valid=X_valid, y_valid=y_valid,
        X_test=X_test, y_test=y_test,
    )
    joblib.dump(preprocessor, os.path.join(results_dir, "preprocessor.pkl"))

    with open(os.path.join(results_dir, "feature_names.json"), "w") as f:
        json.dump(feature_names, f, indent=2)

    # Step 8: Verification
    print("\n=== Verification ===")
    print(f"✅ [MLGG-P01] Pipeline fit on train only, transform on valid/test")
    print(f"✅ [MLGG-P03] No global cleaning before split (split done in Phase 2)")

    # Check no NaN remains
    for name, X in [("train", X_train), ("valid", X_valid), ("test", X_test)]:
        n_nan = np.isnan(X).sum()
        if n_nan > 0:
            print(f"⚠️  {name} has {n_nan} NaN values after preprocessing!")
        else:
            print(f"✅ {name}: no NaN remaining")

    # Missing indicator summary
    indicator_cols = [c for c in feature_names if c.endswith("_missing")]
    print(f"\n  Missing indicators created: {len(indicator_cols)}")
    for ic in indicator_cols:
        idx = feature_names.index(ic)
        rate = X_train[:, idx].mean()
        print(f"    {ic}: {rate:.1%} flagged in train")

    print(f"\n✅ Phase 3 results saved to: {results_dir}")


if __name__ == "__main__":
    main()
