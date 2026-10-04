from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import psutil
import subprocess
import json
import logging
import asyncio
import httpx
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PrediDBOS OS Service")

DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),
    'database': os.getenv('POSTGRES_DB', 'predidbos'),
    'user': os.getenv('POSTGRES_USER', 'predidbos'),
    'password': os.getenv('POSTGRES_PASSWORD', 'predidbos'),
}

ML_SERVICE_URL = os.getenv('ML_SERVICE_URL', 'http://ml:8000')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://backend:3001')

MIN_CONFIDENCE = float(os.getenv('MIN_CONFIDENCE', '0.75'))
MIN_AVAILABLE_MEMORY_MB = int(os.getenv('MIN_AVAILABLE_MEMORY_MB', '512'))
MAX_DISK_IO_MBPS = float(os.getenv('MAX_DISK_IO_MBPS', '200'))
MAX_PREFETCH_SIZE_MB = int(os.getenv('MAX_PREFETCH_SIZE_MB', '1024'))

async def emit_event(event_type: str, payload: Dict):
    """Emit an event to the backend event stream."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{BACKEND_URL}/api/events/emit", json={
                "type": event_type,
                "payload": payload
            })
    except Exception as e:
        logger.debug(f"Failed to emit event {event_type}: {e}")

class HintRequest(BaseModel):
    prediction_id: str
    predicted_object: str
    access_pattern: str
    confidence: float
    estimated_size_mb: Optional[int] = None

class DecisionResponse(BaseModel):
    decision: str
    reason: str
    details: Dict[str, Any]
    decision_id: Optional[str] = None

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def get_system_state() -> Dict[str, Any]:
    mem = psutil.virtual_memory()
    disk = psutil.disk_io_counters()
    cpu = psutil.cpu_percent(interval=0.1)
    
    disk_read_mbps = 0
    disk_write_mbps = 0
    if hasattr(get_system_state, 'last_disk') and get_system_state.last_disk:
        read_diff = disk.read_bytes - get_system_state.last_disk.read_bytes
        write_diff = disk.write_bytes - get_system_state.last_disk.write_bytes
        disk_read_mbps = (read_diff / 1024 / 1024) * 10
        disk_write_mbps = (write_diff / 1024 / 1024) * 10
    get_system_state.last_disk = disk

    load = psutil.getloadavg()
    
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                if ':' in line:
                    k, v = line.split(':', 1)
                    meminfo[k.strip()] = int(v.strip().split()[0]) * 1024
        page_cache_mb = meminfo.get('Cached', 0) / 1024 / 1024
    except:
        page_cache_mb = 0

    return {
        'cpu_usage_percent': cpu,
        'memory_total_mb': mem.total // 1024 // 1024,
        'memory_used_mb': mem.used // 1024 // 1024,
        'memory_available_mb': mem.available // 1024 // 1024,
        'disk_read_mbps': disk_read_mbps,
        'disk_write_mbps': disk_write_mbps,
        'load_avg_1m': load[0],
        'load_avg_5m': load[1],
        'load_avg_15m': load[2],
        'page_cache_mb': page_cache_mb,
    }

def check_already_cached(object_name: str, estimated_size_mb: int) -> bool:
    try:
        state = get_system_state()
        if state['page_cache_mb'] * 1024 > estimated_size_mb * 1024 * 1024 * 0.8:
            return True
    except:
        pass
    return False

def attempt_prefetch(object_name: str, access_pattern: str, estimated_size_mb: int) -> bool:
    try:
        table_files = find_table_files(object_name)
        if not table_files:
            logger.warning(f"No files found for table {object_name}")
            return False

        for fpath in table_files[:3]:
            try:
                fd = os.open(fpath, os.O_RDONLY)
                if access_pattern == 'sequential':
                    # POSIX_FADV_SEQUENTIAL = 2
                    try:
                        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_SEQUENTIAL)
                    except (AttributeError, OSError) as e:
                        logger.debug(f"posix_fadvise not available: {e}")
                    # readahead - read ahead 1MB
                    try:
                        os.preadv(fd, [bytearray(1024*1024)], 0)
                    except (AttributeError, OSError) as e:
                        logger.debug(f"preadv not available: {e}")
                # MADV_WILLNEED = 3
                try:
                    os.madvise(fd, 0, os.MADV_WILLNEED)
                except (AttributeError, OSError) as e:
                    logger.debug(f"madvise not available: {e}")
                os.close(fd)
            except Exception as e:
                logger.warning(f"Failed to prefetch {fpath}: {e}")
        
        logger.info(f"Prefetch attempted for {object_name} ({access_pattern})")
        return True
    except Exception as e:
        logger.error(f"Prefetch failed: {e}")
        return False

def find_table_files(table_name: str) -> list:
    try:
        # First, get the relfilenode (OID) for the table from pg_class
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT relfilenode FROM pg_class 
                    WHERE relname = %s AND relkind = 'r'
                """, (table_name,))
                row = cur.fetchone()
                if not row:
                    logger.warning(f"Table {table_name} not found in pg_class")
                    return []
                relfilenode = row['relfilenode']
        finally:
            conn.close()
        
        # Find files by relfilenode (OID) and its FSM/VM files
        result = subprocess.run(
            ['find', '/var/lib/postgresql/data', '-name', f'{relfilenode}*', '-type', 'f'],
            capture_output=True, text=True, timeout=5
        )
        files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
        logger.info(f"Found {len(files)} files for table {table_name} (relfilenode {relfilenode})")
        return files
    except Exception as e:
        logger.error(f"Error finding table files for {table_name}: {e}")
        return []

