# GOOD: CatBoost eval_set with validation data (not test)
from catboost import CatBoostClassifier
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y)
model = CatBoostClassifier(iterations=500, early_stopping_rounds=20)
model.fit(X_train, y_train, eval_set=(X_valid, y_valid))  # OK: validation data
