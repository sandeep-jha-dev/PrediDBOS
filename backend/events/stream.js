export class EventStream {
  constructor(wss) {
    this.wss = wss;
    this.wsClients = new Map();
    this.sseClients = new Map();
    this.clientCounter = 0;
  }

  addWSClient(ws) {
    const id = `ws-${++this.clientCounter}`;
    this.wsClients.set(id, ws);
    return id;
  }

  removeWSClient(id) {
    this.wsClients.delete(id);
  }

  addSSEClient(res) {
    const id = `sse-${++this.clientCounter}`;
    this.sseClients.set(id, res);
    res.write(`data: ${JSON.stringify({ type: 'connected', clientId: id })}\n\n`);
    return id;
  }

  removeSSEClient(id) {
    this.sseClients.delete(id);
  }

  broadcast(event) {
    const data = JSON.stringify(event);

    for (const [id, ws] of this.wsClients) {
      if (ws.readyState === 1) {
        try {
          ws.send(data);
        } catch (e) {
          console.error(`WS send error for ${id}:`, e.message);
          this.wsClients.delete(id);
        }
      }
    }

    for (const [id, res] of this.sseClients) {
      try {
        res.write(`data: ${data}\n\n`);
      } catch (e) {
        console.error(`SSE send error for ${id}:`, e.message);
        this.sseClients.delete(id);
      }
    }
  }

  emit(type, payload) {
    this.broadcast({
      type,
      timestamp: new Date().toISOString(),
      ...payload
    });
  }
}

export const eventTypes = {
  QUERY_OBSERVED: 'query_observed',
  WORKLOAD_RECORDED: 'workload_recorded',
  PREDICTION_CREATED: 'prediction_created',
  HINT_GENERATED: 'hint_generated',
  OS_STATE_UPDATED: 'os_state_updated',
  DECISION_MADE: 'decision_made',
  ACTION_STARTED: 'action_started',
  ACTION_COMPLETED: 'action_completed',
  OUTCOME_RECORDED: 'outcome_recorded',
  ERROR: 'error',
  SYSTEM_STATUS: 'system_status',
};