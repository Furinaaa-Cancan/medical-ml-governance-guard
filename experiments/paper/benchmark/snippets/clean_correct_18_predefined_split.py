from sklearn.preprocessing import StandardScaler
import pandas as pd
train = pd.read_csv('train.csv')
test = pd.read_csv('test.csv')
scaler = StandardScaler()
X_train = scaler.fit_transform(train.drop(columns=['target']))
X_test = scaler.transform(test.drop(columns=['target']))
