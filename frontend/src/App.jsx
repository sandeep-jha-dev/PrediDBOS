import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  Database, Server, Cpu, HardDrive, MemoryStick, 
  Activity, AlertCircle, CheckCircle, XCircle, 
  RefreshCw, Zap, GitBranch, Terminal, Clock 
} from 'lucide-react';
import { clsx } from 'clsx';
import Header from './components/Header';
import SystemMetrics from './components/SystemMetrics';
import PipelineVisualizer from './components/PipelineVisualizer';
import WorkloadPanel from './components/WorkloadPanel';
import PredictionPanel from './components/PredictionPanel';
import HintPanel from './components/HintPanel';
import DecisionPanel from './components/DecisionPanel';
import EventTimeline from './components/EventTimeline';
import LiveCharts from './components/LiveCharts';
import { useEventStream } from './hooks/useEventStream';
import { fetchSystemStatus, fetchSystemMetrics, fetchWorkloadRecent, fetchPredictionsRecent, fetchDecisionsRecent, fetchPerformanceMetrics, fetchModelStatus } from './services/api';
import ErrorBoundary from './components/ErrorBoundary';

const API_BASE = '/api';

function AppContent() {
  const [systemStatus, setSystemStatus] = useState({
    status: 'unknown',
    components: { postgresql: 'unknown', collector: 'unknown', ml_model: 'unknown', os_service: 'unknown' }
  });
  const [systemMetrics, setSystemMetrics] = useState({});
  const [workload, setWorkload] = useState([]);
  const [predictions, setPredictions] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [performance, setPerformance] = useState({ baseline: {}, predidbos: {} });
  const [modelStatus, setModelStatus] = useState({});
  const [latestEvent, setLatestEvent] = useState(null);
  const [pipelineState, setPipelineState] = useState({
    postgresql: 'pending',
    collector: 'pending',
    ml: 'pending',
    hint: 'pending',
    os: 'pending',
    decision: 'pending',
    action: 'pending',
    outcome: 'pending',
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Track the current pipeline cycle to handle out-of-order events
  const cycleRef = useRef({ 
    workloadId: null, 
    stages: new Set(),
    decision: null,
  });

  const refreshAll = useCallback(async () => {
    try {
      const [status, metrics, workloadData, predictionsData, decisionsData, perfData, modelData] = await Promise.all([
        fetchSystemStatus(),
        fetchSystemMetrics(),
        fetchWorkloadRecent(20),
        fetchPredictionsRecent(20),
        fetchDecisionsRecent(20),
        fetchPerformanceMetrics(),
        fetchModelStatus(),
      ]);
      setSystemStatus(status);
      setSystemMetrics(metrics);
      setWorkload(workloadData);
      setPredictions(predictionsData);
      setDecisions(decisionsData);
      setPerformance(perfData);
      setModelStatus(modelData);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshAll();
    const interval = setInterval(refreshAll, 5000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  const handleEvent = useCallback((event) => {
    if (!event || typeof event.type !== 'string') return;
    
    setLatestEvent(event);
    
    // Update system metrics from os_state_updated events (real-time from OS service)
    if (event.type === 'os_state_updated') {
      setSystemMetrics(prev => ({
        ...prev,
        cpu_usage_percent: event.cpu_usage_percent,
        memory_total_mb: event.memory_total_mb,
        memory_used_mb: event.memory_used_mb,
        memory_available_mb: event.memory_available_mb,
        disk_read_mbps: event.disk_read_mbps,
        disk_write_mbps: event.disk_write_mbps,
        timestamp: event.timestamp,
      }));
    }
    
    // Update pipeline state based on real events only - no timers
    setPipelineState(prev => {
      const next = { ...prev };
      // Event payload fields are at root level (EventStream.emit spreads payload)
      const payload = event;
      
      switch (event.type) {
        case 'query_observed':
          // New pipeline cycle starts - reset and begin
          return {
            postgresql: 'active',
            collector: 'active',
            ml: 'pending',
            hint: 'pending',
            os: 'pending',
            decision: 'pending',
            action: 'pending',
            outcome: 'pending',
          };
          
        case 'workload_recorded':
          next.postgresql = 'completed';
          next.collector = 'completed';
          break;
          
        case 'prediction_created':
          next.ml = 'active';
          break;
          
        case 'hint_generated':
          next.ml = 'completed';
          next.hint = 'completed';
          next.os = 'active';
          break;
          
        case 'os_state_updated':
          next.os = 'completed';
          break;
          
        case 'decision_made':
          next.decision = 'completed';
          // Store decision for action stage logic
          cycleRef.current.decision = payload.decision;
          if (payload.decision === 'prefetch') {
            next.action = 'pending'; // Will be activated by action_started
          } else {
            next.action = 'completed'; // no_action means action stage is skipped/completed
            next.outcome = 'pending'; // Outcome still recorded
          }
          break;
          
        case 'action_started':
          next.action = 'active';
          break;
          
        case 'action_completed':
          next.action = 'completed';
          next.outcome = 'pending';
          break;
          
        case 'outcome_recorded':
          next.outcome = 'completed';
          break;
          
        default:
          break;
      }
      
      return next;
    });
  }, []);

  useEventStream(handleEvent);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-primary-100 mb-4">
            <Database className="w-8 h-8 text-primary-600 animate-spin" />
          </div>
          <h2 className="text-xl font-semibold text-gray-900">PrediDBOS</h2>
          <p className="text-gray-500 mt-1">Initializing dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header 
        systemStatus={systemStatus} 
        modelStatus={modelStatus}
        onRefresh={refreshAll}
      />
      
      <main className="p-4 md:p-6 lg:p-8">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 flex items-center justify-between">
            <span>Error: {error}</span>
            <button onClick={refreshAll} className="btn-secondary text-sm">Retry</button>
          </div>
        )}

        <div className="mb-6">
          <SystemMetrics metrics={systemMetrics} />
        </div>

        <div className="mb-6">
          <PipelineVisualizer 
            state={pipelineState}
            latestEvent={latestEvent}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
          <WorkloadPanel workload={workload} />
          <PredictionPanel predictions={predictions} modelStatus={modelStatus} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
          <HintPanel predictions={predictions} />
          <DecisionPanel decisions={decisions} />
        </div>

        <LiveCharts performance={performance} systemMetrics={systemMetrics} />

        <div className="mb-6">
          <ErrorBoundary fallback={<div className="card h-full"><div className="card-header"><h3 className="font-semibold text-gray-900 flex items-center gap-2"><Clock className="w-5 h-5 text-gray-500" />Live Event Timeline</h3></div><div className="card-body flex items-center justify-center h-64"><p className="text-gray-500">Event Timeline unavailable</p></div></div>}>
            <EventTimeline />
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <AppContent />
    </ErrorBoundary>
  );
}

export default App;