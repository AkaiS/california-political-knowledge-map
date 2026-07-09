import os
import sqlite3
import json
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
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
              AND relevance_label_source IN ('HUMAN', 'LLM')
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
    
    if len(X) < 5:
        print(f"Cannot train Logistic Regression: insufficient data to train model. Only {len(X)} samples available.")
        return

    unique_classes, counts = np.unique(y, return_counts=True)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"Split dataset into {len(X_train)} training samples and {len(X_test)} test samples.")
    
    # Train model on training split
    model = LogisticRegression(max_iter=1000, C=1.0)
    model.fit(X_train, y_train)
    
    # Evaluate on the training set
    y_train_pred = model.predict(X_train)
    print("\n--- Training Set Evaluation Report ---")
    print(classification_report(y_train, y_train_pred, target_names=["IRRELEVANT", "RELEVANT"], zero_division=0))
    
    # Evaluate on the test set
    y_test_pred = model.predict(X_test)
    print("\n--- Test Set Evaluation Report ---")
    print(classification_report(y_test, y_test_pred, target_names=["IRRELEVANT", "RELEVANT"], zero_division=0))
    
    # Retrain on the entire dataset for final model weights export
    print(f"\nRetraining final model on all {len(X)} samples for weights export...")
    final_model = LogisticRegression(max_iter=1000, C=1.0)
    final_model.fit(X, y)

    # Export weights of the final model trained on all available data
    weights = {
        "coefficients": final_model.coef_[0].tolist(),
        "intercept": final_model.intercept_.tolist(),
        "n_samples": len(X)
    }

    # Ensure the directory exists
    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(weights, f, indent=2)

    print(f"Successfully exported model weights to: {WEIGHTS_PATH}")
