#!/usr/bin/env python3
"""
Generate synthetic benchmark code snippets with known ground truth.

Creates 100 Python files (50 leaky + 50 clean) covering:
- All 8 leakage rules (R001-R003, R005-R007, R017, R020)
- Various code styles (dict comprehension, Pipeline, notebook-like, multi-step)
- Edge cases that previously caused FP/FN

Each file has a ground truth label in its filename:
  leak_R001_01.py  — has R001 leakage
  clean_pipeline_01.py — clean, uses Pipeline correctly

Usage:
  python3 experiments/paper/benchmark/generate_benchmark.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).parent / "snippets"

# ---------------------------------------------------------------------------
# Leaky snippets (50)
# ---------------------------------------------------------------------------

LEAKY = [
    # === R001: fit_transform before split (10 variants) ===
    ("leak_R001_01_scaler_before_split", "R001", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import pandas as pd
df = pd.read_csv("data.csv")
X = df.drop(columns=["target"])
y = df["target"]
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)
"""),

    ("leak_R001_02_imputer_before_split", "R001", """
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
imp = SimpleImputer(strategy="mean")
X_clean = imp.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_clean, y)
"""),

    ("leak_R001_03_pca_before_split", "R001", """
from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
pca = PCA(n_components=10)
X_pca = pca.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_pca, y, test_size=0.2)
"""),

    ("leak_R001_04_minmax_before_split", "R001", """
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
scaler = MinMaxScaler()
X_norm = scaler.fit_transform(features)
train_X, test_X, train_y, test_y = train_test_split(X_norm, labels, test_size=0.3)
"""),

    ("leak_R001_05_robust_scaler", "R001", """
from sklearn.preprocessing import RobustScaler
from sklearn.model_selection import train_test_split
rs = RobustScaler()
data_scaled = rs.fit_transform(data_features)
X_train, X_test, y_train, y_test = train_test_split(data_scaled, target)
"""),

    # === R002: scaler fit on test (8 variants) ===
    ("leak_R002_01_fit_transform_test", "R002", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.fit_transform(X_test)
"""),

    ("leak_R002_02_imputer_fit_test", "R002", """
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
imputer = SimpleImputer()
imp = imputer.fit(X_train)
X_train_clean = imp.transform(X_train)
imp = imputer.fit(X_test)
X_test_clean = imp.transform(X_test)
"""),

    ("leak_R002_03_dict_comprehension", "R002", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
scaler = StandardScaler().fit(X_train)
data = {"train": X_train, "test": X_test}
scaled = {k: scaler.fit_transform(v) for k, v in data.items()}
"""),

    ("leak_R002_04_separate_fit_test", "R002", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
sc = StandardScaler()
sc.fit(X_test)
X_test_scaled = sc.transform(X_test)
"""),

    ("leak_R002_05_normalizer_test", "R002", """
from sklearn.preprocessing import Normalizer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
norm = Normalizer()
X_test_norm = norm.fit_transform(X_test)
"""),

    ("leak_R002_06_valid_and_test", "R002", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.4)
X_valid, X_test, y_valid, y_test = train_test_split(X_temp, y_temp, test_size=0.5)
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_valid_s = scaler.fit_transform(X_valid)
X_test_s = scaler.fit_transform(X_test)
"""),

    ("leak_R002_07_iterative_imputer_test", "R002", """
from sklearn.experimental import enable_iterative_imputer
from sklearn.impute import IterativeImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
imp = IterativeImputer()
X_train = imp.fit_transform(X_train)
X_test = imp.fit_transform(X_test)
"""),

    ("leak_R002_08_knn_imputer_test", "R002", """
from sklearn.impute import KNNImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
knn_imp = KNNImputer(n_neighbors=5)
X_test_clean = knn_imp.fit_transform(X_test)
"""),

    # === R003: SMOTE on test (3 variants) ===
    ("leak_R003_01_smote_full_data", "R003", """
from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split
X_resampled, y_resampled = SMOTE().fit_resample(X, y)
X_train, X_test, y_train, y_test = train_test_split(X_resampled, y_resampled)
"""),

    ("leak_R003_02_smote_on_test", "R003", """
from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
sm = SMOTE()
X_test_res, y_test_res = sm.fit_resample(X_test, y_test)
"""),

    ("leak_R003_03_adasyn_full", "R003", """
from imblearn.over_sampling import ADASYN
from sklearn.model_selection import train_test_split
ada = ADASYN()
X_res, y_res = ada.fit_resample(X_all, y_all)
X_train, X_test, y_train, y_test = train_test_split(X_res, y_res)
"""),

    # === R005: threshold on test (3 variants, thresholds USED) ===
    ("leak_R005_01_youden_on_test", "R005", """
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, thresholds = roc_curve(y_test, y_pred)
optimal_idx = (tpr - fpr).argmax()
optimal_threshold = thresholds[optimal_idx]
"""),

    ("leak_R005_02_pr_curve_threshold", "R005", """
from sklearn.metrics import precision_recall_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
prec, rec, thresholds = precision_recall_curve(y_test, y_scores)
best_f1_idx = (2 * prec * rec / (prec + rec + 1e-8)).argmax()
best_thresh = thresholds[best_f1_idx]
"""),

    ("leak_R005_03_threshold_stored", "R005", """
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, thresholds = roc_curve(y_test, model.predict_proba(X_test)[:, 1])
config['threshold'] = thresholds[np.argmax(tpr - fpr)]
"""),

    # === R006: feature selection on full data (3 variants) ===
    ("leak_R006_01_selectkbest_full", "R006", """
from sklearn.feature_selection import SelectKBest, chi2
from sklearn.model_selection import train_test_split
selector = SelectKBest(chi2, k=10)
X_selected = selector.fit_transform(X, y)
X_train, X_test, y_train, y_test = train_test_split(X_selected, y)
"""),

    ("leak_R006_02_mutual_info_full", "R006", """
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.model_selection import train_test_split
fs = SelectKBest(mutual_info_classif, k=20)
X_fs = fs.fit_transform(X_all, y_all)
X_train, X_test, y_train, y_test = train_test_split(X_fs, y_all)
"""),

    ("leak_R006_03_variance_threshold_full", "R006", """
from sklearn.feature_selection import VarianceThreshold
from sklearn.model_selection import train_test_split
vt = VarianceThreshold(threshold=0.01)
X_vt = vt.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_vt, y)
"""),

    # === R007: target as feature (3 variants) ===
    ("leak_R007_01_target_in_features", "R007", """
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
X = df[['age', 'bmi', 'target', 'blood_pressure']]
y = df['target']
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = RandomForestClassifier()
model.fit(X_train, y_train)
"""),

    ("leak_R007_02_no_drop_target", "R007", """
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
features = data
labels = data['outcome']
X_train, X_test, y_train, y_test = train_test_split(features, labels)
lr = LogisticRegression()
lr.fit(X_train, y_train)
"""),

    ("leak_R007_03_same_df", "R007", """
from sklearn.model_selection import train_test_split
import xgboost as xgb
X = patient_data
y = patient_data['mortality']
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = xgb.XGBClassifier()
model.fit(X_train, y_train)
"""),

    # === R017: early stopping on test (3 variants) ===
    ("leak_R017_01_eval_set_test", "R017", """
import xgboost as xgb
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = xgb.XGBClassifier(early_stopping_rounds=10)
model.fit(X_train, y_train, eval_set=[(X_test, y_test)])
"""),

    ("leak_R017_02_lgbm_test_eval", "R017", """
import lightgbm as lgb
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = lgb.LGBMClassifier(n_estimators=1000)
model.fit(X_train, y_train, eval_set=[(X_test, y_test)], callbacks=[lgb.early_stopping(10)])
"""),

    ("leak_R017_03_catboost_test", "R017", """
from catboost import CatBoostClassifier
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = CatBoostClassifier(iterations=500, early_stopping_rounds=20)
model.fit(X_train, y_train, eval_set=(X_test, y_test))
"""),

    # === R020: global cleaning before split (3 variants) ===
    ("leak_R020_01_dropna_before_split", "R020", """
from sklearn.model_selection import train_test_split
import pandas as pd
df = pd.read_csv("data.csv")
df = df.dropna()
X = df.drop(columns=["target"])
y = df["target"]
X_train, X_test, y_train, y_test = train_test_split(X, y)
"""),

    ("leak_R020_02_fillna_before_split", "R020", """
from sklearn.model_selection import train_test_split
import pandas as pd
df = pd.read_csv("data.csv")
df = df.fillna(df.mean())
X_train, X_test, y_train, y_test = train_test_split(df.drop(columns=['y']), df['y'])
"""),

    ("leak_R020_03_clip_before_split", "R020", """
from sklearn.model_selection import train_test_split
import pandas as pd
df = pd.read_csv("data.csv")
for col in df.select_dtypes(include='number').columns:
    df[col] = df[col].clip(lower=df[col].quantile(0.01), upper=df[col].quantile(0.99))
X_train, X_test, y_train, y_test = train_test_split(df.drop(columns=['target']), df['target'])
"""),

    # === Edge cases from real-world audit findings ===
    ("leak_edge_01_dict_fit_transform_all", "R002", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X = {}; y = {}
X['train'], X['test'], y['train'], y['test'] = train_test_split(X_all, y_all)
preprocess = StandardScaler().fit(X['train'])
X = {k: preprocess.fit_transform(v) for k, v in X.items()}
"""),

    ("leak_edge_02_loop_fit_transform", "R002", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
scaler = StandardScaler()
for split_name, split_data in [("train", X_train), ("test", X_test)]:
    scaled = scaler.fit_transform(split_data)
"""),

    ("leak_edge_03_function_hides_leak", "R001", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
def preprocess(data):
    scaler = StandardScaler()
    return scaler.fit_transform(data)
X_processed = preprocess(X)
X_train, X_test, y_train, y_test = train_test_split(X_processed, y)
"""),

    ("leak_edge_04_method_chain", "R001", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_scaled = StandardScaler().fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)
"""),

    # Fill to 50
    ("leak_R001_06_power_transformer", "R001", """
from sklearn.preprocessing import PowerTransformer
from sklearn.model_selection import train_test_split
pt = PowerTransformer()
X_transformed = pt.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_transformed, y)
"""),

    ("leak_R001_07_quantile_transformer", "R001", """
from sklearn.preprocessing import QuantileTransformer
from sklearn.model_selection import train_test_split
qt = QuantileTransformer(output_distribution='normal')
X_qt = qt.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_qt, y)
"""),

    ("leak_R002_09_poly_features_test", "R002", """
from sklearn.preprocessing import PolynomialFeatures
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
poly = PolynomialFeatures(degree=2)
X_test_poly = poly.fit_transform(X_test)
"""),

    ("leak_R001_08_tfidf_before_split", "R001", """
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
tfidf = TfidfVectorizer(max_features=1000)
X_tfidf = tfidf.fit_transform(text_data)
X_train, X_test, y_train, y_test = train_test_split(X_tfidf, labels)
"""),

    ("leak_R001_09_one_hot_before_split", "R001", """
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import train_test_split
ohe = OneHotEncoder(sparse_output=False, handle_unknown='ignore')
X_encoded = ohe.fit_transform(X_cat)
X_train, X_test, y_train, y_test = train_test_split(X_encoded, y)
"""),

    ("leak_R001_10_multiple_transforms", "R001", """
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.impute import SimpleImputer
imp = SimpleImputer().fit_transform(X)
scaled = StandardScaler().fit_transform(imp)
normed = MinMaxScaler().fit_transform(scaled)
X_train, X_test, y_train, y_test = train_test_split(normed, y)
"""),
]

