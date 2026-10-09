"""
Probability Calibration Module for PrediDBOS

Implements multiclass probability calibration using Platt scaling (sigmoid) per class
with out-of-fold predictions from training data for fitting.

Calibration Method: One-vs-Rest Platt Scaling (Sigmoid Calibration)
- Fits a logistic regression (sigmoid) for each class independently
- Uses out-of-fold predictions from training data to avoid overfitting
- Evaluates on validation and historical test sets
- Does NOT use future holdout data (after 2026-10-05T23:05:20+00:00 UTC)
"""

import numpy as np
import pandas as pd
import joblib
import cloudpickle
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

import os
CALIBRATION_DIR = os.path.join(os.path.dirname(__file__), 'saved_model')
CALIBRATION_PATH = os.path.join(CALIBRATION_DIR, 'calibrator.joblib')
CALIBRATION_METADATA_PATH = os.path.join(CALIBRATION_DIR, 'calibration_metadata.joblib')

HOLDOUT_START = pd.Timestamp('2026-10-05 23:05:20+00:00', tz='UTC')

UNK_TOKEN = '<UNK>'
UNK_IDX = -1

INTERNAL_OBJECTS = {
    'performance_results', 'predictions', 'decisions', 'os_state',
    'model_metadata', 'workload_history', 'generate_series',
    'pg_class', 'pg_database', 'pg_catalog', 'pg_attribute',
    'pg_proc', 'pg_type', 'pg_namespace', 'pg_index', 'pg_stat_statements',
    'information_schema'
}

PG_SYSTEM_PREFIXES = ('pg_', 'sql_', 'information_schema_')

QUERY_TYPE_MAP = {'SELECT': 0, 'INSERT': 1, 'UPDATE': 2, 'DELETE': 3, 'DDL': 4, 'UTILITY': 5}

feature_columns = ['current_object', 'prev_object_1', 'prev_object_2', 'prev_object_3', 'hour', 'query_type_encoded']


def is_internal_object(obj_name: str) -> bool:
    if obj_name in INTERNAL_OBJECTS:
        return True
    for prefix in PG_SYSTEM_PREFIXES:
        if obj_name.startswith(prefix):
            return True
    return False


def get_db_connection():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import os
    DB_CONFIG = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', 5432)),
        'database': os.getenv('POSTGRES_DB', 'predidbos'),
        'user': os.getenv('POSTGRES_USER', 'predidbos'),
        'password': os.getenv('POSTGRES_PASSWORD', 'predidbos'),
    }
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


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

    return (X_train, y_train, X_val, y_val, X_test, y_test,
            obj_to_idx, idx_to_obj, target_encoder, target_idx_to_obj,
            df_train, df_val, df_test, future_holdout)


