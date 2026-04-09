"""Red Team R2 #15: SMOTE inside CV loop but outside imblearn Pipeline."""
import pandas as pd
import numpy as np
from sklearn.model_selection import StratifiedKFold
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from imblearn.over_sampling import SMOTE

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"])
y = df["outcome"]

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
aurocs = []

for train_idx, val_idx in cv.split(X, y):
    X_train_fold, y_train_fold = X.iloc[train_idx], y.iloc[train_idx]
    X_val_fold, y_val_fold = X.iloc[val_idx], y.iloc[val_idx]

    # BUG: SMOTE applied inside CV but NOT inside imblearn Pipeline
    # The scaler should also be fitted per fold, not globally
    sm = SMOTE(random_state=42)
    X_res, y_res = sm.fit_resample(X_train_fold, y_train_fold)

    model = LogisticRegression(max_iter=1000, random_state=42)
    model.fit(X_res, y_res)
    y_prob = model.predict_proba(X_val_fold)[:, 1]
    aurocs.append(roc_auc_score(y_val_fold, y_prob))

print(f"CV AUROC: {np.mean(aurocs):.4f} ± {np.std(aurocs):.4f}")
