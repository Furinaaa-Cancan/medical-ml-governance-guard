from sklearn.metrics import roc_curve, roc_auc_score
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, _ = roc_curve(y_test, y_pred)
auc = roc_auc_score(y_test, y_pred)
import matplotlib.pyplot as plt
plt.plot(fpr, tpr)
