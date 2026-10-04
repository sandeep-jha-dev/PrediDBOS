import { Router } from 'express';

const router = Router();

router.get('/performance', async (req, res) => {
  const hours = parseInt(req.query.hours) || 1;
  try {
    const result = await req.pgPool.query(`
      SELECT
        DATE_TRUNC('minute', timestamp) as minute,
        AVG(execution_time_ms) as avg_execution_time,
        SUM(disk_read_bytes) / 1024 / 1024 as disk_read_mb,
        SUM(disk_write_bytes) / 1024 / 1024 as disk_write_mb,
        AVG(peak_memory_mb) as avg_peak_memory,
        SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END)::DOUBLE PRECISION / COUNT(*) as cache_hit_rate,
        SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END)::DOUBLE PRECISION / COUNT(*) as prediction_accuracy,
        SUM(CASE WHEN action_beneficial THEN 1 ELSE 0 END)::DOUBLE PRECISION / COUNT(*) as action_beneficial_rate,
        COUNT(*) as sample_count
      FROM performance_results
      WHERE timestamp > NOW() - INTERVAL '${hours} hours'
      GROUP BY DATE_TRUNC('minute', timestamp)
      ORDER BY minute ASC
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/actions', async (req, res) => {
  const hours = parseInt(req.query.hours) || 1;
  try {
    const result = await req.pgPool.query(`
      SELECT
        DATE_TRUNC('minute', d.timestamp) as minute,
        d.decision,
        COUNT(*) as count
      FROM decisions d
      WHERE d.timestamp > NOW() - INTERVAL '${hours} hours'
      GROUP BY DATE_TRUNC('minute', d.timestamp), d.decision
      ORDER BY minute ASC
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/comparison', async (req, res) => {
  try {
    const baseline = await req.pgPool.query(`
      SELECT
        'baseline' as mode,
        AVG(execution_time_ms) as avg_execution_time,
        SUM(disk_read_bytes) / 1024 / 1024 as total_disk_read_mb,
        AVG(peak_memory_mb) as avg_peak_memory,
        SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END)::DOUBLE PRECISION / COUNT(*) as cache_hit_rate
      FROM performance_results
      WHERE timestamp > NOW() - INTERVAL '1 hour'
        AND decision_id IS NULL
    `);

    const predidbos = await req.pgPool.query(`
      SELECT
        'predidbos' as mode,
        AVG(execution_time_ms) as avg_execution_time,
        SUM(disk_read_bytes) / 1024 / 1024 as total_disk_read_mb,
        AVG(peak_memory_mb) as avg_peak_memory,
        SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END)::DOUBLE PRECISION / COUNT(*) as cache_hit_rate
      FROM performance_results
      WHERE timestamp > NOW() - INTERVAL '1 hour'
        AND decision_id IS NOT NULL
    `);

    res.json({
      baseline: baseline.rows[0] || {},
      predidbos: predidbos.rows[0] || {},
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

export default router;