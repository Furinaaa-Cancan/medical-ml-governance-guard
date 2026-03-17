# BAD: scaling before tree-based model
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_train)
clf = RandomForestClassifier(n_estimators=100)
clf.fit(X_scaled, y_train)
