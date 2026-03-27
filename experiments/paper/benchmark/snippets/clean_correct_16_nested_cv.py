from sklearn.model_selection import cross_val_score, StratifiedKFold, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
inner_cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
outer_cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
pipe = Pipeline([('scaler', StandardScaler()), ('svc', SVC())])
gs = GridSearchCV(pipe, {'svc__C': [0.1, 1, 10]}, cv=inner_cv)
scores = cross_val_score(gs, X, y, cv=outer_cv, scoring='roc_auc')
