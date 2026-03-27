from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X = {}; y = {}
X['train'], X['test'], y['train'], y['test'] = train_test_split(X_all, y_all)
preprocess = StandardScaler().fit(X['train'])
X = {k: preprocess.fit_transform(v) for k, v in X.items()}