def get_out_of_fold_predictions(X_train, y_train, n_splits=5):
    """
    Generate out-of-fold predictions using CHRONOLOGICAL expanding-window CV on training data.

    This ensures temporal validity: for each OOF prediction at time t,
    the model is trained ONLY on data strictly earlier than t.

    Procedure:
    - Split training data chronologically into n_splits folds
    - For fold i (1 to n_splits-1): train on folds 0..i-1, validate on fold i
    - Fold 0 is used as initial training base (not validated)
    - This produces OOF predictions for folds 1 through n_splits-1

    Args:
        X_train: Training features (already in chronological order)
        y_train: Training labels (already in chronological order)
        n_splits: Number of chronological folds (default 5)

    Returns:
        oof_probas: Array of shape (n_samples, n_classes) with OOF predictions
                    for validation folds; zeros for initial training fold
        fold_info: List of dicts with fold boundaries and metadata
    """
    from sklearn.ensemble import RandomForestClassifier

    n_samples = len(X_train)
    n_classes = len(np.unique(y_train))
    oof_probas = np.zeros((n_samples, n_classes))

    # Create chronological folds (no shuffling)
    fold_size = n_samples // n_splits
    fold_indices = []
    for i in range(n_splits):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_splits - 1 else n_samples
        fold_indices.append((start, end))

    fold_info = []

    # Fold 0: initial training base (no OOF prediction)
    logger.info(f"OOF: Fold 0 (initial training base): rows {fold_indices[0][0]}-{fold_indices[0][1]} ({fold_indices[0][1]-fold_indices[0][0]} samples)")
    fold_info.append({
        'fold': 0,
        'role': 'initial_training',
        'train_start': fold_indices[0][0],
        'train_end': fold_indices[0][1],
        'val_start': None,
        'val_end': None,
        'train_samples': fold_indices[0][1] - fold_indices[0][0],
        'val_samples': 0,
    })

    # Expanding window: for each subsequent fold, train on all previous folds
    for i in range(1, n_splits):
        train_start = 0
        train_end = fold_indices[i][0]  # All data before this fold
        val_start = fold_indices[i][0]
        val_end = fold_indices[i][1]

        train_indices = np.arange(train_start, train_end)
        val_indices = np.arange(val_start, val_end)

        logger.info(f"OOF fold {i}/{n_splits-1}: train={len(train_indices)} (rows 0-{train_end-1}), val={len(val_indices)} (rows {val_start}-{val_end-1})")

        X_fold_train = X_train.iloc[train_indices]
        y_fold_train = y_train.iloc[train_indices]
        X_fold_val = X_train.iloc[val_indices]

        # Verify all classes present in training
        train_classes = np.unique(y_fold_train)
        if len(train_classes) < n_classes:
            logger.warning(f"Fold {i}: Training data missing classes! Present: {train_classes}, Expected: {list(range(n_classes))}")

        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1,
            class_weight='balanced'
        )
        model.fit(X_fold_train, y_fold_train)

        fold_probas = model.predict_proba(X_fold_val)
        oof_probas[val_indices] = fold_probas

        # Record class distribution in validation fold (use original y_train for indexing)
        val_labels = y_train.iloc[val_indices]
        val_class_dist = {int(c): int(np.sum(val_labels == c)) for c in train_classes}
        fold_info.append({
            'fold': i,
            'role': 'validation',
            'train_start': train_start,
            'train_end': train_end,
            'val_start': val_start,
            'val_end': val_end,
            'train_samples': len(train_indices),
            'val_samples': len(val_indices),
            'train_classes_present': train_classes.tolist(),
            'val_class_distribution': val_class_dist,
        })

    # Verify no OOF predictions for initial fold (should be zeros)
    initial_fold_end = fold_indices[0][1]
    assert np.all(oof_probas[:initial_fold_end] == 0), "Initial fold should have zero OOF predictions"

    logger.info(f"Chronological OOF complete: {n_splits-1} validation folds, {np.sum(oof_probas > 0)} samples with predictions")

    return oof_probas, fold_info


class MulticlassPlattCalibrator:
    """
    Multiclass probability calibration using One-vs-Rest Platt Scaling (sigmoid).

    For each class, fits a logistic regression (sigmoid) that maps raw probability
    to calibrated probability. This is the standard Platt scaling approach extended
    to multiclass via one-vs-rest.
    """

    def __init__(self, n_classes: int):
        self.n_classes = n_classes
        self.calibrators = []  # One LogisticRegression per class
        self.is_fitted = False

    def fit(self, raw_probas: np.ndarray, true_labels: np.ndarray):
        """
        Fit calibrators using raw probabilities and true labels.

        Args:
            raw_probas: Shape (n_samples, n_classes) - raw predict_proba output
            true_labels: Shape (n_samples,) - true class indices
        """
        if raw_probas.shape[1] != self.n_classes:
            raise ValueError(f"Expected {self.n_classes} classes, got {raw_probas.shape[1]}")

        self.calibrators = []

        for class_idx in range(self.n_classes):
            # One-vs-Rest: binary labels for this class
            y_binary = (true_labels == class_idx).astype(int)
            x_class = raw_probas[:, class_idx].reshape(-1, 1)

            # Fit logistic regression (Platt scaling) for this class
            # Use balanced class weight to handle potential imbalance
            calibrator = LogisticRegression(
                solver='lbfgs',
                max_iter=1000,
                class_weight='balanced',
                random_state=42
            )
            calibrator.fit(x_class, y_binary)
            self.calibrators.append(calibrator)

        self.is_fitted = True
        logger.info(f"Fitted {self.n_classes} Platt calibrators")

    def predict_proba(self, raw_probas: np.ndarray) -> np.ndarray:
        """
        Apply calibration to raw probabilities.

        Args:
            raw_probas: Shape (n_samples, n_classes) - raw predict_proba output

        Returns:
            Calibrated probabilities, shape (n_samples, n_classes)
        """
        if not self.is_fitted:
            raise ValueError("Calibrator not fitted. Call fit() first.")

        if raw_probas.shape[1] != self.n_classes:
            raise ValueError(f"Expected {self.n_classes} classes, got {raw_probas.shape[1]}")

        n_samples = raw_probas.shape[0]
        calibrated = np.zeros((n_samples, self.n_classes))

        for class_idx in range(self.n_classes):
            x_class = raw_probas[:, class_idx].reshape(-1, 1)
            # Get probability of positive class (class_idx)
            calibrated[:, class_idx] = self.calibrators[class_idx].predict_proba(x_class)[:, 1]

        # Renormalize to ensure probabilities sum to 1
        row_sums = calibrated.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0  # Avoid division by zero
        calibrated = calibrated / row_sums

        return calibrated


