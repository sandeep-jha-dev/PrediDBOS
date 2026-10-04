const API_BASE = '/api';

async function fetchJson(url) {
  const response = await fetch(`${API_BASE}${url}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchSystemStatus() {
  return fetchJson('/status');
}

export async function fetchSystemMetrics() {
  return fetchJson('/system/metrics/live');
}

export async function fetchSystemStateHistory(minutes = 30) {
  return fetchJson(`/system/state/history?minutes=${minutes}`);
}

export async function fetchWorkloadRecent(limit = 50) {
  return fetchJson(`/workload/recent?limit=${limit}`);
}

export async function fetchWorkloadStats() {
  return fetchJson('/workload/stats');
}

export async function fetchWorkloadObjects() {
  return fetchJson('/workload/objects');
}

export async function fetchPredictionsRecent(limit = 50) {
  return fetchJson(`/predictions/recent?limit=${limit}`);
}

export async function fetchPredictionsLatest() {
  return fetchJson('/predictions/latest');
}

export async function fetchPredictionAccuracy(hours = 24) {
  return fetchJson(`/predictions/accuracy?hours=${hours}`);
}

export async function fetchPredictionConfidenceDistribution() {
  return fetchJson('/predictions/confidence/distribution');
}

export async function fetchDecisionsRecent(limit = 50) {
  return fetchJson(`/decisions/recent?limit=${limit}`);
}

export async function fetchDecisionsStats() {
  return fetchJson('/decisions/stats');
}

export async function fetchDecisionsLatest() {
  return fetchJson('/decisions/latest');
}

export async function fetchPerformanceMetrics(hours = 1) {
  return fetchJson(`/metrics/performance?hours=${hours}`);
}

export async function fetchActionMetrics(hours = 1) {
  return fetchJson(`/metrics/actions?hours=${hours}`);
}

export async function fetchComparisonMetrics() {
  return fetchJson('/metrics/comparison');
}

export async function fetchModelStatus() {
  return fetchJson('/model/status');
}

export async function fetchModelHistory() {
  return fetchJson('/model/history');
}

export async function activateModel(modelVersion) {
  const response = await fetch(`${API_BASE}/model/activate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_version: modelVersion }),
  });
  if (!response.ok) throw new Error('Failed to activate model');
  return response.json();
}