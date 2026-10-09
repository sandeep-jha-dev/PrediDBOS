#!/usr/bin/env python3
"""
PrediDBOS Orchestrator
Automatically connects: Collector -> ML Prediction -> JSON Hint -> OS Decision -> Outcome Recording
"""
import os
import time
import json
import logging
import asyncio
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor
import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'database': os.getenv('POSTGRES_DB', 'predidbos'),
    'user': os.getenv('POSTGRES_USER', 'predidbos'),
    'password': os.getenv('POSTGRES_PASSWORD', 'predidbos'),
}

ML_SERVICE_URL = os.getenv('ML_SERVICE_URL', 'http://ml:8000')
OS_SERVICE_URL = os.getenv('OS_SERVICE_URL', 'http://os-service:8001')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://backend:3001')
ORCHESTRATOR_INTERVAL = int(os.getenv('ORCHESTRATOR_INTERVAL', '10'))
BATCH_SIZE = int(os.getenv('ORCHESTRATOR_BATCH_SIZE', '10'))

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


class PipelineOrchestrator:
    def __init__(self):
        self.last_processed_workload_id: Optional[uuid.UUID] = None
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.current_model_version: Optional[str] = None
        self.model_version_fetched_at: Optional[datetime] = None
        self.model_version_ttl_seconds = 60

    async def emit_event(self, event_type: str, payload: Dict):
        """Emit an event to the backend event stream."""
        try:
            await self.http_client.post(f"{BACKEND_URL}/api/events/emit", json={
                "type": event_type,
                "payload": payload
            })
        except Exception as e:
            logger.debug(f"Failed to emit event {event_type}: {e}")

    async def get_unprocessed_workloads(self, limit: int = BATCH_SIZE) -> List[Dict]:
        """Get workload entries that haven't been processed by the orchestrator yet."""
        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        try:
            with conn.cursor() as cur:
                if self.last_processed_workload_id:
                    cur.execute("""
                        SELECT id, timestamp, object_name, access_pattern, query_type,
                               execution_time_ms, shared_blks_hit, shared_blks_read
                        FROM workload_history
                        WHERE id > %s
                        ORDER BY id ASC
                        LIMIT %s
                    """, (self.last_processed_workload_id, limit))
                else:
                    cur.execute("""
                        SELECT id, timestamp, object_name, access_pattern, query_type,
                               execution_time_ms, shared_blks_hit, shared_blks_read
                        FROM workload_history
                        ORDER BY id ASC
                        LIMIT %s
                    """, (limit,))
                return cur.fetchall()
        finally:
            conn.close()

    async def get_recent_objects(self, limit: int = 4) -> List[str]:
        """Get recent USER object names from workload history for ML prediction context.

        Internal/system objects (PrediDBOS instrumentation, PostgreSQL catalogs) are excluded
        to match the training formulation which learns user->user transitions.
        """
        # We need to fetch more than `limit` because some will be filtered out
        fetch_limit = limit * 5  # heuristic: fetch 5x to account for internal objects

        INTERNAL_OBJECTS = {
            'performance_results', 'predictions', 'decisions', 'os_state',
            'model_metadata', 'workload_history', 'generate_series',
            'pg_class', 'pg_database', 'pg_catalog', 'pg_attribute',
            'pg_proc', 'pg_type', 'pg_namespace', 'pg_index', 'pg_stat_statements',
            'information_schema'
        }
        PG_SYSTEM_PREFIXES = ('pg_', 'sql_', 'information_schema_')

        def is_internal(obj_name: str) -> bool:
            if obj_name in INTERNAL_OBJECTS:
                return True
            for prefix in PG_SYSTEM_PREFIXES:
                if obj_name.startswith(prefix):
                    return True
            return False

        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT object_name
                    FROM workload_history
                    WHERE object_name IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT %s
                """, (fetch_limit,))
                rows = cur.fetchall()

            # Filter out internal objects
            user_objects = [row['object_name'] for row in rows if not is_internal(row['object_name'])]

            # Return up to `limit` user objects
            return user_objects[:limit]
        finally:
            conn.close()

    async def get_model_version(self) -> Optional[str]:
        """Fetch the active model version from ML service."""
        now = datetime.utcnow()
        if (self.current_model_version and self.model_version_fetched_at and
            (now - self.model_version_fetched_at).total_seconds() < self.model_version_ttl_seconds):
            return self.current_model_version

        try:
            response = await self.http_client.get(f"{ML_SERVICE_URL}/model/status")
            if response.status_code == 200:
                data = response.json()
                # ML service now returns nested structure: base_model.model_version
                model_version = data.get('base_model', {}).get('model_version')
                # Fallback for legacy flat structure
                if not model_version:
                    model_version = data.get('model_version')
                if model_version:
                    self.current_model_version = model_version
                    self.model_version_fetched_at = now
                    logger.info(f"Fetched model version: {model_version}")
                    return model_version
            else:
                logger.warning(f"Failed to fetch model version: {response.status_code}")
        except Exception as e:
            logger.warning(f"Error fetching model version: {e}")
        return self.current_model_version

    async def call_ml_prediction(self, recent_objects: List[str], query_type: str = 'SELECT') -> Optional[Dict]:
        """Call ML service to get prediction."""
        try:
            payload = {
                "recent_objects": recent_objects,
                "query_type": query_type
            }
            response = await self.http_client.post(
                f"{ML_SERVICE_URL}/predict",
                json=payload
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"ML prediction failed: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.warning(f"ML prediction error: {e}")
            return None

    async def call_os_decide(self, prediction_id: str, predicted_object: str,
                             access_pattern: str, confidence: float, estimated_size_mb: int = 10) -> Optional[Dict]:
        """Call OS service /decide endpoint with the prediction hint."""
        try:
            payload = {
                "prediction_id": prediction_id,
                "predicted_object": predicted_object,
                "access_pattern": access_pattern,
                "confidence": confidence,
                "estimated_size_mb": estimated_size_mb
            }
            response = await self.http_client.post(
                f"{OS_SERVICE_URL}/decide",
                json=payload
            )
            if response.status_code == 200:
                result = response.json()
                # Log the decision_id if present
                if result.get('decision_id'):
                    logger.info(f"OS decision recorded with ID: {result['decision_id']}")
                return result
            else:
                logger.warning(f"OS decision failed: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.warning(f"OS decision error: {e}")
            return None

    async def record_performance_outcome(self, workload_id: str, prediction_id: str,
                                         decision_id: str, actual_object: Optional[str],
                                         actual_access_pattern: Optional[str],
                                         execution_time_ms: float, cache_hit: bool,
                                         prediction_correct: bool, action_beneficial: bool,
                                         overhead_ms: float):
        """Record the outcome in performance_results table."""
        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        try:
            with conn.cursor() as cur:
                # Get disk I/O for this workload (from OS state at decision time)
                # We'll use the current OS state as approximation
                cur.execute("""
                    INSERT INTO performance_results (
                        workload_id, prediction_id, decision_id,
                        actual_object, actual_access_pattern,
                        execution_time_ms, disk_read_bytes, disk_write_bytes,
                        peak_memory_mb, cache_hit, prediction_correct,
                        action_beneficial, overhead_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    workload_id, prediction_id, decision_id,
                    actual_object, actual_access_pattern,
                    execution_time_ms, 0, 0,  # disk bytes - not easily available per-query
                    0,  # peak_memory_mb
                    cache_hit, prediction_correct, action_beneficial, 0.0
                ))
            conn.commit()
            logger.info(f"Recorded performance outcome for workload {workload_id}")
        except Exception as e:
            logger.error(f"Failed to record performance outcome: {e}")
            conn.rollback()
        finally:
            conn.close()

    async def record_prediction(self, workload_id: str, predicted_object: str,
                                predicted_access_pattern: str, confidence: float,
                                model_version: str, features: Dict) -> str:
        """Record prediction in predictions table and return prediction_id."""
        prediction_id = str(uuid.uuid4())
        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO predictions (
                        id, timestamp, workload_id, predicted_object,
                        predicted_access_pattern, confidence, model_version, features
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    prediction_id, datetime.utcnow(), workload_id,
                    predicted_object, predicted_access_pattern, confidence, model_version, '{}'
                ))
            conn.commit()
            return prediction_id
        except Exception as e:
            logger.error(f"Failed to record prediction: {e}")
            conn.rollback()
            return prediction_id
        finally:
            conn.close()

    async def process_workload(self, workload: Dict) -> bool:
        """Process a single workload through the full pipeline."""
        workload_id = workload['id']
        object_name = workload.get('object_name')
        access_pattern = workload.get('access_pattern', 'unknown')
        query_type = workload.get('query_type', 'SELECT')
        execution_time_ms = workload.get('execution_time_ms', 0)
        shared_blks_hit = workload.get('shared_blks_hit', 0)
        shared_blks_read = workload.get('shared_blks_read', 0)

        # Skip if no object name (e.g., system queries)
        if not object_name:
            return False

        logger.info(f"Processing workload {workload_id}: {object_name} ({access_pattern})")

        try:
            # 1. Get recent objects for ML context
            recent_objects = await self.get_recent_objects(4)

            # 2. Check for sufficient history - need at least 4 objects for [current, prev1, prev2, prev3]
            if len(recent_objects) < 4:
                logger.debug(f"Insufficient history for workload {workload_id}: "
                           f"{len(recent_objects)} objects available, need 4. Skipping prediction.")
                # Emit event for observability
                await self.emit_event('prediction_skipped', {
                    'workload_id': str(workload_id),
                    'reason': 'insufficient_history',
                    'objects_available': len(recent_objects),
                    'objects_required': 4,
                })
                return False

            # 3. Call ML prediction
            ml_result = await self.call_ml_prediction(recent_objects, query_type)
            if not ml_result:
                logger.warning(f"ML prediction failed for workload {workload_id}")
                return False

            predicted_object = ml_result.get('predicted_object')
            confidence = ml_result.get('confidence', 0)
            predicted_access_pattern = ml_result.get('access_pattern', 'sequential')

            if not predicted_object:
                logger.warning(f"No prediction returned for workload {workload_id}")
                return False

            # 3. Record prediction with actual model version
            model_version = await self.get_model_version()
            if not model_version:
                logger.warning("No model version available, skipping prediction")
                return False

            prediction_id = await self.record_prediction(
                workload_id, predicted_object, predicted_access_pattern,
                confidence, model_version, {}
            )

            # Emit prediction_created event
            await self.emit_event('prediction_created', {
                'prediction_id': prediction_id,
                'workload_id': str(workload_id),
                'predicted_object': predicted_object,
                'predicted_access_pattern': predicted_access_pattern,
                'confidence': confidence,
                'model_version': model_version,
            })

            # 4. Send hint to OS service /decide
            estimated_size_mb = 10  # Default, could be enhanced

            # Emit hint_generated event (the hint is the payload sent to OS service)
            await self.emit_event('hint_generated', {
                'prediction_id': prediction_id,
                'workload_id': str(workload_id),
                'predicted_object': predicted_object,
                'access_pattern': predicted_access_pattern,
                'confidence': confidence,
                'estimated_size_mb': estimated_size_mb,
            })

            decision_result = await self.call_os_decide(
                prediction_id, predicted_object, predicted_access_pattern,
                confidence, estimated_size_mb
            )

            if not decision_result:
                logger.warning(f"OS decision failed for workload {workload_id}")
                return False

            decision = decision_result.get('decision', 'no_action')
            reason = decision_result.get('reason', '')
            decision_id = decision_result.get('decision_id')

            # Emit decision_made event
            await self.emit_event('decision_made', {
                'decision_id': decision_id,
                'prediction_id': prediction_id,
                'workload_id': str(workload_id),
                'decision': decision,
                'reason': reason,
                'predicted_object': predicted_object,
                'confidence': confidence,
            })

            # Determine if action was taken
            action_taken = decision == 'prefetch'

            if action_taken:
                # Emit action_started event
                await self.emit_event('action_started', {
                    'decision_id': decision_id,
                    'prediction_id': prediction_id,
                    'workload_id': str(workload_id),
                    'object': predicted_object,
                    'access_pattern': predicted_access_pattern,
                })

                # Emit action_completed event (OS service does the actual prefetch)
                await self.emit_event('action_completed', {
                    'decision_id': decision_id,
                    'prediction_id': prediction_id,
                    'workload_id': str(workload_id),
                    'object': predicted_object,
                    'success': True,
                })

            # 5. Determine if predicted object was actually accessed (simplified check)
            # In a real system, we'd track this more carefully
            actual_object = object_name if action_taken else None
            prediction_correct = (actual_object == predicted_object) if actual_object else None
            action_beneficial = action_taken and (prediction_correct is True)

            # 5. Record performance outcome with decision_id
            await self.record_performance_outcome(
                workload_id=workload_id,
                prediction_id=prediction_id,
                decision_id=decision_id,
                actual_object=actual_object,
                actual_access_pattern=access_pattern if action_taken else None,
                execution_time_ms=execution_time_ms or 0,
                cache_hit=shared_blks_hit > shared_blks_read if shared_blks_read > 0 else False,
                prediction_correct=prediction_correct,
                action_beneficial=action_beneficial,
                overhead_ms=0.0
            )

            # Emit outcome_recorded event
            await self.emit_event('outcome_recorded', {
                'workload_id': str(workload_id),
                'prediction_id': prediction_id,
                'decision_id': decision_id,
                'prediction_correct': prediction_correct,
                'action_beneficial': action_beneficial,
                'actual_object': actual_object,
                'predicted_object': predicted_object,
            })

            logger.info(f"Pipeline completed for workload {workload_id}: "
                       f"predicted={predicted_object}, confidence={confidence:.2f}, "
                       f"decision={decision}, action_taken={action_taken}")
            return True

        except Exception as e:
            logger.error(f"Pipeline error for workload {workload_id}: {e}")
            return False

    async def run_cycle(self):
        """Run one orchestration cycle."""
        try:
            workloads = await self.get_unprocessed_workloads()
            if not workloads:
                return

            logger.info(f"Processing {len(workloads)} new workload entries")

            for workload in workloads:
                try:
                    await self.process_workload(workload)
                    self.last_processed_workload_id = workload['id']
                except Exception as e:
                    logger.error(f"Error processing workload {workload.get('id')}: {e}")

        except Exception as e:
            logger.error(f"Orchestrator cycle error: {e}")

    async def run(self):
        logger.info(f"PrediDBOS Orchestrator starting (interval: {ORCHESTRATOR_INTERVAL}s)")
        while True:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"Orchestrator main loop error: {e}")
            await asyncio.sleep(ORCHESTRATOR_INTERVAL)

async def main():
    orchestrator = PipelineOrchestrator()
    await orchestrator.run()

if __name__ == "__main__":
    asyncio.run(main())
