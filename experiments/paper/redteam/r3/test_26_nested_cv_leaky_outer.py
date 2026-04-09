"""Red Team R3 #26: Nested CV but feature selection done on entire outer fold."""
import pandas as pd
import numpy as np
from sklearn.model_selection import StratifiedKFold
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"]).values
y = df["outcome"].values

outer_cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
outer_scores = []

for train_idx, test_idx in outer_cv.split(X, y):
    X_outer_train, y_outer_train = X[train_idx], y[train_idx]
    X_outer_test, y_outer_test = X[test_idx], y[test_idx]

    # BUG: feature selection on full outer training fold (not inner CV)
    # This is a subtle issue — many papers do this thinking it's correct
    # because it's "within the CV fold", but SelectKBest.fit uses y which
    # means the selected features are influenced by all train samples
    # including those that will serve as inner-CV validation
    selector = SelectKBest(f_classif, k=10)
    X_selected_train = selector.fit_transform(X_outer_train, y_outer_train)
    X_selected_test = selector.transform(X_outer_test)

    model = LogisticRegression(max_iter=1000, random_state=42)
    model.fit(X_selected_train, y_outer_train)
    y_prob = model.predict_proba(X_selected_test)[:, 1]
    outer_scores.append(roc_auc_score(y_outer_test, y_prob))

print(f"Nested CV AUROC: {np.mean(outer_scores):.4f} ± {np.std(outer_scores):.4f}")
