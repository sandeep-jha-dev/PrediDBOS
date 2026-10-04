import { Router } from 'express';

const router = Router();

router.get('/recent', async (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  try {
    const result = await req.pgPool.query(`
      SELECT
        id, timestamp, query_id, query_text, object_name,
        access_pattern, query_type, execution_time_ms,
        shared_blks_hit, shared_blks_read,
        metadata
      FROM workload_history
      ORDER BY timestamp DESC
      LIMIT $1
    `, [limit]);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/stats', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT
        COUNT(*) as total_queries,
        COUNT(DISTINCT object_name) as unique_objects,
        AVG(execution_time_ms) as avg_execution_time,
        SUM(shared_blks_read) as total_blocks_read,
        SUM(shared_blks_hit) as total_blocks_hit,
        COUNT(*) FILTER (WHERE timestamp > NOW() - INTERVAL '1 minute') as queries_last_minute,
        COUNT(*) FILTER (WHERE timestamp > NOW() - INTERVAL '5 minutes') as queries_last_5min
      FROM workload_history
      WHERE timestamp > NOW() - INTERVAL '1 hour'
    `);
    res.json(result.rows[0]);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/objects', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT
        object_name,
        COUNT(*) as access_count,
        AVG(execution_time_ms) as avg_time,
        SUM(shared_blks_read) as blocks_read,
        SUM(shared_blks_hit) as blocks_hit,
        MAX(timestamp) as last_accessed
      FROM workload_history
      WHERE object_name IS NOT NULL
        AND timestamp > NOW() - INTERVAL '1 hour'
      GROUP BY object_name
      ORDER BY access_count DESC
      LIMIT 20
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

export default router;