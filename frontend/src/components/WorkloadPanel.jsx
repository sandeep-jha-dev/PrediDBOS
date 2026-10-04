import { Database, Clock, Zap, Eye, EyeOff } from 'lucide-react';
import { clsx } from 'clsx';
import { useState } from 'react';

const patternColors = {
  sequential: 'bg-blue-100 text-blue-700',
  random: 'bg-orange-100 text-orange-700',
  bitmap: 'bg-purple-100 text-purple-700',
  index: 'bg-green-100 text-green-700',
  default: 'bg-gray-100 text-gray-700',
};

export default function WorkloadPanel({ workload }) {
  const [showQueries, setShowQueries] = useState(true);

  if (!workload || workload.length === 0) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Database className="w-5 h-5 text-gray-500" />
            Live Workload
          </h3>
        </div>
        <div className="card-body flex items-center justify-center h-64">
          <div className="text-center text-gray-500">
            <Database className="w-12 h-12 mx-auto mb-2 text-gray-300" />
            <p>No workload data yet</p>
            <p className="text-sm">Execute queries to see activity</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header flex items-center justify-between">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Database className="w-5 h-5 text-gray-500" />
          Live Workload
        </h3>
        <button 
          onClick={() => setShowQueries(!showQueries)}
          className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
        >
          {showQueries ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          <span className="hidden sm:inline">{showQueries ? 'Hide' : 'Show'} Queries</span>
        </button>
      </div>
      <div className="card-body flex-1 overflow-hidden">
        {showQueries && (
          <div className="overflow-y-auto max-h-96 scrollbar-thin">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wider">
                  <th className="pb-2 pr-3 font-medium">Time</th>
                  <th className="pb-2 pr-3 font-medium">Object</th>
                  <th className="pb-2 pr-3 font-medium">Pattern</th>
                  <th className="pb-2 pr-3 font-medium">Type</th>
                  <th className="pb-2 pr-3 font-medium text-right">Time (ms)</th>
                  <th className="pb-2 font-medium">Cache</th>
                </tr>
              </thead>
              <tbody>
                {workload.slice(0, 30).map((row, idx) => (
                  <tr key={row.id || idx} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-2 pr-3 font-mono text-gray-600">
                      {new Date(row.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="py-2 pr-3 text-gray-900 font-medium max-w-[150px] truncate">
                      {row.object_name || '—'}
                    </td>
                    <td className="py-2 pr-3">
                      <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', patternColors[row.access_pattern] || patternColors.default)}>
                        {row.access_pattern || '—'}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-gray-600 text-xs">{row.query_type || '—'}</td>
                    <td className="py-2 pr-3 text-right font-mono text-gray-600">
                      {row.execution_time_ms ? row.execution_time_ms.toFixed(1) : '—'}
                    </td>
                    <td className="py-2">
                      {row.shared_blks_hit !== undefined && row.shared_blks_read !== undefined ? (
                        <span className={clsx('px-2 py-0.5 rounded text-xs font-medium',
                          row.shared_blks_hit > row.shared_blks_read ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                        )}>
                          {row.shared_blks_hit > row.shared_blks_read ? 'Hit' : 'Miss'}
                        </span>
                      ) : (
                        <span className="text-gray-400 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!showQueries && (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            <p className="text-sm">Click "Show Queries" to see workload</p>
          </div>
        )}
      </div>
    </div>
  );
}