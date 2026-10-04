import express from 'express';
import { createServer } from 'http';
import { WebSocketServer } from 'ws';
import cors from 'cors';
import pg from 'pg';
import axios from 'axios';
import dotenv from 'dotenv';

import statusRoutes from './routes/status.js';
import systemRoutes from './routes/system.js';
import workloadRoutes from './routes/workload.js';
import predictionRoutes from './routes/predictions.js';
import decisionRoutes from './routes/decisions.js';
import metricsRoutes from './routes/metrics.js';
import modelRoutes from './routes/model.js';
import { EventStream } from './events/stream.js';

dotenv.config();

const app = express();
const server = createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });

const PORT = process.env.PORT || 3001;

const pgPool = new pg.Pool({
  host: process.env.POSTGRES_HOST || 'localhost',
  port: process.env.POSTGRES_PORT || 5432,
  database: process.env.POSTGRES_DB || 'predidbos',
  user: process.env.POSTGRES_USER || 'predidbos',
  password: process.env.POSTGRES_PASSWORD || 'predidbos',
  max: 20,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

pgPool.on('error', (err) => {
  console.error('Unexpected PG pool error:', err);
});

const eventStream = new EventStream(wss);

app.use(cors());
app.use(express.json());
app.use((req, res, next) => {
  req.pgPool = pgPool;
  req.eventStream = eventStream;
  req.mlServiceUrl = process.env.ML_SERVICE_URL || 'http://localhost:8000';
  req.osServiceUrl = process.env.OS_SERVICE_URL || 'http://localhost:8001';
  next();
});

app.get('/api/health', async (req, res) => {
  try {
    await req.pgPool.query('SELECT 1');
    res.json({ status: 'healthy', timestamp: new Date().toISOString() });
  } catch (e) {
    res.status(503).json({ status: 'unhealthy', error: e.message });
  }
});

app.use('/api/status', statusRoutes);
app.use('/api/system', systemRoutes);
app.use('/api/workload', workloadRoutes);
app.use('/api/predictions', predictionRoutes);
app.use('/api/decisions', decisionRoutes);
app.use('/api/metrics', metricsRoutes);
app.use('/api/model', modelRoutes);

app.post('/api/frontend-error', (req, res) => {
  console.error('[FRONTEND ERROR]', JSON.stringify(req.body, null, 2));
  res.json({ received: true });
});

app.post('/api/events/emit', (req, res) => {
  const { type, payload } = req.body;
  if (!type) {
    return res.status(400).json({ error: 'Event type is required' });
  }
  eventStream.emit(type, payload || {});
  res.json({ emitted: true, type });
});

app.get('/api/events/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  const clientId = eventStream.addSSEClient(res);
  console.log(`SSE client connected: ${clientId}`);

  req.on('close', () => {
    eventStream.removeSSEClient(clientId);
    console.log(`SSE client disconnected: ${clientId}`);
  });
});

wss.on('connection', (ws, req) => {
  const clientId = eventStream.addWSClient(ws);
  console.log(`WS client connected: ${clientId}`);

  ws.on('close', () => {
    eventStream.removeWSClient(clientId);
    console.log(`WS client disconnected: ${clientId}`);
  });

  ws.on('error', (err) => {
    console.error(`WS error for ${clientId}:`, err.message);
    eventStream.removeWSClient(clientId);
  });
});

server.listen(PORT, () => {
  console.log(`PrediDBOS Backend running on http://localhost:${PORT}`);
  console.log(`WebSocket: ws://localhost:${PORT}/ws`);
  console.log(`SSE: http://localhost:${PORT}/api/events/stream`);
});

process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down...');
  server.close(() => {
    pgPool.end().then(() => process.exit(0));
  });
});