# Ensure class is available in calibration namespace for pickling (Docker deployment)
import sys
if 'calibration' in sys.modules:
    sys.modules['calibration'].MulticlassPlattCalibrator = MulticlassPlattCalibrator
# Also register in ml.calibration for backward compatibility
if 'ml.calibration' in sys.modules:
    sys.modules['ml.calibration'].MulticlassPlattCalibrator = MulticlassPlattCalibrator


def evaluate_calibration(raw_probas: np.ndarray,
                          calibrated_probas: np.ndarray,
                          true_labels: np.ndarray,
                          target_idx_to_obj: Dict[int, str]) -> Dict[str, Any]:
    """
    Evaluate calibration quality using multiple metrics.

    Args:
        raw_probas: Raw model probabilities (n_samples, n_classes)
        calibrated_probas: Calibrated probabilities (n_samples, n_classes)
        true_labels: True class indices (n_samples,)
        target_idx_to_obj: Mapping from class index to object name

    Returns:
        Dictionary with calibration metrics
    """
    n_classes = raw_probas.shape[1]
    results = {}

    # Overall metrics
    results['overall'] = {}

    # Brier Score (lower is better)
    # For multiclass, we compute per-class and average
    raw_brier_per_class = []
    cal_brier_per_class = []

    for class_idx in range(n_classes):
        y_binary = (true_labels == class_idx).astype(int)
        raw_brier = brier_score_loss(y_binary, raw_probas[:, class_idx])
        cal_brier = brier_score_loss(y_binary, calibrated_probas[:, class_idx])
        raw_brier_per_class.append(raw_brier)
        cal_brier_per_class.append(cal_brier)

    results['overall']['raw_brier_score'] = float(np.mean(raw_brier_per_class))
    results['overall']['calibrated_brier_score'] = float(np.mean(cal_brier_per_class))
    results['overall']['brier_improvement'] = float(np.mean(raw_brier_per_class) - np.mean(cal_brier_per_class))

    # Log Loss (lower is better)
    results['overall']['raw_log_loss'] = float(log_loss(true_labels, raw_probas, labels=list(range(n_classes))))
    results['overall']['calibrated_log_loss'] = float(log_loss(true_labels, calibrated_probas, labels=list(range(n_classes))))
    results['overall']['log_loss_improvement'] = float(results['overall']['raw_log_loss'] - results['overall']['calibrated_log_loss'])

    # Expected Calibration Error (ECE) - using 10 bins
    results['overall']['raw_ece'] = compute_ece(raw_probas, true_labels, n_bins=10)
    results['overall']['calibrated_ece'] = compute_ece(calibrated_probas, true_labels, n_bins=10)
    results['overall']['ece_improvement'] = float(results['overall']['raw_ece'] - results['overall']['calibrated_ece'])

    # Per-class metrics
    results['per_class'] = {}
    for class_idx in range(n_classes):
        class_name = target_idx_to_obj.get(class_idx, f'class_{class_idx}')
        y_binary = (true_labels == class_idx).astype(int)

        results['per_class'][class_name] = {
            'raw_brier': float(brier_score_loss(y_binary, raw_probas[:, class_idx])),
            'calibrated_brier': float(brier_score_loss(y_binary, calibrated_probas[:, class_idx])),
            'raw_log_loss': float(log_loss(y_binary, np.column_stack([1 - raw_probas[:, class_idx], raw_probas[:, class_idx]]))),
            'calibrated_log_loss': float(log_loss(y_binary, np.column_stack([1 - calibrated_probas[:, class_idx], calibrated_probas[:, class_idx]]))),
            'support': int(np.sum(y_binary)),
            'raw_ece': compute_ece_binary(raw_probas[:, class_idx], y_binary, n_bins=10),
            'calibrated_ece': compute_ece_binary(calibrated_probas[:, class_idx], y_binary, n_bins=10),
        }

    # Predictive metrics (accuracy, F1) - these should not change with calibration
    raw_preds = np.argmax(raw_probas, axis=1)
    cal_preds = np.argmax(calibrated_probas, axis=1)

    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

    results['predictive'] = {
        'raw': {
            'accuracy': float(accuracy_score(true_labels, raw_preds)),
            'f1_macro': float(f1_score(true_labels, raw_preds, average='macro', zero_division=0)),
            'f1_weighted': float(f1_score(true_labels, raw_preds, average='weighted', zero_division=0)),
            'precision_macro': float(precision_score(true_labels, raw_preds, average='macro', zero_division=0)),
            'recall_macro': float(recall_score(true_labels, raw_preds, average='macro', zero_division=0)),
        },
        'calibrated': {
            'accuracy': float(accuracy_score(true_labels, cal_preds)),
            'f1_macro': float(f1_score(true_labels, cal_preds, average='macro', zero_division=0)),
            'f1_weighted': float(f1_score(true_labels, cal_preds, average='weighted', zero_division=0)),
            'precision_macro': float(precision_score(true_labels, cal_preds, average='macro', zero_division=0)),
            'recall_macro': float(recall_score(true_labels, cal_preds, average='macro', zero_division=0)),
        }
    }

    # Threshold-specific analysis at 0.75
    results['threshold_analysis'] = analyze_threshold(raw_probas, calibrated_probas, true_labels,
                                                        target_idx_to_obj, threshold=0.75)

    return results


