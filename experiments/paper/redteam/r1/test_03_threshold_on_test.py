"""Red Team #3: Threshold selected on test set."""
import numpy as np
from sklearn.metrics import roc_curve, roc_auc_score
from sklearn.linear_model import LogisticRegression

# Assume X_train, y_train, X_test, y_test already split
model = LogisticRegression()
model.fit(X_train, y_train)

y_prob_test = model.predict_proba(X_test)[:, 1]
fpr, tpr, thresholds = roc_curve(y_test, y_prob_test)
best_idx = np.argmax(tpr - fpr)
optimal_threshold = thresholds[best_idx]  # BUG: threshold from test set

y_pred = (y_prob_test >= optimal_threshold).astype(int)
print(f"AUROC: {roc_auc_score(y_test, y_prob_test):.4f}")
