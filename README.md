# PrediDBOS

**Workload-aware Memory Collaboration between SQL and Linux via Predictive Hinting**

A research prototype demonstrating DB-OS cooperation for intelligent caching and prefetching decisions.

## Architecture

```
PostgreSQL → Collector → Historical Data → ML Predictor → JSON Hint → OS Decision Engine → Linux (madvise/fadvise/readahead)
                                    ↑                                                        ↓
                              Feedback Loop ◄────────────────────────────────────────────────
```

## Components

| Component | Technology | Port | Description |
|-----------|------------|------|-------------|
| PostgreSQL | 16-alpine | 5432 | Database + pg_stat_statements |
| Backend API | Node.js/Express | 3001 | REST API + WebSocket/SSE |
| Frontend | React + Tailwind | 3000 | Real-time dashboard |
| ML Service | Python/FastAPI | 8000 | Random Forest predictor |
| OS Service | Python/FastAPI | 8001 | System monitoring + decision engine |
| Collector | Python | - | pg_stat_statements collector |

## Quick Start

```bash
# Clone and enter
cd predidbos

# Start all services
docker compose up --build

# Wait for all containers to be healthy (30-60s)
# Then open http://localhost:3000
```

## Dashboard Features

- **System Status**: PostgreSQL, Collector, ML Model, OS Service health
- **Live Metrics**: CPU, RAM, Disk I/O, Cache (updating every 5s)
- **Pipeline Visualizer**: Live flow: PostgreSQL → Collector → ML → Hint → OS → Decision → Action → Outcome
- **Workload Panel**: Recent queries with object, pattern, cache hit/miss
- **Prediction Panel**: ML predicted object, confidence, model version
- **Hint Panel**: Raw JSON hint sent from ML to OS
- **Decision Panel**: OS decision with reasoning (prefetch/no_action)
- **Event Timeline**: Live log of all pipeline events
- **Charts**: CPU/RAM/Disk, Execution time, Cache hit rate, Action counts

## API Endpoints

```
GET  /api/health                 - Overall health
GET  /api/status                 - Component statuses
GET  /api/system/state           - Current OS metrics
GET  /api/system/state/history   - OS metrics history
GET  /api/workload/recent        - Recent workload entries
GET  /api/workload/stats         - Workload statistics
GET  /api/predictions/recent     - Recent predictions
GET  /api/predictions/latest     - Latest prediction
GET  /api/decisions/recent       - Recent decisions
GET  /api/metrics/performance    - Performance comparison
GET  /api/model/status           - Current ML model info
GET  /api/events/stream          - SSE live event stream
WS   /ws                         - WebSocket live event stream
```

## ML Pipeline

1. **Collector** reads `pg_stat_statements` every 5s
2. **Historical data** stored in `workload_history` table
3. **Training**: Random Forest on sequences of 4 previous objects → next object
4. **Prediction**: On new query, predict next table + confidence
5. **Hint**: JSON sent to OS service with predicted object, pattern, confidence
6. **Decision**: OS service evaluates system state + confidence → prefetch/no_action
7. **Action**: `madvise(MADV_WILLNEED)`, `posix_fadvise`, `readahead`
8. **Feedback**: Outcome recorded for evaluation

## Configuration

Environment variables (set in `docker-compose.yml`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_CONFIDENCE` | 0.75 | Minimum ML confidence to act |
| `MIN_AVAILABLE_MEMORY_MB` | 512 | Min free RAM for prefetch |
| `MAX_DISK_IO_MBPS` | 200 | Max disk I/O before blocking |
| `MAX_PREFETCH_SIZE_MB` | 1024 | Max prefetch size |
| `COLLECTION_INTERVAL` | 5 | Collector interval (seconds) |

## Development

```bash
# View logs
docker compose logs -f backend
docker compose logs -f ml
docker compose logs -f os-service

# Restart single service
docker compose restart backend

# Run benchmark (after data collected)
docker compose exec backend npm run benchmark
```

## Research Evaluation

Run controlled experiments:

```bash
# Baseline (normal PostgreSQL)
# 1. Disable PrediDBOS decision engine
# 2. Run pgbench/tpch workload
# 3. Record metrics

# PrediDBOS enabled
# 1. Enable decision engine
# 2. Run same workload
# 3. Compare: execution time, disk reads, memory, cache hits
```

## Project Structure

```
predidbos/
├── backend/          # Node.js API + WebSocket
├── frontend/         # React dashboard
├── collector/        # pg_stat_statements collector
├── ml/               # Python ML service
├── os_service/       # Python OS decision service
├── database/         # SQL schema
├── docker/           # Docker configs
└── docker-compose.yml
```

## License

Research prototype for academic evaluation.