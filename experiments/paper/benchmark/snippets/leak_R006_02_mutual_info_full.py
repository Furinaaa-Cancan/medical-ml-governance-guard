from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.model_selection import train_test_split
fs = SelectKBest(mutual_info_classif, k=20)
X_fs = fs.fit_transform(X_all, y_all)
X_train, X_test, y_train, y_test = train_test_split(X_fs, y_all)
