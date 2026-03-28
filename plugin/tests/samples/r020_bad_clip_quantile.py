# BAD: clip with quantile bounds on full data before split
import pandas as pd
from sklearn.model_selection import train_test_split

df = pd.read_csv("data.csv")
for col in df.select_dtypes(include='number').columns:
    df[col] = df[col].clip(lower=df[col].quantile(0.01), upper=df[col].quantile(0.99))
X_train, X_test, y_train, y_test = train_test_split(df.drop(columns=['target']), df['target'])
