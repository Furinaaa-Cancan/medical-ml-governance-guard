"""Sample: TCGA-style gene expression features — MLGG out of scope."""
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

df = pd.read_csv("tcga_brca.csv")
features = [
    "gene_BRCA1",
    "gene_TP53",
    "gene_EGFR",
    "gene_KRAS",
    "gene_PTEN",
]
X = df[features]
y = df["outcome"]

clf = RandomForestClassifier(random_state=42)
clf.fit(X, y)
