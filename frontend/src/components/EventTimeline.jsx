import { useState, useEffect } from 'react';
import { 
  Database, Server, Cpu, FileJson, 
  HardDrive, GitBranch, Zap, CheckCircle,
  Clock, XCircle, AlertCircle, Loader2, Activity, BarChart2, RotateCcw
} from 'lucide-react';
import { clsx } from 'clsx';
import { useEventStream } from '../hooks/useEventStream';

const eventIcons = {
  query_observed: Database,
  workload_recorded: Server,
  prediction_created: Cpu,
  hint_generated: FileJson,
  os_state_updated: HardDrive,
  decision_made: GitBranch,
  action_started: Zap,
  action_completed: Zap,
  outcome_recorded: CheckCircle,
  error: AlertCircle,
  system_status: Activity,
  default: Activity,
};

const eventColors = {
  query_observed: 'text-blue-600 bg-blue-100',
  workload_recorded: 'text-indigo-600 bg-indigo-100',
  prediction_created: 'text-purple-600 bg-purple-100',
  hint_generated: 'text-pink-600 bg-pink-100',
  os_state_updated: 'text-orange-600 bg-orange-100',
  decision_made: 'text-amber-600 bg-amber-100',
  action_started: 'text-green-600 bg-green-100',
  action_completed: 'text-green-600 bg-green-100',
  outcome_recorded: 'text-teal-600 bg-teal-100',
  error: 'text-red-600 bg-red-100',
  system_status: 'text-gray-600 bg-gray-100',
  default: 'text-gray-600 bg-gray-100',
};

const eventLabels = {
  query_observed: 'Query Observed',
  workload_recorded: 'Workload Recorded',
  prediction_created: 'ML Prediction',
  hint_generated: 'JSON Hint Generated',
  os_state_updated: 'OS State Check',
  decision_made: 'Decision Made',
  action_started: 'Action Started',
  action_completed: 'Action Completed',
  outcome_recorded: 'Outcome Recorded',
  error: 'Error',
  system_status: 'System Status',
  default: 'Unknown Event',
};

const payloadFormatters = {
  query_observed: (p) => p?.object ? `${p.object} (${p.access_pattern || '?'})` : 'Unknown query',
  workload_recorded: (p) => p?.object_name ? `Saved: ${p.object_name}` : 'Recorded',
  prediction_created: (p) => p?.prediction ? `${p.prediction.object} — ${((p.prediction.confidence || 0) * 100).toFixed(0)}%` : 'Prediction created',
  hint_generated: (p) => p?.predicted_object ? `Hint for ${p.predicted_object}` : 'Hint sent',
  os_state_updated: (p) => `RAM: ${p?.available_memory_mb ? (p.available_memory_mb/1024).toFixed(1)+' GB' : '?'} • CPU: ${p?.cpu_usage_percent?.toFixed(1)+'%' || '?'}`,
  decision_made: (p) => `${p?.decision?.replace('_', ' ') || '?'} — ${p?.reason || ''}`,
  action_started: (p) => `Prefetch: ${p?.object || '?'}`,
  action_completed: (p) => `Completed: ${p?.object || '?'}`,
  outcome_recorded: (p) => p?.prediction_correct !== undefined ? (p.prediction_correct ? '✓ Correct' : '✗ Incorrect') : 'Measured',
  error: (p) => p?.message || 'Unknown error',
  system_status: (p) => `PostgreSQL: ${p?.postgresql || '?'} • Collector: ${p?.collector || '?'} • ML: ${p?.ml_model || '?'} • OS: ${p?.os_service || '?'}`,
  default: (p) => p ? JSON.stringify(p).slice(0, 100) : '—',
};

