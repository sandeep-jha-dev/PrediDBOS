-- PrediDBOS Database Schema
-- Run on PostgreSQL 16+

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- =====================================================
-- WORKLOAD HISTORY
-- Raw observations from PostgreSQL workload
-- =====================================================
CREATE TABLE workload_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    query_id TEXT,
    query_text TEXT,
    normalized_query_hash TEXT,
    object_name TEXT,
    access_pattern TEXT,          -- 'sequential', 'random', 'bitmap', 'index'
    query_type TEXT,              -- 'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DDL', 'UTILITY'
    execution_time_ms DOUBLE PRECISION,
    rows_returned BIGINT,
    shared_blks_hit BIGINT,
    shared_blks_read BIGINT,
    shared_blks_dirtied BIGINT,
    shared_blks_written BIGINT,
    local_blks_hit BIGINT,
    local_blks_read BIGINT,
    temp_blks_read BIGINT,
    temp_blks_written BIGINT,
    blk_read_time DOUBLE PRECISION,
    blk_write_time DOUBLE PRECISION,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_workload_history_timestamp ON workload_history(timestamp DESC);
CREATE INDEX idx_workload_history_object ON workload_history(object_name);
CREATE INDEX idx_workload_history_query_hash ON workload_history(normalized_query_hash);

-- =====================================================
-- PREDICTIONS
-- ML model outputs
-- =====================================================
CREATE TABLE predictions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    workload_id UUID REFERENCES workload_history(id),
    predicted_object TEXT NOT NULL,
    predicted_access_pattern TEXT,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    model_version TEXT NOT NULL,
    features JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_predictions_timestamp ON predictions(timestamp DESC);
CREATE INDEX idx_predictions_object ON predictions(predicted_object);
CREATE INDEX idx_predictions_workload ON predictions(workload_id);

-- =====================================================
-- DECISIONS
-- OS-side decision engine outcomes
-- =====================================================
CREATE TABLE decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prediction_id UUID REFERENCES predictions(id),
    decision TEXT NOT NULL,       -- 'prefetch', 'no_action', 'keep_hot', 'evict'
    reason TEXT NOT NULL,
    available_memory_mb BIGINT,
    cpu_usage_percent DOUBLE PRECISION,
    disk_io_read_mbps DOUBLE PRECISION,
    disk_io_write_mbps DOUBLE PRECISION,
    already_cached BOOLEAN,
    cache_check_method TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_decisions_timestamp ON decisions(timestamp DESC);
CREATE INDEX idx_decisions_prediction ON decisions(prediction_id);
CREATE INDEX idx_decisions_decision ON decisions(decision);

-- =====================================================
-- PERFORMANCE RESULTS
-- Measured outcomes for evaluation
-- =====================================================
CREATE TABLE performance_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    workload_id UUID REFERENCES workload_history(id),
    prediction_id UUID REFERENCES predictions(id),
    decision_id UUID REFERENCES decisions(id),
    actual_object TEXT,
    actual_access_pattern TEXT,
    execution_time_ms DOUBLE PRECISION,
    disk_read_bytes BIGINT,
    disk_write_bytes BIGINT,
    peak_memory_mb BIGINT,
    cache_hit BOOLEAN,
    prediction_correct BOOLEAN,
    action_beneficial BOOLEAN,
    overhead_ms DOUBLE PRECISION,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_perf_timestamp ON performance_results(timestamp DESC);
CREATE INDEX idx_perf_workload ON performance_results(workload_id);

-- =====================================================
-- OS STATE SNAPSHOTS
-- Periodic system telemetry
-- =====================================================
CREATE TABLE os_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cpu_usage_percent DOUBLE PRECISION,
    memory_total_mb BIGINT,
    memory_used_mb BIGINT,
    memory_available_mb BIGINT,
    swap_total_mb BIGINT,
    swap_used_mb BIGINT,
    disk_read_bytes BIGINT,
    disk_write_bytes BIGINT,
    disk_read_mbps DOUBLE PRECISION,
    disk_write_mbps DOUBLE PRECISION,
    disk_utilization_percent DOUBLE PRECISION,
    io_wait_percent DOUBLE PRECISION,
    load_avg_1m DOUBLE PRECISION,
    load_avg_5m DOUBLE PRECISION,
    load_avg_15m DOUBLE PRECISION,
    page_cache_mb BIGINT,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_os_state_timestamp ON os_state(timestamp DESC);

-- =====================================================
-- MODEL METADATA
-- Track ML model versions and performance
-- =====================================================
CREATE TABLE model_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_version TEXT NOT NULL UNIQUE,
    model_type TEXT NOT NULL,       -- 'random_forest', 'baseline', etc.
    trained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    training_samples INTEGER,
    features JSONB NOT NULL,
    hyperparameters JSONB DEFAULT '{}'::jsonb,
    evaluation_metrics JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- =====================================================
-- VIEWS FOR DASHBOARD
-- =====================================================

-- Recent workload with prediction/decision join
CREATE VIEW recent_workload_with_predictions AS
SELECT
    wh.*,
    p.predicted_object,
    p.predicted_access_pattern,
    p.confidence,
    p.model_version,
    d.decision,
    d.reason,
    d.available_memory_mb,
    pr.prediction_correct,
    pr.action_beneficial,
    pr.execution_time_ms as perf_execution_time_ms
FROM workload_history wh
LEFT JOIN predictions p ON p.workload_id = wh.id
LEFT JOIN decisions d ON d.prediction_id = p.id
LEFT JOIN performance_results pr ON pr.workload_id = wh.id
ORDER BY wh.timestamp DESC
LIMIT 100;

-- System health summary
CREATE VIEW system_health AS
SELECT
    (SELECT COUNT(*) FROM workload_history WHERE timestamp > NOW() - INTERVAL '1 minute') as queries_last_minute,
    (SELECT COUNT(*) FROM predictions WHERE timestamp > NOW() - INTERVAL '1 minute') as predictions_last_minute,
    (SELECT COUNT(*) FROM decisions WHERE timestamp > NOW() - INTERVAL '1 minute') as decisions_last_minute,
    (SELECT AVG(confidence) FROM predictions WHERE timestamp > NOW() - INTERVAL '5 minutes') as avg_confidence,
    (SELECT COUNT(*) FROM decisions WHERE decision = 'prefetch' AND timestamp > NOW() - INTERVAL '5 minutes') as prefetch_count,
    (SELECT COUNT(*) FROM decisions WHERE decision = 'no_action' AND timestamp > NOW() - INTERVAL '5 minutes') as no_action_count;

-- Prediction accuracy over time (hourly buckets)
CREATE VIEW prediction_accuracy_hourly AS
SELECT
    DATE_TRUNC('hour', p.timestamp) as hour,
    COUNT(*) as total_predictions,
    SUM(CASE WHEN pr.prediction_correct THEN 1 ELSE 0 END)::DOUBLE PRECISION / COUNT(*) as accuracy,
    AVG(p.confidence) as avg_confidence
FROM predictions p
JOIN performance_results pr ON pr.prediction_id = p.id
WHERE p.timestamp > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', p.timestamp)
ORDER BY hour DESC;