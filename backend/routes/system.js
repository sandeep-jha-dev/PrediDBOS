import { Router } from 'express';

const router = Router();

router.get('/state', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT * FROM os_state
      ORDER BY timestamp DESC
      LIMIT 1
    `);
    res.json(result.rows[0] || {});
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/state/history', async (req, res) => {
  const minutes = parseInt(req.query.minutes) || 30;
  try {
    const result = await req.pgPool.query(`
      SELECT * FROM os_state
      WHERE timestamp > NOW() - INTERVAL '${minutes} minutes'
      ORDER BY timestamp ASC
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/metrics/live', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT
        cpu_usage_percent,
        memory_total_mb,
        memory_available_mb,
        memory_used_mb,
        disk_read_mbps,
        disk_write_mbps,
        io_wait_percent,
        timestamp
      FROM os_state
      ORDER BY timestamp DESC
      LIMIT 1
    `);
    res.json(result.rows[0] || {});
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

export default router;