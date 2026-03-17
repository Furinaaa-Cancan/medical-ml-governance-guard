# GOOD: scaling with distance-based model (SVM), not tree-based
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_train)
clf = SVC(kernel="rbf")
clf.fit(X_scaled, y_train)
