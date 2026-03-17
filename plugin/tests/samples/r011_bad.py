# BAD: SMOTE outside imblearn.Pipeline with cross-validation
from imblearn.over_sampling import SMOTE
from sklearn.model_selection import cross_val_score
from sklearn.ensemble import RandomForestClassifier

sm = SMOTE()
X_res, y_res = sm.fit_resample(X, y)
scores = cross_val_score(RandomForestClassifier(), X_res, y_res, scoring='roc_auc')
