# BAD: target column included in feature list selection
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

X = df[['age', 'bmi', 'target', 'blood_pressure']]
y = df['target']
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = RandomForestClassifier()
model.fit(X_train, y_train)
