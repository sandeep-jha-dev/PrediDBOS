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
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, classification_report, confusion_matrix
import logging

from calibration import load_calibrator, apply_calibration, CALIBRATION_PATH, CALIBRATION_METADATA_PATH

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

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'saved_model')
MODEL_PATH = os.path.join(MODEL_DIR, 'model.joblib')
ENCODER_PATH = os.path.join(MODEL_DIR, 'encoders.joblib')

model = None
encoders = {}
feature_columns = ['current_object', 'prev_object_1', 'prev_object_2', 'prev_object_3', 'hour', 'query_type_encoded']
target_encoder = None

calibrator = None
calibration_metadata = None
calibration_enabled = False

INTERNAL_OBJECTS = {
    'performance_results', 'predictions', 'decisions', 'os_state',
    'model_metadata', 'workload_history', 'generate_series',
    'pg_class', 'pg_database', 'pg_catalog', 'pg_attribute',
    'pg_proc', 'pg_type', 'pg_namespace', 'pg_index', 'pg_stat_statements',
    'information_schema'
}

PG_SYSTEM_PREFIXES = ('pg_', 'sql_', 'information_schema_')

QUERY_TYPE_MAP = {'SELECT': 0, 'INSERT': 1, 'UPDATE': 2, 'DELETE': 3, 'DDL': 4, 'UTILITY': 5}

UNK_TOKEN = '<UNK>'
UNK_IDX = -1

HOLDOUT_START = pd.Timestamp('2026-10-05 23:05:20+00:00', tz='UTC')

def is_internal_object(obj_name: str) -> bool:
    if obj_name in INTERNAL_OBJECTS:
        return True
    for prefix in PG_SYSTEM_PREFIXES:
        if obj_name.startswith(prefix):
            return True
    return False

class PredictionRequest(BaseModel):
    recent_objects: List[str]
    query_type: Optional[str] = 'SELECT'
    hour: Optional[int] = None

class PredictionResponse(BaseModel):
    predicted_object: str
    confidence: float
    raw_confidence: Optional[float] = None
    calibrated_confidence: Optional[float] = None
    access_pattern: Optional[str] = None
    all_probabilities: Optional[Dict[str, float]] = None
    raw_probabilities: Optional[Dict[str, float]] = None
    calibration_version: Optional[str] = None

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def load_model():
    global model, encoders, target_encoder, calibrator, calibration_metadata, calibration_enabled
    try:
        if os.path.exists(MODEL_PATH) and os.path.exists(ENCODER_PATH):
            model = joblib.load(MODEL_PATH)
            encoders = joblib.load(ENCODER_PATH)
            target_encoder = encoders.get('target')
            logger.info("Model loaded successfully")

            # Load calibrator if available
            from calibration import load_calibrator as load_cal
            if load_cal():
                # Get the loaded calibrator from the calibration module
                import calibration as cal_module
                calibrator = cal_module.calibrator
                calibration_metadata = cal_module.calibration_metadata
                if calibrator is not None and calibrator.is_fitted:
                    calibration_enabled = True
                    logger.info(f"Calibrator loaded: {calibration_metadata.get('calibration_version', 'unknown')}")
                else:
                    calibration_enabled = False
            else:
                calibration_enabled = False
                logger.info("No calibrator found - using raw probabilities")

            return True
    except Exception as e:
        logger.warning(f"Could not load model: {e}")
    return False

