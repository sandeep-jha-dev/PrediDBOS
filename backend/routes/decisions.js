import { Router } from 'express';

const router = Router();

router.get('/recent', async (req, res) => {
  const limit = parseInt(req.query.limit) || 50;
  try {
    const result = await req.pgPool.query(`
      SELECT
        d.*, p.predicted_object, p.confidence, p.predicted_access_pattern
      FROM decisions d
      LEFT JOIN predictions p ON p.id = d.prediction_id
      ORDER BY d.timestamp DESC
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
        decision,
        COUNT(*) as count,
        AVG(available_memory_mb) as avg_available_memory,
        AVG(cpu_usage_percent) as avg_cpu
      FROM decisions
      WHERE timestamp > NOW() - INTERVAL '1 hour'
      GROUP BY decision
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/latest', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT
        d.*, p.predicted_object, p.confidence, p.predicted_access_pattern
      FROM decisions d
      LEFT JOIN predictions p ON p.id = d.prediction_id
      ORDER BY d.timestamp DESC
      LIMIT 1
    `);
    res.json(result.rows[0] || {});
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

export default router;