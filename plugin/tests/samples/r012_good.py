# GOOD: roc_auc scoring on imbalanced data
from sklearn.model_selection import GridSearchCV
from sklearn.ensemble import RandomForestClassifier
from imblearn.over_sampling import SMOTE

smote = SMOTE()
X_res, y_res = smote.fit_resample(X, y)
grid = GridSearchCV(RandomForestClassifier(), param_grid={"n_estimators": [50, 100]}, scoring="roc_auc")