def compute_ece(probas: np.ndarray, true_labels: np.ndarray, n_bins: int = 10) -> float:
    """
    Compute Expected Calibration Error for multiclass.
    ECE = sum_{bins} (|bin| / n) * |accuracy(bin) - confidence(bin)|
    """
    n_samples = len(true_labels)
    pred_classes = np.argmax(probas, axis=1)
    pred_confidences = np.max(probas, axis=1)
    correct = (pred_classes == true_labels).astype(float)

    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0

    for i in range(n_bins):
        bin_low = bin_boundaries[i]
        bin_high = bin_boundaries[i + 1]
        in_bin = (pred_confidences >= bin_low) & (pred_confidences < bin_high)

        if i == n_bins - 1:
            # Include right boundary for last bin
            in_bin = (pred_confidences >= bin_low) & (pred_confidences <= bin_high)

        bin_count = np.sum(in_bin)
        if bin_count > 0:
            bin_accuracy = np.mean(correct[in_bin])
            bin_confidence = np.mean(pred_confidences[in_bin])
            ece += (bin_count / n_samples) * abs(bin_accuracy - bin_confidence)

    return float(ece)


def compute_ece_binary(probas: np.ndarray, true_labels: np.ndarray, n_bins: int = 10) -> float:
    """Compute ECE for binary calibration (one-vs-rest)."""
    n_samples = len(true_labels)
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0

    for i in range(n_bins):
        bin_low = bin_boundaries[i]
        bin_high = bin_boundaries[i + 1]
        in_bin = (probas >= bin_low) & (probas < bin_high)

        if i == n_bins - 1:
            in_bin = (probas >= bin_low) & (probas <= bin_high)

        bin_count = np.sum(in_bin)
        if bin_count > 0:
            bin_accuracy = np.mean(true_labels[in_bin])
            bin_confidence = np.mean(probas[in_bin])
            ece += (bin_count / n_samples) * abs(bin_accuracy - bin_confidence)

    return float(ece)


