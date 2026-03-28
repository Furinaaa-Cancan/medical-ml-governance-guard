# GOOD: fit_transform in a utility file with no train_test_split
# R001 should NOT flag this — the split happens in another file.
from sklearn.preprocessing import StandardScaler

def preprocess(data):
    scaler = StandardScaler()
    return scaler.fit_transform(data)
