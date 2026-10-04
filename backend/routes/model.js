import { Router } from 'express';

const router = Router();

router.get('/status', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT * FROM model_metadata
      ORDER BY trained_at DESC
      LIMIT 1
    `);
    res.json(result.rows[0] || {});
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/history', async (req, res) => {
  try {
    const result = await req.pgPool.query(`
      SELECT * FROM model_metadata
      ORDER BY trained_at DESC
      LIMIT 10
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.post('/activate', async (req, res) => {
  const { model_version } = req.body;
  if (!model_version) {
    return res.status(400).json({ error: 'model_version required' });
  }
  try {
    await req.pgPool.query('UPDATE model_metadata SET is_active = FALSE');
    await req.pgPool.query('UPDATE model_metadata SET is_active = TRUE WHERE model_version = $1', [model_version]);
    
    req.eventStream.emit('model_activated', { model_version });
    res.json({ success: true, model_version });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

export default router;