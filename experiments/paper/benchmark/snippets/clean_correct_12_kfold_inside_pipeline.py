from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score, KFold
from sklearn.linear_model import LogisticRegression
pipe = Pipeline([('scaler', StandardScaler()), ('lr', LogisticRegression())])
scores = cross_val_score(pipe, X, y, cv=KFold(5, shuffle=True, random_state=0))
