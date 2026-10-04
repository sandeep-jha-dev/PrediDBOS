import { Cpu, Target, TrendingUp, AlertCircle, CheckCircle, XCircle } from 'lucide-react';
import { clsx } from 'clsx';

export default function PredictionPanel({ predictions, modelStatus }) {
  const latest = predictions[0];
  const recentPredictions = predictions.slice(0, 10);

  const getConfidenceColor = (conf) => {
    if (conf >= 0.9) return 'text-green-600 bg-green-100';
    if (conf >= 0.7) return 'text-yellow-600 bg-yellow-100';
    return 'text-red-600 bg-red-100';
  };

  const getConfidenceLabel = (conf) => {
    if (conf >= 0.9) return 'HIGH';
    if (conf >= 0.7) return 'MEDIUM';
    return 'LOW';
  };

  if (!latest) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Cpu className="w-5 h-5 text-gray-500" />
            ML Prediction
          </h3>
        </div>
        <div className="card-body flex items-center justify-center h-64">
          <div className="text-center text-gray-500">
            <Cpu className="w-12 h-12 mx-auto mb-2 text-gray-300" />
            <p>No predictions yet</p>
            <p className="text-sm">Workload will trigger predictions</p>
          </div>
        </div>
      </div>
    );
  }

  const confidence = typeof latest.confidence === 'number' && !isNaN(latest.confidence) ? latest.confidence : 0;

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Cpu className="w-5 h-5 text-gray-500" />
          ML Prediction
        </h3>
      </div>
      <div className="card-body flex-1">
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div className="p-4 bg-gray-50 rounded-lg">
            <div className="text-xs text-gray-500 mb-1">Predicted Object</div>
            <div className="text-xl font-bold text-gray-900 font-mono">{latest.predicted_object || '—'}</div>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <div className="text-xs text-gray-500 mb-1">Access Pattern</div>
            <div className="text-xl font-bold text-gray-900 capitalize">{latest.predicted_access_pattern || '—'}</div>
          </div>
        </div>

        <div className="mb-6">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-gray-500">Confidence</span>
            <span className={clsx('font-semibold px-2 py-0.5 rounded', getConfidenceColor(confidence))}>
              {(confidence * 100).toFixed(1)}% — {getConfidenceLabel(confidence)}
            </span>
          </div>
          <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
            <div 
              className={clsx('h-full rounded-full transition-all duration-500', getConfidenceColor(confidence).replace('text-', 'bg-').replace('bg-', 'bg-'))}
              style={{ width: `${(confidence * 100).toFixed(1)}%` }}
            />
          </div>
        </div>

        <div className="mb-6 p-3 bg-gray-50 rounded-lg">
          <div className="flex items-center gap-2 text-sm mb-2">
            <span className="text-gray-500">Model</span>
            <span className="font-mono text-gray-900">{modelStatus?.model_version || '—'}</span>
            {modelStatus?.is_active && (
              <span className="px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-xs">Active</span>
            )}
          </div>
          <div className="text-xs text-gray-500">
            Trained: {modelStatus?.trained_at ? new Date(modelStatus.trained_at).toLocaleString() : '—'}
          </div>
        </div>

        <div className="border-t border-gray-200 pt-4">
          <h4 className="text-sm font-medium text-gray-700 mb-3">Recent Predictions</h4>
          <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin">
            {recentPredictions.map((p, idx) => {
              const predConfidence = typeof p.confidence === 'number' && !isNaN(p.confidence) ? p.confidence : 0;
              return (
                <div key={p.id || idx} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="w-2 h-2 rounded-full bg-gray-300" />
                    <div>
                      <div className="font-mono text-sm text-gray-900 truncate max-w-[180px]">{p.predicted_object}</div>
                      <div className="text-xs text-gray-500">{p.predicted_access_pattern} • {(predConfidence * 100).toFixed(0)}%</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {p.prediction_correct === true && <CheckCircle className="w-4 h-4 text-green-500" title="Correct" />}
                    {p.prediction_correct === false && <XCircle className="w-4 h-4 text-red-500" title="Incorrect" />}
                    {p.prediction_correct === undefined && <span className="w-4 h-4 text-gray-300" title="Pending" />}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

const getConfidenceColor = (conf) => {
  if (conf >= 0.9) return 'text-green-600 bg-green-100';
  if (conf >= 0.7) return 'text-yellow-600 bg-yellow-100';
  return 'text-red-600 bg-red-100';
};

const getConfidenceLabel = (conf) => {
  if (conf >= 0.9) return 'HIGH';
  if (conf >= 0.7) return 'MEDIUM';
  return 'LOW';
};