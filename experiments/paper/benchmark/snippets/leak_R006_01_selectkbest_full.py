from sklearn.feature_selection import SelectKBest, chi2
from sklearn.model_selection import train_test_split
selector = SelectKBest(chi2, k=10)
X_selected = selector.fit_transform(X, y)
X_train, X_test, y_train, y_test = train_test_split(X_selected, y)