def analyze_threshold(raw_probas: np.ndarray,
                       calibrated_probas: np.ndarray,
                       true_labels: np.ndarray,
                       target_idx_to_obj: Dict[int, str],
                       threshold: float = 0.75) -> Dict[str, Any]:
    """
    Analyze prediction behavior around the OS decision threshold (0.75).
    """
    n_samples = len(true_labels)

    # Raw probabilities
    raw_max_probas = np.max(raw_probas, axis=1)
    raw_preds = np.argmax(raw_probas, axis=1)
    raw_above = raw_max_probas >= threshold
    raw_correct = (raw_preds == true_labels).astype(int)

    # Calibrated probabilities
    cal_max_probas = np.max(calibrated_probas, axis=1)
    cal_preds = np.argmax(calibrated_probas, axis=1)
    cal_above = cal_max_probas >= threshold
    cal_correct = (cal_preds == true_labels).astype(int)

    results = {
        'threshold': threshold,
        'raw': {
            'n_above_threshold': int(np.sum(raw_above)),
            'n_below_threshold': int(np.sum(~raw_above)),
            'accuracy_above': float(np.mean(raw_correct[raw_above])) if np.sum(raw_above) > 0 else 0.0,
            'accuracy_below': float(np.mean(raw_correct[~raw_above])) if np.sum(~raw_above) > 0 else 0.0,
            'mean_confidence_above': float(np.mean(raw_max_probas[raw_above])) if np.sum(raw_above) > 0 else 0.0,
            'mean_confidence_below': float(np.mean(raw_max_probas[~raw_above])) if np.sum(~raw_above) > 0 else 0.0,
        },
        'calibrated': {
            'n_above_threshold': int(np.sum(cal_above)),
            'n_below_threshold': int(np.sum(~cal_above)),
            'accuracy_above': float(np.mean(cal_correct[cal_above])) if np.sum(cal_above) > 0 else 0.0,
            'accuracy_below': float(np.mean(cal_correct[~cal_above])) if np.sum(~cal_above) > 0 else 0.0,
            'mean_confidence_above': float(np.mean(cal_max_probas[cal_above])) if np.sum(cal_above) > 0 else 0.0,
            'mean_confidence_below': float(np.mean(cal_max_probas[~cal_above])) if np.sum(~cal_above) > 0 else 0.0,
        }
    }

    # Confusion at threshold: how many predictions cross the threshold after calibration
    raw_above_set = set(np.where(raw_above)[0])
    cal_above_set = set(np.where(cal_above)[0])

    results['threshold_crossing'] = {
        'raw_above_cal_below': int(len(raw_above_set - cal_above_set)),
        'raw_below_cal_above': int(len(cal_above_set - raw_above_set)),
        'both_above': int(len(raw_above_set & cal_above_set)),
        'both_below': int(n_samples - len(raw_above_set | cal_above_set)),
    }

    return results


def compute_reliability_curve(probas: np.ndarray, true_labels: np.ndarray, n_bins: int = 10) -> Dict[str, List]:
    """
    Compute reliability curve data for plotting.
    Returns bin centers, accuracies, confidences, and counts.
    """
    pred_classes = np.argmax(probas, axis=1)
    pred_confidences = np.max(probas, axis=1)
    correct = (pred_classes == true_labels).astype(float)

    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bin_centers = []
    bin_accuracies = []
    bin_confidences = []
    bin_counts = []

    for i in range(n_bins):
        bin_low = bin_boundaries[i]
        bin_high = bin_boundaries[i + 1]
        in_bin = (pred_confidences >= bin_low) & (pred_confidences <= bin_high)

        bin_count = np.sum(in_bin)
        if bin_count > 0:
            bin_centers.append((bin_low + bin_high) / 2)
            bin_accuracies.append(float(np.mean(correct[in_bin])))
            bin_confidences.append(float(np.mean(pred_confidences[in_bin])))
            bin_counts.append(int(bin_count))

    return {
        'bin_centers': bin_centers,
        'bin_accuracies': bin_accuracies,
        'bin_confidences': bin_confidences,
        'bin_counts': bin_counts
    }


