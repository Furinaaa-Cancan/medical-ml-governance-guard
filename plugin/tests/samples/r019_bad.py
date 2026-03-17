# BAD: multiple models compared without correction
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC

model1 = LogisticRegression()
model2 = RandomForestClassifier()
model3 = GradientBoostingClassifier()
model4 = SVC()