# ---------------------------------------------------------------------------
# Clean snippets (50)
# ---------------------------------------------------------------------------

CLEAN = [
    # === Correct preprocessing (15 variants) ===
    ("clean_correct_01_fit_train_transform_test", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)
"""),

    ("clean_correct_02_pipeline", """
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
pipe = Pipeline([('scaler', StandardScaler()), ('lr', LogisticRegression())])
pipe.fit(X_train, y_train)
score = pipe.score(X_test, y_test)
"""),

    ("clean_correct_03_imputer_train_only", """
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
imp = SimpleImputer(strategy='median')
X_train_clean = imp.fit_transform(X_train)
X_test_clean = imp.transform(X_test)
"""),

    ("clean_correct_04_pca_after_split", """
from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
pca = PCA(n_components=10)
X_train_pca = pca.fit_transform(X_train)
X_test_pca = pca.transform(X_test)
"""),

    ("clean_correct_05_minmax_after_split", """
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
mm = MinMaxScaler()
X_train_mm = mm.fit_transform(X_train)
X_test_mm = mm.transform(X_test)
"""),

    ("clean_correct_06_cv_pipeline", """
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.ensemble import RandomForestClassifier
pipe = Pipeline([('scaler', StandardScaler()), ('rf', RandomForestClassifier())])
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
scores = cross_val_score(pipe, X, y, cv=cv, scoring='roc_auc')
"""),

    ("clean_correct_07_make_pipeline", """
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = make_pipeline(StandardScaler(), SVC())
model.fit(X_train, y_train)
"""),

    ("clean_correct_08_column_transformer", """
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
ct = ColumnTransformer([('num', StandardScaler(), num_cols), ('cat', OneHotEncoder(), cat_cols)])
X_train_t = ct.fit_transform(X_train)
X_test_t = ct.transform(X_test)
"""),

    ("clean_correct_09_smote_train_only", """
from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
sm = SMOTE(random_state=42)
X_train_res, y_train_res = sm.fit_resample(X_train, y_train)
"""),

    ("clean_correct_10_threshold_on_valid", """
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, thresholds = roc_curve(y_valid, y_pred_valid)
best = thresholds[(tpr - fpr).argmax()]
"""),

    # === Legitimate patterns that look suspicious (15 variants) ===
    ("clean_legit_01_label_encoder_target", """
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
le = LabelEncoder()
y_encoded = le.fit_transform(y)
X_train, X_test, y_train, y_test = train_test_split(X, y_encoded)
"""),

    ("clean_legit_02_roc_curve_eval_only", """
from sklearn.metrics import roc_curve, roc_auc_score
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, _ = roc_curve(y_test, y_pred)
auc = roc_auc_score(y_test, y_pred)
import matplotlib.pyplot as plt
plt.plot(fpr, tpr)
"""),

    ("clean_legit_03_roc_curve_thresh_unused", """
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, thresholds = roc_curve(y_test, y_scores)
plt.plot(fpr, tpr, label=f'AUC={auc:.3f}')
"""),

    ("clean_legit_04_model_fit_is_training", """
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
clf = RandomForestClassifier()
clf.fit(X_train, y_train)
y_pred = clf.predict(X_test)
"""),

    ("clean_legit_05_xgb_early_stop_valid", """
import xgboost as xgb
from sklearn.model_selection import train_test_split
X_train, X_valid, y_train, y_valid = train_test_split(X, y)
model = xgb.XGBClassifier(early_stopping_rounds=10)
model.fit(X_train, y_train, eval_set=[(X_valid, y_valid)])
"""),

    ("clean_legit_06_tsne_visualization", """
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
tsne = TSNE(n_components=2)
X_2d = tsne.fit_transform(X)
plt.scatter(X_2d[:, 0], X_2d[:, 1], c=y)
"""),

    ("clean_legit_07_dropna_is_row_removal", """
from sklearn.model_selection import train_test_split
import pandas as pd
df = pd.read_csv("data.csv")
df = df.dropna(subset=["target"])
X_train, X_test, y_train, y_test = train_test_split(df.drop(columns=['target']), df['target'])
"""),

    ("clean_legit_08_ordinal_encoder_target", """
from sklearn.preprocessing import OrdinalEncoder
from sklearn.model_selection import train_test_split
enc = OrdinalEncoder()
y_enc = enc.fit_transform(y.values.reshape(-1, 1)).ravel()
X_train, X_test, y_train, y_test = train_test_split(X, y_enc)
"""),

    ("clean_legit_09_separate_validation_set", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.4)
X_valid, X_test, y_valid, y_test = train_test_split(X_temp, y_temp, test_size=0.5)
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_valid_s = scaler.transform(X_valid)
X_test_s = scaler.transform(X_test)
"""),

    ("clean_legit_10_feature_importance", """
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
rf = RandomForestClassifier()
rf.fit(X_train, y_train)
importances = rf.feature_importances_
"""),

    # === More clean patterns (20) ===
    ("clean_correct_11_robust_scaler", """
from sklearn.preprocessing import RobustScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
rs = RobustScaler()
X_train_r = rs.fit_transform(X_train)
X_test_r = rs.transform(X_test)
"""),

    ("clean_correct_12_kfold_inside_pipeline", """
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score, KFold
from sklearn.linear_model import LogisticRegression
pipe = Pipeline([('scaler', StandardScaler()), ('lr', LogisticRegression())])
scores = cross_val_score(pipe, X, y, cv=KFold(5, shuffle=True, random_state=0))
"""),

    ("clean_correct_13_imblearn_pipeline", """
from imblearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from imblearn.over_sampling import SMOTE
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
pipe = Pipeline([('scaler', StandardScaler()), ('smote', SMOTE()), ('rf', RandomForestClassifier())])
pipe.fit(X_train, y_train)
"""),

    ("clean_correct_14_target_encoder_sklearn", """
from sklearn.preprocessing import TargetEncoder
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
te = TargetEncoder()
X_train_e = te.fit_transform(X_train, y_train)
X_test_e = te.transform(X_test)
"""),

    ("clean_correct_15_gridsearch_cv", """
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
X_train, X_test, y_train, y_test = train_test_split(X, y)
pipe = Pipeline([('scaler', StandardScaler()), ('svc', SVC())])
gs = GridSearchCV(pipe, {'svc__C': [0.1, 1, 10]}, cv=5)
gs.fit(X_train, y_train)
"""),

    ("clean_legit_11_roc_multiple_models", """
from sklearn.metrics import roc_curve, auc
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
for name, model in models.items():
    y_pred = model.predict_proba(X_test)[:, 1]
    fpr, tpr, _ = roc_curve(y_test, y_pred)
    plt.plot(fpr, tpr, label=f'{name} AUC={auc(fpr, tpr):.3f}')
"""),

    ("clean_legit_12_calibration_plot", """
from sklearn.calibration import calibration_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
prob_true, prob_pred = calibration_curve(y_test, y_scores, n_bins=10)
"""),

    ("clean_legit_13_confusion_matrix", """
from sklearn.metrics import confusion_matrix, classification_report
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
y_pred = model.predict(X_test)
cm = confusion_matrix(y_test, y_pred)
print(classification_report(y_test, y_pred))
"""),

    ("clean_legit_14_shap_explanation", """
import shap
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
model.fit(X_train, y_train)
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_test)
"""),

    ("clean_legit_15_bootstrap_ci", """
from sklearn.utils import resample
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
aucs = []
for i in range(1000):
    idx = resample(range(len(y_test)), random_state=i)
    aucs.append(roc_auc_score(y_test.iloc[idx], y_scores[idx]))
ci_lower, ci_upper = np.percentile(aucs, [2.5, 97.5])
"""),

    ("clean_correct_16_nested_cv", """
from sklearn.model_selection import cross_val_score, StratifiedKFold, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
inner_cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
outer_cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
pipe = Pipeline([('scaler', StandardScaler()), ('svc', SVC())])
gs = GridSearchCV(pipe, {'svc__C': [0.1, 1, 10]}, cv=inner_cv)
scores = cross_val_score(gs, X, y, cv=outer_cv, scoring='roc_auc')
"""),

    ("clean_correct_17_train_valid_test", """
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.3, random_state=42)
X_valid, X_test, y_valid, y_test = train_test_split(X_temp, y_temp, test_size=0.5, random_state=42)
scaler = StandardScaler().fit(X_train)
X_train, X_valid, X_test = [scaler.transform(d) for d in [X_train, X_valid, X_test]]
model = GradientBoostingClassifier()
model.fit(X_train, y_train)
"""),

    ("clean_correct_18_predefined_split", """
from sklearn.preprocessing import StandardScaler
import pandas as pd
train = pd.read_csv('train.csv')
test = pd.read_csv('test.csv')
scaler = StandardScaler()
X_train = scaler.fit_transform(train.drop(columns=['target']))
X_test = scaler.transform(test.drop(columns=['target']))
"""),

    ("clean_correct_19_iterative_imputer_correct", """
from sklearn.experimental import enable_iterative_imputer
from sklearn.impute import IterativeImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
imp = IterativeImputer(random_state=42)
X_train_imp = imp.fit_transform(X_train)
X_test_imp = imp.transform(X_test)
"""),

    ("clean_correct_20_feature_union", """
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
features = FeatureUnion([('pca', PCA(n_components=5)), ('scaler', StandardScaler())])
pipe = Pipeline([('features', features), ('lr', LogisticRegression())])
pipe.fit(X_train, y_train)
"""),
]

# Flexible counts — ensure reasonable coverage
print(f"Leaky: {len(LEAKY)}, Clean: {len(CLEAN)}, Total: {len(LEAKY)+len(CLEAN)}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []

    for name, rule, code in LEAKY:
        path = OUT_DIR / f"{name}.py"
        path.write_text(code.strip() + "\n", encoding="utf-8")
        manifest.append({
            "file": name + ".py",
            "ground_truth": "leakage",
            "expected_rule": rule,
            "category": "leaky",
        })

    for name, code in CLEAN:
        path = OUT_DIR / f"{name}.py"
        path.write_text(code.strip() + "\n", encoding="utf-8")
        manifest.append({
            "file": name + ".py",
            "ground_truth": "clean",
            "expected_rule": None,
            "category": "clean",
        })

    manifest_path = OUT_DIR.parent / "benchmark_manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Generated {len(LEAKY)} leaky + {len(CLEAN)} clean = {len(manifest)} snippets")
    print(f"Output: {OUT_DIR}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