def train_calibration():
    """
    Main calibration training pipeline.

    1. Load data using the same protocol as ML service
    2. Get out-of-fold predictions on training data (chronological expanding window)
    3. Fit Platt calibrators on OOF predictions
    4. Evaluate on validation and historical test sets
    5. Save calibrator and metadata
    """
    logger.info("Starting calibration training pipeline...")

    # Load data using existing protocol
    result = prepare_user_sequence()
    if result is None:
        logger.error("Failed to prepare data for calibration")
        return False

    (X_train, y_train, X_val, y_val, X_test, y_test,
     obj_to_idx, idx_to_obj, target_encoder, target_idx_to_obj,
     df_train, df_val, df_test, future_holdout) = result

    # Load the trained base model directly from disk
    import os
    MODEL_DIR = os.path.join(os.path.dirname(__file__), 'saved_model')
    MODEL_PATH = os.path.join(MODEL_DIR, 'model.joblib')
    ENCODER_PATH = os.path.join(MODEL_DIR, 'encoders.joblib')

    # Get the active base model version from database
    base_model_version = 'unknown'
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT model_version FROM model_metadata WHERE model_type = 'random_forest' AND is_active = TRUE ORDER BY trained_at DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                base_model_version = row['model_version']
        conn.close()
    except Exception as e:
        logger.warning(f"Could not fetch base model version from database: {e}")

    try:
        base_model = joblib.load(MODEL_PATH)
        base_encoders = joblib.load(ENCODER_PATH)
        target_idx_to_obj = base_encoders.get('target_idx_to_obj', target_idx_to_obj)
        logger.info(f"Base model loaded from disk successfully (version: {base_model_version})")
    except Exception as e:
        logger.error(f"Failed to load base model from disk: {e}")
        return False

    logger.info("Generating CHRONOLOGICAL out-of-fold predictions on training data...")
    oof_probas, fold_info = get_out_of_fold_predictions(X_train, y_train, n_splits=5)

    # Filter out initial training fold (zeros) for calibrator fitting
    # Only use samples that have actual OOF predictions (folds 1-4)
    oof_mask = np.any(oof_probas > 0, axis=1)
    oof_probas_for_cal = oof_probas[oof_mask]
    y_train_for_cal = y_train.values[oof_mask]

    logger.info(f"Fitting Platt calibrators on {len(oof_probas_for_cal)} OOF predictions (excluded initial training fold)...")
    calibrator = MulticlassPlattCalibrator(n_classes=len(target_idx_to_obj))
    calibrator.fit(oof_probas_for_cal, y_train_for_cal)

    # Get raw probabilities on validation and test sets
    logger.info("Evaluating on validation set...")
    val_raw_probas = base_model.predict_proba(X_val)
    val_calibrated_probas = calibrator.predict_proba(val_raw_probas)
    val_metrics = evaluate_calibration(val_raw_probas, val_calibrated_probas, y_val.values, target_idx_to_obj)

    logger.info("Evaluating on historical test set...")
    test_raw_probas = base_model.predict_proba(X_test)
    test_calibrated_probas = calibrator.predict_proba(test_raw_probas)
    test_metrics = evaluate_calibration(test_raw_probas, test_calibrated_probas, y_test.values, target_idx_to_obj)

    # Also evaluate on training OOF for reference (only samples with predictions)
    logger.info("Evaluating on training OOF...")
    train_metrics = evaluate_calibration(oof_probas_for_cal, calibrator.predict_proba(oof_probas_for_cal), y_train_for_cal, target_idx_to_obj)

    # Save calibrator state (logistic regression coefficients) to avoid pickling issues
    import os
    os.makedirs(os.path.dirname(CALIBRATION_PATH), exist_ok=True)

    calibrator_state = {
        'n_classes': calibrator.n_classes,
        'calibrators': calibrator.calibrators,
        'is_fitted': calibrator.is_fitted,
    }
    joblib.dump(calibrator_state, CALIBRATION_PATH)

    # Save calibration metadata with detailed fold information
    calibration_metadata = {
        'calibration_version': f"cal_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        'calibration_method': 'multiclass_platt_scaling_ovr',
        'calibrator_type': 'MulticlassPlattCalibrator',
        'base_model_version': base_model_version,
        'calibration_training_data': 'train_oof_chronological',
        'calibration_training_samples': int(len(oof_probas_for_cal)),
        'n_classes': len(target_idx_to_obj),
        'target_classes': target_idx_to_obj,
        'fitted_at': datetime.now(timezone.utc).isoformat(),
        'evaluation': {
            'train_oof': train_metrics,
            'validation': val_metrics,
            'historical_test': test_metrics,
        },
        'holdout_boundary': HOLDOUT_START.isoformat(),
        'holdout_untouched': True,
        'preprocessing_version': 'v2_task2a_compliant',
        'class_weight': 'balanced',
        'oof_method': 'chronological_expanding_window',
        'oof_folds': 5,
        'oof_fold_details': fold_info,
        'oof_initial_fold_excluded': True,
        'oof_validation_folds': len([f for f in fold_info if f['role'] == 'validation']),
    }

    joblib.dump(calibration_metadata, CALIBRATION_METADATA_PATH)

    # Also save to database
    save_calibration_metadata(calibration_metadata)

    logger.info("Calibration training completed successfully")
    logger.info(f"Validation - Raw Brier: {val_metrics['overall']['raw_brier_score']:.4f}, "
                f"Calibrated Brier: {val_metrics['overall']['calibrated_brier_score']:.4f}")
    logger.info(f"Validation - Raw LogLoss: {val_metrics['overall']['raw_log_loss']:.4f}, "
                f"Calibrated LogLoss: {val_metrics['overall']['calibrated_log_loss']:.4f}")
    logger.info(f"Validation - Raw ECE: {val_metrics['overall']['raw_ece']:.4f}, "
                f"Calibrated ECE: {val_metrics['overall']['calibrated_ece']:.4f}")

    return True


