# GOOD: metrics on test data
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# Final evaluation on test set — correct
test_acc = accuracy_score(y_test, model.predict(X_test))
print(f"Test accuracy: {test_acc}")
