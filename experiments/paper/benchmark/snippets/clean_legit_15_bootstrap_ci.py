from sklearn.utils import resample
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
aucs = []
for i in range(1000):
    idx = resample(range(len(y_test)), random_state=i)
    aucs.append(roc_auc_score(y_test.iloc[idx], y_scores[idx]))
ci_lower, ci_upper = np.percentile(aucs, [2.5, 97.5])
