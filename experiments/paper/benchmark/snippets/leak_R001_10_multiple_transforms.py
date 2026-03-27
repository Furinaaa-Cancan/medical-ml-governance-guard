from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.impute import SimpleImputer
imp = SimpleImputer().fit_transform(X)
scaled = StandardScaler().fit_transform(imp)
normed = MinMaxScaler().fit_transform(scaled)
X_train, X_test, y_train, y_test = train_test_split(normed, y)
