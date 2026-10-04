import { 
  Database, Server, Cpu, FileJson, 
  HardDrive, GitBranch, Zap, CheckCircle,
  ArrowRight, Loader2, AlertCircle
} from 'lucide-react';
import { clsx } from 'clsx';

const PIPELINE_STEPS = [
  { key: 'postgresql', label: 'PostgreSQL', icon: Database, desc: 'Query Execution' },
  { key: 'collector', label: 'Collector', icon: Server, desc: 'Workload Capture' },
  { key: 'ml', label: 'ML Prediction', icon: Cpu, desc: 'Access Forecast' },
  { key: 'hint', label: 'JSON Hint', icon: FileJson, desc: 'Structured Hint' },
  { key: 'os', label: 'OS State', icon: HardDrive, desc: 'System Check' },
  { key: 'decision', label: 'Decision', icon: GitBranch, desc: 'Rule Evaluation' },
  { key: 'action', label: 'Action', icon: Zap, desc: 'Prefetch/Keep' },
  { key: 'outcome', label: 'Outcome', icon: CheckCircle, desc: 'Result Measure' },
];

const stepColors = {
  postgresql: 'bg-blue-100 text-blue-800',
  collector: 'bg-indigo-100 text-indigo-800',
  ml: 'bg-purple-100 text-purple-800',
  hint: 'bg-pink-100 text-pink-800',
  os: 'bg-orange-100 text-orange-800',
  decision: 'bg-amber-100 text-amber-800',
  action: 'bg-green-100 text-green-800',
  outcome: 'bg-teal-100 text-teal-800',
};

function formatTimestamp(ts) {
  if (!ts) return 'waiting...';
  try {
    const date = new Date(ts);
    if (isNaN(date.getTime())) return 'waiting...';
    return date.toLocaleTimeString();
  } catch {
    return 'waiting...';
  }
}

export default function PipelineVisualizer({ state, latestEvent }) {
  const getStepStatus = (key) => state[key] || 'pending';

  const renderArrow = (index) => (
    <div className="flex items-center px-1 text-gray-300">
      <ArrowRight className="w-5 h-5" />
    </div>
  );

  return (
    <div className="card overflow-hidden">
      <div className="card-header flex items-center justify-between">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-primary-500 animate-pulse" />
          Live Pipeline Visualizer
        </h3>
        <span className="text-xs text-gray-500 font-mono">
          Last event: {latestEvent?.type ? latestEvent.type.replace(/_/g, ' ') : 'waiting...'}
        </span>
      </div>
      <div className="card-body p-4">
        <div className="flex flex-wrap items-center gap-1 md:gap-0">
          {PIPELINE_STEPS.map((step, index) => (
            <div key={step.key} className="flex flex-col items-center min-w-[90px]">
              <div className={clsx(
                'pipeline-step w-full text-center',
                stepColors[step.key],
                getStepStatus(step.key) === 'active' && 'pipeline-step-active animate-pulse',
                getStepStatus(step.key) === 'completed' && 'pipeline-step-completed',
                getStepStatus(step.key) === 'pending' && 'pipeline-step-pending',
                getStepStatus(step.key) === 'error' && 'pipeline-step-error',
              )}>
                <div className="flex items-center justify-center gap-1.5">
                  <step.icon className="w-4 h-4" />
                  <span className="font-medium">{step.label}</span>
                  {getStepStatus(step.key) === 'active' && (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  )}
                  {getStepStatus(step.key) === 'completed' && (
                    <CheckCircle className="w-3.5 h-3.5" />
                  )}
                  {getStepStatus(step.key) === 'error' && (
                    <AlertCircle className="w-3.5 h-3.5" />
                  )}
                </div>
              </div>
              <p className="text-xs text-gray-500 text-center mt-1 max-w-[100px]">{step.desc}</p>
              {index < PIPELINE_STEPS.length - 1 && renderArrow(index)}
            </div>
          ))}
        </div>

        {latestEvent && (
          <div className="mt-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
            <div className="flex items-center gap-2 text-sm">
              <span className="font-mono text-gray-400">{formatTimestamp(latestEvent.timestamp)}</span>
              <span className="px-2 py-0.5 bg-primary-100 text-primary-700 rounded text-xs font-medium">
                {latestEvent.type.replace(/_/g, ' ')}
              </span>
              {latestEvent.payload?.predicted_object && (
                <span className="text-gray-700">→ {latestEvent.payload.predicted_object}</span>
              )}
              {latestEvent.payload?.decision && (
                <span className={clsx('px-2 py-0.5 rounded text-xs font-medium',
                  latestEvent.payload.decision === 'prefetch' && 'bg-green-100 text-green-700',
                  latestEvent.payload.decision === 'no_action' && 'bg-gray-100 text-gray-700'
                )}>
                  {latestEvent.payload.decision}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}