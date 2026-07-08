import os
import sqlite3
import json
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from knowledge_map.core.relevance import deserialize_embedding

DEFAULT_DB_PATH = "document_store.db"
WEIGHTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "src",
    "knowledge_map",
    "resources",
    "classifier_weights.json"
)

def train_classifier(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Pulls labeled articles with embeddings from the SQLite database,
    trains a Logistic Regression model, and exports weights.
    """
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT embedding, relevance_status
            FROM scraped_html_cache
            WHERE relevance_status IN ('RELEVANT', 'IRRELEVANT')
              AND embedding IS NOT NULL
        """)
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print("No labeled articles with embeddings found in the database. Cannot train.")
        return

    X = []
    y = []
    for emb_blob, status in rows:
        emb = deserialize_embedding(emb_blob)
        if emb:
            X.append(emb)
            y.append(1 if status == 'RELEVANT' else 0)

    X = np.array(X)
    y = np.array(y)

    unique_classes = np.unique(y)
    if len(unique_classes) < 2:
        print(f"Cannot train Logistic Regression: training data only contains class {unique_classes}. Both RELEVANT and IRRELEVANT examples are required.")
        return

    print(f"Found {len(X)} samples for training.")
    
    # Train Logistic Regression model
    model = LogisticRegression(max_iter=1000, C=1.0)
    model.fit(X, y)

    # Evaluate on the training set (or print basic classification report)
    y_pred = model.predict(X)
    print("\n--- Training Set Evaluation Report ---")
    print(classification_report(y, y_pred, target_names=["IRRELEVANT", "RELEVANT"]))

    # Export weights
    weights = {
        "coefficients": model.coef_[0].tolist(),
        "intercept": model.intercept_.tolist(),
        "n_samples": len(X)
    }

    # Ensure the directory exists
    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(weights, f, indent=2)

    print(f"Successfully exported model weights to: {WEIGHTS_PATH}")
