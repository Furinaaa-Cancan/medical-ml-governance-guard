from imblearn.over_sampling import ADASYN
from sklearn.model_selection import train_test_split
ada = ADASYN()
X_res, y_res = ada.fit_resample(X_all, y_all)
X_train, X_test, y_train, y_test = train_test_split(X_res, y_res)
