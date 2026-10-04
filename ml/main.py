from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PrediDBOS ML Service")

DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),
    'database': os.getenv('POSTGRES_DB', 'predidbos'),
    'user': os.getenv('POSTGRES_USER', 'predidbos'),
    'password': os.getenv('POSTGRES_PASSWORD', 'predidbos'),
}

MODEL_PATH = '/app/saved_model/model.joblib'
ENCODER_PATH = '/app/saved_model/encoders.joblib'

model = None
encoders = {}
feature_columns = ['prev_object_1', 'prev_object_2', 'prev_object_3', 'prev_object_4', 'hour', 'query_type_encoded']
target_encoder = None

class PredictionRequest(BaseModel):
    recent_objects: List[str]
    query_type: Optional[str] = 'SELECT'
    hour: Optional[int] = None

class PredictionResponse(BaseModel):
    predicted_object: str
    confidence: float
    access_pattern: Optional[str] = None
    all_probabilities: Optional[Dict[str, float]] = None

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def load_model():
    global model, encoders, target_encoder
    try:
        if os.path.exists(MODEL_PATH) and os.path.exists(ENCODER_PATH):
            model = joblib.load(MODEL_PATH)
            encoders = joblib.load(ENCODER_PATH)
            target_encoder = encoders.get('target')
            logger.info("Model loaded successfully")
            return True
    except Exception as e:
        logger.warning(f"Could not load model: {e}")
    return False

def prepare_training_data():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT object_name, "timestamp" as ts, query_type
                FROM workload_history
                WHERE object_name IS NOT NULL
                  AND "timestamp" IS NOT NULL
                ORDER BY "timestamp" ASC
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    if len(rows) < 10:
        return None

    # Create DataFrame manually from rows
    df = pd.DataFrame(rows, columns=['object_name', 'ts', 'query_type'])
    
    logger.info(f"DataFrame columns: {df.columns.tolist()}")
    logger.info(f"DataFrame shape: {df.shape}")
    logger.info(f"Sample ts values: {df['ts'].head().tolist()}")
    logger.info(f"ts dtype: {df['ts'].dtype}")

    # Convert ts to datetime
    df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce')
    df = df.dropna(subset=['ts'])
    
    if len(df) < 10:
        return None

    df['hour'] = df['ts'].dt.hour
    df['query_type_encoded'] = df['query_type'].astype('category').cat.codes

    objects = df['object_name'].unique()
    obj_to_idx = {obj: i for i, obj in enumerate(objects)}
    idx_to_obj = {i: obj for i, obj in enumerate(objects)}

    df['object_idx'] = df['object_name'].map(obj_to_idx)

    for i in range(1, 5):
        df[f'prev_object_{i}'] = df['object_idx'].shift(i)

    df['target'] = df['object_idx'].shift(-1)
    df = df.dropna()

    if len(df) == 0:
        return None

    X = df[feature_columns]
    y = df['target'].astype(int)

    return (X, y, obj_to_idx, idx_to_obj)

def train_model():
    global model, encoders, target_encoder
    result = prepare_training_data()
    if result is None:
        logger.warning("Insufficient data for training")
        return False

    X, y, obj_to_idx, idx_to_obj = result

    encoders = {
        'obj_to_idx': obj_to_idx,
        'idx_to_obj': idx_to_obj,
        'target': LabelEncoder().fit(y),
    }
    y_encoded = encoders['target'].transform(y)

    model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    model.fit(X, y_encoded)

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(encoders, ENCODER_PATH)

    # Save model metadata to database
    save_model_metadata(len(X), len(obj_to_idx))

    logger.info(f"Model trained on {len(X)} samples, {len(obj_to_idx)} objects")
    return True

def save_model_metadata(training_samples: int, num_objects: int):
    conn = get_db_connection()
    try:
        model_version = f"rf_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO model_metadata (model_version, model_type, trained_at, training_samples, features, hyperparameters, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                model_version,
                'random_forest',
                datetime.utcnow(),
                training_samples,
                json.dumps(feature_columns),
                json.dumps({'n_estimators': 100, 'max_depth': 10, 'random_state': 42}),
                True
            ))
            # Deactivate other models
            cur.execute("UPDATE model_metadata SET is_active = FALSE WHERE model_version != %s", (model_version,))
        conn.commit()
        logger.info(f"Model metadata saved: {model_version}")
    except Exception as e:
        logger.error(f"Failed to save model metadata: {e}")
    finally:
        conn.close()

def encode_features(recent_objects: List[str], query_type: str, hour: int):
    obj_to_idx = encoders.get('obj_to_idx', {})
    encoded = [obj_to_idx.get(obj, -1) for obj in recent_objects[-4:]]
    while len(encoded) < 4:
        encoded.insert(0, -1)
    encoded = encoded[-4:]

    query_types = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DDL', 'UTILITY']
    qt_encoded = query_types.index(query_type) if query_type in query_types else 0

    return np.array([encoded + [hour, qt_encoded]])

@app.on_event("startup")
async def startup():
    load_model()
    if not train_model():
        logger.info("Model not trained yet - waiting for data")

@app.get("/health")
async def health():
    return {
        "status": "healthy" if model else "degraded",
        "model_loaded": model is not None,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/model/status")
async def model_status():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM model_metadata ORDER BY trained_at DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else {}
    finally:
        conn.close()

@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    if not model:
        raise HTTPException(status_code=503, detail="Model not trained yet")

    hour = request.hour if request.hour is not None else datetime.utcnow().hour
    X = encode_features(request.recent_objects, request.query_type, hour)

    try:
        probas = model.predict_proba(X)[0]
        pred_idx = np.argmax(probas)
        confidence = float(probas[pred_idx])

        idx_to_obj = encoders.get('idx_to_obj', {})
        predicted_object = idx_to_obj.get(pred_idx, 'unknown')

        all_probs = {}
        for idx, prob in enumerate(probas):
            obj = idx_to_obj.get(idx)
            if obj and prob > 0.01:
                all_probs[obj] = float(prob)

        access_pattern = 'sequential'
        if 'index' in predicted_object.lower() or 'pk' in predicted_object.lower():
            access_pattern = 'index'
        elif predicted_object.endswith('_log') or predicted_object.endswith('_audit'):
            access_pattern = 'sequential'

        return PredictionResponse(
            predicted_object=predicted_object,
            confidence=confidence,
            access_pattern=access_pattern,
            all_probabilities=all_probs
        )
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/train")
async def train_endpoint():
    success = train_model()
    if success:
        return {"status": "trained", "timestamp": datetime.utcnow().isoformat()}
    else:
        raise HTTPException(status_code=400, detail="Insufficient data for training")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)