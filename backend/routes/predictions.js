import { Router } from 'express';

const router = Router();

router.get('/recent', async (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  try {
    const result = await req.pgPool.query(`
      SELECT
        p.*, wh.query_text, wh.object_name as actual_object
      FROM predictions p
      LEFT JOIN workload_history wh ON wh.id = p.workload_id
      ORDER BY p.timestamp DESC
      LIMIT $1
    `, [limit]);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/latest', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT
        p.*, wh.query_text, wh.object_name as actual_object
      FROM predictions p
      LEFT JOIN workload_history wh ON wh.id = p.workload_id
      ORDER BY p.timestamp DESC
      LIMIT 1
    `);
    res.json(result.rows[0] || {});
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/accuracy', async (req, res) => {
  const hours = parseInt(req.query.hours) || 24;
  try {
    const result = await req.pgPool.query(`
      SELECT
        DATE_TRUNC('hour', p.timestamp) as hour,
        COUNT(*) as total,
        SUM(CASE WHEN pr.prediction_correct THEN 1 ELSE 0 END)::DOUBLE PRECISION / COUNT(*) as accuracy,
        AVG(p.confidence) as avg_confidence
      FROM predictions p
      LEFT JOIN performance_results pr ON pr.prediction_id = p.id
      WHERE p.timestamp > NOW() - INTERVAL '${hours} hours'
      GROUP BY DATE_TRUNC('hour', p.timestamp)
      ORDER BY hour DESC
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/confidence/distribution', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT
        CASE
          WHEN confidence >= 0.9 THEN '0.9-1.0'
          WHEN confidence >= 0.8 THEN '0.8-0.9'
          WHEN confidence >= 0.7 THEN '0.7-0.8'
          WHEN confidence >= 0.6 THEN '0.6-0.7'
          ELSE '<0.6'
        END as bucket,
        COUNT(*) as count
      FROM predictions
      WHERE timestamp > NOW() - INTERVAL '24 hours'
      GROUP BY bucket
      ORDER BY bucket DESC
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

export default router;