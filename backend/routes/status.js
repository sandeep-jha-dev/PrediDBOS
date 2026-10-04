import { Router } from 'express';
import axios from 'axios';

const router = Router();

router.get('/', async (req, res) => {
  try {
    const pgResult = await req.pgPool.query('SELECT 1 as ok');
    const pgConnected = pgResult.rows[0].ok === 1;

    let collectorStatus = 'unknown';
    let mlStatus = 'unknown';
    let osStatus = 'unknown';

    console.log('[STATUS] Checking ML at:', req.mlServiceUrl);
    try {
      const mlResp = await axios.get(`${req.mlServiceUrl}/health`, { timeout: 2000 });
      console.log('[STATUS] ML response:', mlResp.data);
      mlStatus = mlResp.data.status || 'unknown';
    } catch (e) {
      console.log('[STATUS] ML error:', e.message, e.code);
      mlStatus = 'unreachable';
    }

    console.log('[STATUS] Checking OS at:', req.osServiceUrl);
    try {
      const osResp = await axios.get(`${req.osServiceUrl}/health`, { timeout: 2000 });
      console.log('[STATUS] OS response:', osResp.data);
      osStatus = osResp.data.status || 'unknown';
    } catch (e) {
      console.log('[STATUS] OS error:', e.message, e.code);
      osStatus = 'unreachable';
    }

    // Collector doesn't have HTTP endpoint; check via database activity
    try {
      const recentActivity = await req.pgPool.query(
        "SELECT 1 FROM workload_history WHERE timestamp > NOW() - INTERVAL '2 minutes' LIMIT 1"
      );
      collectorStatus = recentActivity.rows.length > 0 ? 'active' : 'idle';
    } catch (e) {
      collectorStatus = 'unknown';
    }

    res.json({
      status: pgConnected && mlStatus !== 'unreachable' && osStatus !== 'unreachable' ? 'online' : 'degraded',
      timestamp: new Date().toISOString(),
      components: {
        postgresql: pgConnected ? 'connected' : 'disconnected',
        collector: collectorStatus,
        ml_model: mlStatus,
        os_service: osStatus,
      },
    });
  } catch (e) {
    res.status(500).json({ status: 'error', error: e.message });
  }
});

export default router;