def save_calibration_metadata(metadata: Dict):
    """Save calibration metadata to database."""
    import json
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO model_metadata (model_version, model_type, trained_at, training_samples,
                    features, hyperparameters, evaluation_metrics, is_active, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                metadata['calibration_version'],
                'calibration_platt',
                datetime.now(timezone.utc),
                metadata['calibration_training_samples'],
                json.dumps(feature_columns),
                json.dumps({'method': 'platt_scaling_ovr', 'oof_folds': 5}),
                json.dumps(metadata['evaluation']),
                False,  # Not the primary model
                json.dumps(metadata)
            ))
        conn.commit()
        logger.info(f"Calibration metadata saved: {metadata['calibration_version']}")
    except Exception as e:
        logger.error(f"Failed to save calibration metadata: {e}")
    finally:
        conn.close()


def load_calibrator():
    """Load the fitted calibrator."""
    global calibrator, calibration_metadata
    try:
        if os.path.exists(CALIBRATION_PATH) and os.path.exists(CALIBRATION_METADATA_PATH):
            calibrator_state = joblib.load(CALIBRATION_PATH)
            calibrator = MulticlassPlattCalibrator(n_classes=calibrator_state['n_classes'])
            calibrator.calibrators = calibrator_state['calibrators']
            calibrator.is_fitted = calibrator_state['is_fitted']
            calibration_metadata = joblib.load(CALIBRATION_METADATA_PATH)
            logger.info(f"Calibrator loaded: {calibration_metadata.get('calibration_version')}")
            return True
    except Exception as e:
        logger.warning(f"Could not load calibrator: {e}")
    return False


# Global calibrator state
calibrator = None
calibration_metadata = None


def apply_calibration(raw_probas: np.ndarray) -> np.ndarray:
    """Apply calibration to raw probabilities if calibrator is available."""
    global calibrator
    if calibrator is not None and calibrator.is_fitted:
        return calibrator.predict_proba(raw_probas)
    return raw_probas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    train_calibration()
