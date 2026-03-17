# GOOD: SMOTE wrapped in imblearn.Pipeline with cross-validation
from imblearn.pipeline import Pipeline
from imblearn.over_sampling import SMOTE
from sklearn.model_selection import cross_val_score
from sklearn.ensemble import RandomForestClassifier

pipe = Pipeline([
    ("smote", SMOTE()),
    ("clf", RandomForestClassifier()),
])
scores = cross_val_score(pipe, X, y, scoring='roc_auc')