function safeEventItem(event, idx) {
  try {
    if (!event || typeof event.type !== 'string') {
      return null;
    }
    
    const type = event.type;
    
    // Safe lookup with fallback
    const Icon = eventIcons[type] || eventIcons.default;
    const colorClass = eventColors[type] || eventColors.default;
    const label = eventLabels[type] || eventLabels.default;
    const formatter = payloadFormatters[type] || payloadFormatters.default;
    
    // Safe timestamp parsing
    const timestamp = event.timestamp ? new Date(event.timestamp) : null;
    const timeStr = (timestamp && !isNaN(timestamp.getTime())) 
      ? timestamp.toLocaleTimeString() 
      : '—';
    
    // Safe payload formatting
    let payloadText = '—';
    try {
      payloadText = formatter ? formatter(event.payload) : '—';
    } catch (e) {
      payloadText = 'Format error';
    }
    
    // Ensure Icon is a valid component
    const IconComponent = eventIcons[type] || eventIcons.default;
    if (!IconComponent) {
      console.error('Invalid icon component for type:', type);
      return (
        <div key={`${event?.timestamp || 'err'}-${idx}`} className="flex items-start gap-3 p-2 bg-red-50 border border-red-200 rounded">
          <span className="text-red-600 text-xs font-mono">Invalid icon for event type: {type}</span>
        </div>
      );
    }

    return (
      <div 
        key={`${event.timestamp || 'no-ts'}-${idx}`}
        className="flex items-start gap-3 animate-fade-in"
      >
        <div className="flex-shrink-0 w-10 text-center">
          <span className="text-xs text-gray-400 font-mono">
            {timestamp && !isNaN(timestamp.getTime()) ? timestamp.toLocaleTimeString() : '—'}
          </span>
        </div>
        <div className={clsx('flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center', colorClass)}>
          <IconComponent className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900">{eventLabels[type] || eventLabels.default}</span>
            {event.payload?.decision && (
              <span className={clsx('px-1.5 py-0.5 rounded text-xs font-medium',
                event.payload.decision === 'prefetch' && 'bg-green-100 text-green-700',
                event.payload.decision === 'no_action' && 'bg-gray-100 text-gray-700'
              )}>
                {event.payload.decision}
              </span>
            )}
            {type === 'prediction_created' && event.payload?.prediction && (
              <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                {((event.payload.prediction.confidence || 0) * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <div className="text-sm text-gray-500 mt-0.5 font-mono">
            {payloadText}
          </div>
        </div>
      </div>
    );
  } catch (err) {
    console.error('EventTimeline render error:', err, 'event:', event);
    return (
      <div key={`${event?.timestamp || 'err'}-${idx}`} className="flex items-start gap-3 animate-fade-in p-2 bg-red-50 border border-red-200 rounded">
        <span className="text-red-600 text-xs font-mono">Render error for event type: {event?.type || 'unknown'}</span>
      </div>
    );
  }
}

function EventTimelineContent() {
  const [events, setEvents] = useState([]);

  useEventStream((event) => {
    if (event && typeof event.type === 'string') {
      setEvents(prev => [event, ...prev].slice(0, 100));
    }
  });

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header flex items-center justify-between">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Clock className="w-5 h-5 text-gray-500" />
          Live Event Timeline
        </h3>
        <button 
          onClick={() => setEvents([])}
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          Clear
        </button>
      </div>
      <div className="card-body flex-1 overflow-hidden">
        <div className="overflow-y-auto max-h-96 scrollbar-thin space-y-2">
          {events.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              <p className="text-sm">Waiting for events...</p>
            </div>
          ) : (
            events.map((event, idx) => safeEventItem(event, idx))
          )}
        </div>
      </div>
    </div>
  );
}

export default function EventTimeline() {
  try {
    return <EventTimelineContent />;
  } catch (err) {
    console.error('EventTimeline wrapper error:', err);
    return (
      <div className="card h-full flex flex-col">
        <div className="card-header flex items-center justify-between">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Clock className="w-5 h-5 text-gray-500" />
            Live Event Timeline
          </h3>
        </div>
        <div className="card-body flex-1 overflow-hidden p-4 text-center text-red-600">
          <p className="font-mono text-sm">EventTimeline component error: {err?.message || 'Unknown error'}</p>
        </div>
      </div>
    );
  }
}