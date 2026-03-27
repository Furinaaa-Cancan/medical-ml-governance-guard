from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
pca = PCA(n_components=10)
X_pca = pca.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_pca, y, test_size=0.2)
