from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
tfidf = TfidfVectorizer(max_features=1000)
X_tfidf = tfidf.fit_transform(text_data)
X_train, X_test, y_train, y_test = train_test_split(X_tfidf, labels)
