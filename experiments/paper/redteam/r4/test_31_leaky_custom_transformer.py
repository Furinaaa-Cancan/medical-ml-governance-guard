"""Red Team R4 #31: Custom transformer that secretly fits on full data inside Pipeline.
Pipeline looks correct but the custom step cheats."""
import pandas as pd
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

# BUG: This custom transformer stores global stats in __init__ before Pipeline.fit()
class LeakyImputer(BaseEstimator, TransformerMixin):
    """Looks like a proper sklearn transformer, but cheats."""
    def __init__(self, global_medians=None):
        self.global_medians = global_medians  # BUG: pre-computed on full data

    def fit(self, X, y=None):
        # Appears to fit on training data, but actually uses pre-computed global stats
        if self.global_medians is not None:
            self.medians_ = self.global_medians  # BUG: ignores fit data
        else:
            self.medians_ = np.nanmedian(X, axis=0)
        return self

    def transform(self, X):
        X = X.copy()
        for i in range(X.shape[1]):
            mask = np.isnan(X[:, i])
            X[mask, i] = self.medians_[i]
        return X

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"]).values
y = df["outcome"].values

# BUG: global medians computed on full data, passed to custom transformer
full_medians = np.nanmedian(X, axis=0)

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

pipe = Pipeline([
    ("imputer", LeakyImputer(global_medians=full_medians)),  # BUG: uses full-data stats
    ("scaler", StandardScaler()),
    ("model", LogisticRegression(max_iter=1000, random_state=42)),
])

pipe.fit(X_train, y_train)
y_prob = pipe.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
