#!/usr/bin/env python3
import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import json
from datetime import datetime
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

COLLECTION_INTERVAL = int(os.getenv('COLLECTION_INTERVAL', '5'))
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:3001')

def emit_event(event_type: str, payload: dict):
    """Emit an event to the backend event stream (synchronous)."""
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{BACKEND_URL}/api/events/emit", json={
                "type": event_type,
                "payload": payload
            })
    except Exception as e:
        logger.debug(f"Failed to emit event {event_type}: {e}")

QUERY_STATS_SQL = """
    SELECT 
        queryid,
        query,
        calls,
        total_exec_time,
        mean_exec_time,
        rows,
        shared_blks_hit,
        shared_blks_read,
        shared_blks_dirtied,
        shared_blks_written,
        local_blks_hit,
        local_blks_read,
        temp_blks_read,
        temp_blks_written,
        blk_read_time,
        blk_write_time
    FROM pg_stat_statements
    WHERE query NOT LIKE '%pg_stat_statements%'
      AND query NOT LIKE '%workload_history%'
      AND query NOT LIKE '%predictions%'
      AND query NOT LIKE '%decisions%'
      AND query NOT LIKE '%os_state%'
      AND query NOT LIKE '%model_metadata%'
    ORDER BY total_exec_time DESC
    LIMIT 100
"""

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def normalize_query(query: str) -> str:
    import re
    normalized = re.sub(r'\b\d+\b', '?', query)
    normalized = re.sub(r"'[^']*'", "'?'", normalized)
    normalized = ' '.join(normalized.split())
    return normalized[:500]

def extract_object_and_pattern(query: str):
    import re
    query_lower = query.lower().strip()
    
    access_pattern = 'unknown'
    if 'join' in query_lower:
        access_pattern = 'join'
    elif 'where' in query_lower and 'index' not in query_lower:
        access_pattern = 'sequential'
    elif 'index' in query_lower or 'pk' in query_lower:
        access_pattern = 'index'
    elif 'order by' in query_lower:
        access_pattern = 'sequential'
    else:
        access_pattern = 'random'

    object_name = None
    from_match = re.search(r'\bfrom\s+(\w+)', query_lower)
    join_match = re.search(r'\bjoin\s+(\w+)', query_lower)
    update_match = re.search(r'\bupdate\s+(\w+)', query_lower)
    insert_match = re.search(r'\binsert\s+into\s+(\w+)', query_lower)
    delete_match = re.search(r'\bdelete\s+from\s+(\w+)', query_lower)

    for match in [from_match, join_match, update_match, insert_match, delete_match]:
        if match:
            object_name = match.group(1)
            break

    query_type = 'SELECT'
    if query_lower.startswith('insert'):
        query_type = 'INSERT'
    elif query_lower.startswith('update'):
        query_type = 'UPDATE'
    elif query_lower.startswith('delete'):
        query_type = 'DELETE'
    elif query_lower.startswith('create') or query_lower.startswith('alter') or query_lower.startswith('drop'):
        query_type = 'DDL'

    return object_name, access_pattern, query_type

def collect_once():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY_STATS_SQL)
            rows = cur.fetchall()

        if not rows:
            logger.debug("No queries in pg_stat_statements")
            return

        for row in rows:
            object_name, access_pattern, query_type = extract_object_and_pattern(row['query'])
            
            # Emit query_observed event
            emit_event('query_observed', {
                'query_id': row['queryid'],
                'object_name': object_name,
                'access_pattern': access_pattern,
                'query_type': query_type,
                'execution_time_ms': row['mean_exec_time'] or 0,
            })
            
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO workload_history (
                        query_id, query_text, normalized_query_hash, object_name,
                        access_pattern, query_type, execution_time_ms,
                        rows_returned, shared_blks_hit, shared_blks_read,
                        shared_blks_dirtied, shared_blks_written,
                        local_blks_hit, local_blks_read,
                        temp_blks_read, temp_blks_written,
                        blk_read_time, blk_write_time,
                        metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    row['queryid'],
                    row['query'][:1000],
                    str(hash(normalize_query(row['query']))),
                    object_name,
                    access_pattern,
                    query_type,
                    row['mean_exec_time'] or 0,
                    row['rows'] or 0,
                    row['shared_blks_hit'] or 0,
                    row['shared_blks_read'] or 0,
                    row['shared_blks_dirtied'] or 0,
                    row['shared_blks_written'] or 0,
                    row['local_blks_hit'] or 0,
                    row['local_blks_read'] or 0,
                    row['temp_blks_read'] or 0,
                    row['temp_blks_written'] or 0,
                    row['blk_read_time'] or 0,
                    row['blk_write_time'] or 0,
                    json.dumps({'original_calls': row['calls']})
                ))
                workload_id = cur.fetchone()['id']
            
            # Emit workload_recorded event
            emit_event('workload_recorded', {
                'workload_id': str(workload_id),
                'query_id': row['queryid'],
                'object_name': object_name,
                'access_pattern': access_pattern,
                'query_type': query_type,
            })
        
        conn.commit()
        logger.info(f"Collected {len(rows)} query entries")
        
    except Exception as e:
        logger.error(f"Collection error: {e}")
        conn.rollback()
    finally:
        conn.close()

def main():
    logger.info(f"PrediDBOS Collector starting (interval: {COLLECTION_INTERVAL}s)")
    
    while True:
        try:
            collect_once()
        except Exception as e:
            logger.error(f"Main loop error: {e}")
        time.sleep(COLLECTION_INTERVAL)

if __name__ == "__main__":
    main()