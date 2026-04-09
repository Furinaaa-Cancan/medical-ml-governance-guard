"""Red Team #6 (HARD): Leakage hidden inside helper function."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score


def preprocess(data):
    """Innocent-looking preprocessing function."""
    scaler = StandardScaler()
    numeric_cols = data.select_dtypes(include=[np.number]).columns
    data[numeric_cols] = scaler.fit_transform(data[numeric_cols])
    return data  # BUG: scaler fit on whatever data is passed — caller passes full data


def build_model(csv_path):
    df = pd.read_csv(csv_path)
    df = preprocess(df)  # BUG: preprocessing BEFORE split, hidden in function call

    X = df.drop(columns=["patient_id", "readmission_30d"])
    y = df["readmission_30d"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)
    y_prob = model.predict_proba(X_test)[:, 1]
    print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")


build_model("diabetes_readmission.csv")
