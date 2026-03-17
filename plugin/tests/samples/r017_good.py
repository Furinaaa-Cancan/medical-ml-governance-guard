# GOOD: early stopping on dedicated tuning set (not test/valid holdout)
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
# Split training into train + tuning (for early stopping)
X_trn, X_tune, y_trn, y_tune = train_test_split(X_train, y_train, test_size=0.2)
model = XGBClassifier(n_estimators=1000)
model.fit(X_trn, y_trn, eval_set=[(X_tune, y_tune)], early_stopping_rounds=10)
