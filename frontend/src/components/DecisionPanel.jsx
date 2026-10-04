import { GitBranch, CheckCircle, XCircle, AlertCircle, Info, Database, HardDrive, Cpu, MemoryStick, Zap } from 'lucide-react';
import { clsx } from 'clsx';

const decisionStyles = {
  prefetch: 'bg-green-100 text-green-700 border-green-200',
  no_action: 'bg-gray-100 text-gray-700 border-gray-200',
  keep_hot: 'bg-blue-100 text-blue-700 border-blue-200',
  evict: 'bg-red-100 text-red-700 border-red-200',
};

const decisionIcons = {
  prefetch: Zap,
  no_action: XCircle,
  keep_hot: Database,
  evict: AlertCircle,
};

function toNumber(val) {
  const n = Number(val);
  return isNaN(n) ? null : n;
}

export default function DecisionPanel({ decisions }) {
  const latest = decisions[0];

  if (!latest) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-gray-500" />
            OS Decision
          </h3>
        </div>
        <div className="card-body flex items-center justify-center h-64">
          <div className="text-center text-gray-500">
            <GitBranch className="w-12 h-12 mx-auto mb-2 text-gray-300" />
            <p>No decisions yet</p>
            <p className="text-sm">Predictions will trigger decisions</p>
          </div>
        </div>
      </div>
    );
  }

  const DecisionIcon = decisionIcons[latest.decision] || GitBranch;
  const decisionClass = decisionStyles[latest.decision] || decisionStyles.no_action;

  const availableMemoryMb = toNumber(latest.available_memory_mb);
  const cpuUsage = toNumber(latest.cpu_usage_percent);
  const diskReadMbps = toNumber(latest.disk_io_read_mbps);

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <GitBranch className="w-5 h-5 text-gray-500" />
          OS Decision
        </h3>
      </div>
      <div className="card-body flex-1">
        <div className={clsx('p-4 rounded-lg border', decisionClass, 'mb-6')}>
          <div className="flex items-center gap-3">
            <div className="p-3 bg-white/50 rounded-lg">
              <DecisionIcon className="w-6 h-6" />
            </div>
            <div>
              <div className="text-lg font-bold capitalize">{latest.decision.replace('_', ' ')}</div>
              <div className="text-sm opacity-80">{latest.reason || 'No reason provided'}</div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 mb-6">
          <div className="p-3 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
              <MemoryStick className="w-3.5 h-3.5" />
              Available RAM
            </div>
            <div className="font-mono text-lg text-gray-900">
              {availableMemoryMb !== null ? `${(availableMemoryMb / 1024).toFixed(1)} GB` : '—'}
            </div>
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
              <Cpu className="w-3.5 h-3.5" />
              CPU Usage
            </div>
            <div className="font-mono text-lg text-gray-900">
              {cpuUsage !== null ? `${cpuUsage.toFixed(1)}%` : '—'}
            </div>
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
              <HardDrive className="w-3.5 h-3.5" />
              Disk I/O
            </div>
            <div className="font-mono text-lg text-gray-900">
              {diskReadMbps !== null ? `${diskReadMbps.toFixed(1)} MB/s` : '—'}
            </div>
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
              <Database className="w-3.5 h-3.5" />
              Already Cached
            </div>
            <div className="font-mono text-lg text-gray-900">
              {latest.already_cached ? 'Yes' : 'No'}
            </div>
          </div>
        </div>

        <div className="border-t border-gray-200 pt-4">
          <h4 className="text-sm font-medium text-gray-700 mb-3">Recent Decisions</h4>
          <div className="space-y-2 max-h-48 overflow-y-auto scrollbar-thin">
            {decisions.slice(0, 10).map((d, idx) => (
              <div key={d.id || idx} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', decisionStyles[d.decision])}>
                    {d.decision.replace('_', ' ')}
                  </span>
                  <span className="text-xs text-gray-500 truncate max-w-[200px]">{d.reason}</span>
                </div>
                <div className="text-xs text-gray-400 font-mono">
                  {new Date(d.timestamp).toLocaleTimeString()}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}