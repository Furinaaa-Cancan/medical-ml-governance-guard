from sklearn.model_selection import train_test_split
import xgboost as xgb
X = patient_data
y = patient_data['mortality']
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = xgb.XGBClassifier()
model.fit(X_train, y_train)
