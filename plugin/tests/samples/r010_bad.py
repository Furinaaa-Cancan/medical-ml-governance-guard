# BAD: reporting training metrics as final
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# ... model.fit(X_train, y_train) ...
train_acc = accuracy_score(y_train, model.predict(X_train))
print(f"Final accuracy: {train_acc}")
