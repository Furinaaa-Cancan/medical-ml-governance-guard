# BAD: early stopping on test data hidden in a NESTED container.
# The old one-level List/Tuple scan only looked at top-level tuples, so this
# nested form slipped through; the recursive walk catches X_test/y_test.
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split

X = [[0.0, 1.0], [1.0, 0.0]]
y = [0, 1]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
model = XGBClassifier(n_estimators=1000)
model.fit(X_train, y_train, eval_set=[[(X_test, y_test)]], early_stopping_rounds=10)