def prepare_user_sequence():
    """Load and filter workload history to user-only sequence, ordered chronologically."""
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

    df = pd.DataFrame(rows, columns=['object_name', 'ts', 'query_type'])
    df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce')
    df = df.dropna(subset=['ts'])

    if len(df) < 10:
        return None

    df['is_internal'] = df['object_name'].apply(is_internal_object)
    internal_count = df['is_internal'].sum()
    total_count = len(df)
    logger.info(f"Total workload rows: {total_count}, Internal: {internal_count} ({internal_count/total_count*100:.1f}%), User: {total_count-internal_count} ({(total_count-internal_count)/total_count*100:.1f}%)")

    df_user = df[~df['is_internal']].copy()

    if len(df_user) < 10:
        logger.warning("Insufficient user workload rows after filtering internal objects")
        return None

    logger.info(f"User-only sequence length: {len(df_user)}")

    df_user['hour'] = df_user['ts'].dt.hour
    df_user['query_type_encoded'] = df_user['query_type'].map(QUERY_TYPE_MAP).fillna(0).astype(int)

    historical = df_user[df_user['ts'] < HOLDOUT_START].copy()
    future_holdout = df_user[df_user['ts'] >= HOLDOUT_START].copy()

    logger.info(f"Historical data (before holdout): {len(historical)} rows")
    logger.info(f"Future holdout data (after holdout): {len(future_holdout)} rows")

    if len(historical) < 10:
        logger.warning("Insufficient historical data for training")
        return None

    n_historical = len(historical)
    train_end_idx = int(n_historical * 0.7)
    val_end_idx = int(n_historical * 0.85)

    df_train = historical.iloc[:train_end_idx].copy()
    df_val = historical.iloc[train_end_idx:val_end_idx].copy()
    df_test = historical.iloc[val_end_idx:].copy()

    logger.info(f"Chronological split within historical: Train={len(df_train)}, Val={len(df_val)}, Test(historical)={len(df_test)}")

    train_objects = df_train['object_name'].unique()
    obj_to_idx = {obj: i for i, obj in enumerate(train_objects)}
    obj_to_idx[UNK_TOKEN] = UNK_IDX
    idx_to_obj = {i: obj for obj, i in obj_to_idx.items()}

    def map_object(obj):
        return obj_to_idx.get(obj, UNK_IDX)

    for df_split in [df_train, df_val, df_test, future_holdout]:
        if len(df_split) > 0:
            df_split['object_idx'] = df_split['object_name'].map(map_object)
            df_split['current_object'] = df_split['object_idx']
            for i in range(1, 4):
                df_split[f'prev_object_{i}'] = df_split['object_idx'].shift(i)
            df_split['target'] = df_split['object_idx'].shift(-1)

    df_train = df_train.dropna()
    df_val = df_val.dropna()
    df_test = df_test.dropna()

    if len(df_train) == 0:
        logger.warning("Insufficient training samples after constructing temporal features")
        return None

    target_encoder = LabelEncoder().fit(df_train['target'])
    target_classes = target_encoder.classes_
    target_idx_to_obj = {i: idx_to_obj[idx] for i, idx in enumerate(target_classes)}

    df_train['target_encoded'] = target_encoder.transform(df_train['target'])
    df_val['target_encoded'] = target_encoder.transform(df_val['target'])
    df_test['target_encoded'] = target_encoder.transform(df_test['target'])

    X_train = df_train[feature_columns]
    y_train = df_train['target_encoded'].astype(int)
    X_val = df_val[feature_columns]
    y_val = df_val['target_encoded'].astype(int)
    X_test = df_test[feature_columns]
    y_test = df_test['target_encoded'].astype(int)

    logger.info(f"Train feature matrix shape: {X_train.shape}")
    logger.info(f"Val feature matrix shape: {X_val.shape}")
    logger.info(f"Historical test feature matrix shape: {X_test.shape}")
    logger.info(f"Target classes: {list(target_idx_to_obj.values())}")

    return (X_train, y_train, X_val, y_val, X_test, y_test, obj_to_idx, idx_to_obj, target_encoder, target_idx_to_obj, df_train, df_val, df_test, future_holdout)

def train_and_evaluate(X_train, y_train, X_val, y_val, target_idx_to_obj, class_weight=None):
    """Train model and evaluate on validation set only (not future holdout)."""
    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        random_state=42,
        n_jobs=-1,
        class_weight=class_weight
    )
    model.fit(X_train, y_train)

    y_val_pred = model.predict(X_val)
    val_accuracy = accuracy_score(y_val, y_val_pred)
    val_precision_w = precision_score(y_val, y_val_pred, average='weighted', zero_division=0)
    val_recall_w = recall_score(y_val, y_val_pred, average='weighted', zero_division=0)
    val_f1_w = f1_score(y_val, y_val_pred, average='weighted', zero_division=0)
    val_precision_m = precision_score(y_val, y_val_pred, average='macro', zero_division=0)
    val_recall_m = recall_score(y_val, y_val_pred, average='macro', zero_division=0)
    val_f1_m = f1_score(y_val, y_val_pred, average='macro', zero_division=0)

    metrics = {
        'validation': {
            'accuracy': float(val_accuracy),
            'precision_weighted': float(val_precision_w),
            'recall_weighted': float(val_recall_w),
            'f1_weighted': float(val_f1_w),
            'precision_macro': float(val_precision_m),
            'recall_macro': float(val_recall_m),
            'f1_macro': float(val_f1_m),
        }
    }

    return model, metrics

