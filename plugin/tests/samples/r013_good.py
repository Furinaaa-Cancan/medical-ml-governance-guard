# GOOD: threshold tuned on validation data
from sklearn.metrics import roc_curve
import numpy as np

fpr, tpr, thresholds = roc_curve(y_valid, y_prob_valid)
optimal_idx = np.argmax(tpr - fpr)
optimal_threshold = thresholds[optimal_idx]
y_pred = (y_prob_test > optimal_threshold).astype(int)
