# GOOD: metrics with bootstrap confidence intervals
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from scipy.stats import bootstrap
import numpy as np

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

acc = accuracy_score(y_test, y_pred)
auc = roc_auc_score(y_test, y_prob)

# Bootstrap CI
rng = np.random.default_rng(42)
ci = bootstrap((y_test, y_prob), statistic=roc_auc_score, random_state=rng)