def train_model_clean():
    """Train with clean protocol: fixed future holdout, vocab from train only, validation-only model selection."""
    global model, encoders, target_encoder

    result = prepare_user_sequence()
    if result is None:
        logger.warning("Insufficient data for training")
        return False

    (X_train, y_train, X_val, y_val, X_test, y_test,
     obj_to_idx, idx_to_obj, target_encoder_fitted, target_idx_to_obj,
     df_train, df_val, df_test, future_holdout) = result

    for name, y_split in [('Train', y_train), ('Val', y_val), ('Historical_Test', y_test)]:
        dist = {}
        for idx, count in pd.Series(y_split).value_counts().items():
            dist[target_idx_to_obj[idx]] = int(count)
        logger.info(f"{name} class distribution: {dist}")

    logger.info("Training baseline Random Forest (class_weight=None)...")
    baseline_model, baseline_metrics = train_and_evaluate(
        X_train, y_train, X_val, y_val, target_idx_to_obj, class_weight=None
    )

    logger.info("Training class-weighted Random Forest (class_weight='balanced')...")
    weighted_model, weighted_metrics = train_and_evaluate(
        X_train, y_train, X_val, y_val, target_idx_to_obj, class_weight='balanced'
    )

    baseline_val_f1_macro = baseline_metrics['validation']['f1_macro']
    weighted_val_f1_macro = weighted_metrics['validation']['f1_macro']

    logger.info(f"Baseline val macro F1: {baseline_val_f1_macro:.4f}")
    logger.info(f"Weighted val macro F1: {weighted_val_f1_macro:.4f}")

    if weighted_val_f1_macro > baseline_val_f1_macro:
        selected_model = weighted_model
        selected_metrics = weighted_metrics
        selected_class_weight = 'balanced'
        logger.info("Selected: class-weighted model (higher validation macro F1)")
    else:
        selected_model = baseline_model
        selected_metrics = baseline_metrics
        selected_class_weight = None
        logger.info("Selected: baseline model (higher or equal validation macro F1)")

    model = selected_model
    target_encoder = target_encoder_fitted
    encoders = {
        'obj_to_idx': obj_to_idx,
        'idx_to_obj': idx_to_obj,
        'target': target_encoder_fitted,
        'target_idx_to_obj': target_idx_to_obj,
        'unk_token': UNK_TOKEN,
        'unk_idx': UNK_IDX,
    }

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(encoders, ENCODER_PATH)

    evaluation_metadata = {
        'split_protocol': 'fixed_future_holdout_chronological_70_15',
        'holdout_start_timestamp': HOLDOUT_START.isoformat(),
        'holdout_pristine': len(future_holdout) == 0,
        'train_ratio_historical': 0.7,
        'val_ratio_historical': 0.15,
        'historical_test_ratio': 0.15,
        'split_time_boundaries': {
            'historical_data_end': df_train.iloc[-1]['ts'].isoformat() if len(df_train) > 0 else None,
            'train_end': df_train.iloc[-1]['ts'].isoformat() if len(df_train) > 0 else None,
            'val_end': df_val.iloc[-1]['ts'].isoformat() if len(df_val) > 0 else None,
            'historical_test_end': df_test.iloc[-1]['ts'].isoformat() if len(df_test) > 0 else None,
            'holdout_start': HOLDOUT_START.isoformat(),
            'holdout_end': future_holdout.iloc[-1]['ts'].isoformat() if len(future_holdout) > 0 else None,
        },
        'sample_counts': {
            'train': int(len(X_train)),
            'validation': int(len(X_val)),
            'historical_test': int(len(X_test)),
            'future_holdout': int(len(future_holdout)),
        },
        'class_distributions': {
            'train': {target_idx_to_obj[idx]: int(count) for idx, count in pd.Series(y_train).value_counts().items()},
            'validation': {target_idx_to_obj[idx]: int(count) for idx, count in pd.Series(y_val).value_counts().items()},
            'historical_test': {target_idx_to_obj[idx]: int(count) for idx, count in pd.Series(y_test).value_counts().items()},
            'future_holdout': {},
        },
        'baseline_model': {
            'class_weight': None,
            'validation': baseline_metrics['validation'],
        },
        'class_weighted_model': {
            'class_weight': 'balanced',
            'validation': weighted_metrics['validation'],
        },
        'selected_model': {
            'class_weight': selected_class_weight,
            'validation': selected_metrics['validation'],
            'selection_rule': 'higher_validation_macro_f1',
        },
        'majority_baseline': {
            'most_common_class': target_idx_to_obj[pd.Series(y_train).value_counts().index[0]],
            'majority_class_accuracy_val': float(pd.Series(y_val).value_counts().iloc[0] / len(y_val)) if len(y_val) > 0 else 0.0,
        },
        'final_holdout_evaluation': 'PENDING - insufficient future data after holdout_start',
        'evaluated_at': datetime.now(timezone.utc).isoformat(),
        'preprocessing_version': 'v2_task2a_compliant',
        'vocabulary_source': 'train_only',
        'target_encoder_fitted_on': 'train_only',
    }

    save_model_metadata(len(X_train), len(target_idx_to_obj), evaluation_metadata)

    logger.info(f"Model trained and saved. Selected class_weight={selected_class_weight}")
    logger.info(f"Future holdout evaluation: {evaluation_metadata['final_holdout_evaluation']}")
    return True

