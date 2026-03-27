from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
features = FeatureUnion([('pca', PCA(n_components=5)), ('scaler', StandardScaler())])
pipe = Pipeline([('features', features), ('lr', LogisticRegression())])
pipe.fit(X_train, y_train)