def make_decision(hint: HintRequest) -> DecisionResponse:
    state = get_system_state()
    details = {**state, 'prediction_id': hint.prediction_id}

    if hint.confidence < MIN_CONFIDENCE:
        return DecisionResponse(
            decision='no_action',
            reason=f'Confidence {hint.confidence:.2f} below threshold {MIN_CONFIDENCE}',
            details=details
        )

    if state['memory_available_mb'] < MIN_AVAILABLE_MEMORY_MB:
        return DecisionResponse(
            decision='no_action',
            reason=f'Insufficient memory: {state["memory_available_mb"]} MB available < {MIN_AVAILABLE_MEMORY_MB} MB threshold',
            details=details
        )

    if state['disk_read_mbps'] > MAX_DISK_IO_MBPS or state['disk_write_mbps'] > MAX_DISK_IO_MBPS:
        return DecisionResponse(
            decision='no_action',
            reason=f'High disk I/O: read={state["disk_read_mbps"]:.1f}, write={state["disk_write_mbps"]:.1f} MB/s',
            details=details
        )

    estimated_size = hint.estimated_size_mb or 100
    if estimated_size > MAX_PREFETCH_SIZE_MB:
        return DecisionResponse(
            decision='no_action',
            reason=f'Estimated size {estimated_size} MB exceeds max {MAX_PREFETCH_SIZE_MB} MB',
            details=details
        )

    already_cached = check_already_cached(hint.predicted_object, estimated_size)
    details['already_cached'] = already_cached

    if already_cached:
        return DecisionResponse(
            decision='no_action',
            reason='Data already likely in page cache',
            details=details
        )

    success = attempt_prefetch(hint.predicted_object, hint.access_pattern, estimated_size)
    
    if success:
        return DecisionResponse(
            decision='prefetch',
            reason=f'High confidence ({hint.confidence:.2f}) + sufficient resources + not cached',
            details=details
        )
    else:
        return DecisionResponse(
            decision='no_action',
            reason='Prefetch attempt failed',
            details=details
        )

def record_os_state(state: Dict[str, Any]):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO os_state (cpu_usage_percent, memory_total_mb, memory_used_mb, 
                    memory_available_mb, disk_read_mbps, disk_write_mbps, 
                    load_avg_1m, load_avg_5m, load_avg_15m, page_cache_mb)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                state['cpu_usage_percent'], state['memory_total_mb'], state['memory_used_mb'],
                state['memory_available_mb'], state['disk_read_mbps'], state['disk_write_mbps'],
                state['load_avg_1m'], state['load_avg_5m'], state['load_avg_15m'],
                state['page_cache_mb']
            ))
        conn.commit()
    finally:
        conn.close()

def record_decision(hint: HintRequest, decision: DecisionResponse):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Ensure prediction exists (create placeholder if needed)
            cur.execute("""
                INSERT INTO predictions (id, timestamp, predicted_object, predicted_access_pattern, confidence, model_version)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                hint.prediction_id, datetime.utcnow(),
                hint.predicted_object, hint.access_pattern, hint.confidence,
                'test_model'
            ))
            
            cur.execute("""
                INSERT INTO decisions (prediction_id, decision, reason, available_memory_mb,
                    cpu_usage_percent, disk_io_read_mbps, disk_io_write_mbps, already_cached)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                hint.prediction_id, decision.decision, decision.reason,
                decision.details['memory_available_mb'], decision.details['cpu_usage_percent'],
                decision.details['disk_read_mbps'], decision.details['disk_write_mbps'],
                decision.details.get('already_cached', False)
            ))
            decision_id = cur.fetchone()['id']
        conn.commit()
        return decision_id
    finally:
        conn.close()

@app.on_event("startup")
async def startup():
    logger.info("OS Service started")
    # Start background task to periodically record OS state
    import asyncio
    asyncio.create_task(periodic_state_recording())

async def periodic_state_recording():
    while True:
        try:
            state = get_system_state()
            record_os_state(state)
            # Emit os_state_updated event
            await emit_event('os_state_updated', state)
            await asyncio.sleep(10)  # Record every 10 seconds
        except Exception as e:
            logger.error(f"Periodic state recording failed: {e}")
            await asyncio.sleep(10)

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/state")
async def get_state():
    state = get_system_state()
    record_os_state(state)
    await emit_event('os_state_updated', state)
    return state

@app.post("/decide", response_model=DecisionResponse)
async def decide(hint: HintRequest):
    decision = make_decision(hint)
    decision_id = record_decision(hint, decision)
    decision.decision_id = decision_id
    return decision

@app.get("/config")
async def get_config():
    return {
        "MIN_CONFIDENCE": MIN_CONFIDENCE,
        "MIN_AVAILABLE_MEMORY_MB": MIN_AVAILABLE_MEMORY_MB,
        "MAX_DISK_IO_MBPS": MAX_DISK_IO_MBPS,
        "MAX_PREFETCH_SIZE_MB": MAX_PREFETCH_SIZE_MB,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)