def save_model_metadata(training_samples: int, num_objects: int, evaluation_metrics: Dict):
    conn = get_db_connection()
    try:
        model_version = f"rf_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO model_metadata (model_version, model_type, trained_at, training_samples, features, hyperparameters, evaluation_metrics, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                model_version,
                'random_forest',
                datetime.now(timezone.utc),
                training_samples,
                json.dumps(feature_columns),
                json.dumps({'n_estimators': 100, 'max_depth': 10, 'random_state': 42}),
                json.dumps(evaluation_metrics),
                True
            ))
            cur.execute("UPDATE model_metadata SET is_active = FALSE WHERE model_version != %s", (model_version,))
        conn.commit()
        logger.info(f"Model metadata saved: {model_version}")
    except Exception as e:
        logger.error(f"Failed to save model metadata: {e}")
    finally:
        conn.close()

def encode_features(recent_objects: List[str], query_type: str, hour: int):
    obj_to_idx = encoders.get('obj_to_idx', {})
    unk_idx = encoders.get('unk_idx', UNK_IDX)
    if len(recent_objects) < 4:
        raise ValueError(f"Insufficient history: {len(recent_objects)} objects provided, need 4")
    encoded = [obj_to_idx.get(obj, unk_idx) for obj in recent_objects[:4]]

    qt_encoded = QUERY_TYPE_MAP.get(query_type, 0)

    feature_values = encoded + [hour, qt_encoded]
    return pd.DataFrame([feature_values], columns=feature_columns)

@app.on_event("startup")
async def startup():
    load_model()
    if not train_model_clean():
        logger.info("Model not trained yet - waiting for data")

@app.get("/health")
async def health():
    return {
        "status": "healthy" if model else "degraded",
        "model_loaded": model is not None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/model/status")
async def model_status():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM model_metadata WHERE model_type = 'random_forest' ORDER BY trained_at DESC LIMIT 1")
            model_row = cur.fetchone()
            cur.execute("SELECT * FROM model_metadata WHERE model_type = 'calibration_platt' ORDER BY trained_at DESC LIMIT 1")
            cal_row = cur.fetchone()

            result = {}
            if model_row:
                result['base_model'] = dict(model_row)
            if cal_row:
                result['calibration'] = dict(cal_row)
            result['calibration_enabled'] = calibration_enabled
            result['os_decision_threshold'] = 0.75
            return result
    finally:
        conn.close()

@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    if not model:
        raise HTTPException(status_code=503, detail="Model not trained yet")

    hour = request.hour if request.hour is not None else datetime.now(timezone.utc).hour

    try:
        X = encode_features(request.recent_objects, request.query_type, hour)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        raw_probas = model.predict_proba(X)[0]
        raw_pred_idx = np.argmax(raw_probas)
        raw_confidence = float(raw_probas[raw_pred_idx])

        target_idx_to_obj = encoders.get('target_idx_to_obj', {})
        predicted_object = target_idx_to_obj.get(raw_pred_idx, 'unknown')

        raw_all_probs = {}
        for idx, prob in enumerate(raw_probas):
            obj = target_idx_to_obj.get(idx)
            if obj and prob > 0.01:
                raw_all_probs[obj] = float(prob)

        # Apply calibration if available
        if calibration_enabled and calibrator is not None:
            calibrated_probas = apply_calibration(raw_probas.reshape(1, -1))[0]
            cal_pred_idx = np.argmax(calibrated_probas)
            calibrated_confidence = float(calibrated_probas[cal_pred_idx])

            cal_all_probs = {}
            for idx, prob in enumerate(calibrated_probas):
                obj = target_idx_to_obj.get(idx)
                if obj and prob > 0.01:
                    cal_all_probs[obj] = float(prob)

            # Use calibrated confidence for decision (OS threshold = 0.75)
            confidence = calibrated_confidence
            all_probabilities = cal_all_probs
        else:
            calibrated_confidence = None
            cal_all_probs = None
            confidence = raw_confidence
            all_probabilities = raw_all_probs

        access_pattern = 'sequential'
        if 'index' in predicted_object.lower() or 'pk' in predicted_object.lower():
            access_pattern = 'index'
        elif predicted_object.endswith('_log') or predicted_object.endswith('_audit'):
            access_pattern = 'sequential'

        cal_version = calibration_metadata.get('calibration_version') if calibration_metadata else None

        return PredictionResponse(
            predicted_object=predicted_object,
            confidence=confidence,
            raw_confidence=raw_confidence,
            calibrated_confidence=calibrated_confidence,
            access_pattern=access_pattern,
            all_probabilities=all_probabilities,
            raw_probabilities=raw_all_probs,
            calibration_version=cal_version
        )
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/train")
async def train_endpoint():
    success = train_model_clean()
    if success:
        return {"status": "trained", "timestamp": datetime.now(timezone.utc).isoformat()}
    else:
        raise HTTPException(status_code=400, detail="Insufficient data for training")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
