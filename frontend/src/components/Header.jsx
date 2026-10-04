import { Database, Server, Cpu, Activity, RefreshCw, GitBranch } from 'lucide-react';
import { clsx } from 'clsx';

const statusStyles = {
  online: 'status-online',
  degraded: 'status-degraded',
  offline: 'status-offline',
  unknown: 'status-unknown',
  connected: 'status-online',
  disconnected: 'status-offline',
  unreachable: 'status-offline',
};

const statusIcons = {
  postgresql: Database,
  collector: Server,
  ml_model: Cpu,
  os_service: Activity,
};

export default function Header({ systemStatus, modelStatus, onRefresh }) {
  const overallStatus = systemStatus?.status || 'unknown';
  const components = systemStatus?.components || {};

  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-40">
      <div className="max-w-full mx-auto px-4 md:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between h-16 md:h-14 gap-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary-100">
              <Database className="w-6 h-6 text-primary-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">PrediDBOS</h1>
              <p className="text-xs text-gray-500">Workload-aware Memory Collaboration</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className={clsx('status-badge', statusStyles[overallStatus])}>
              <span className={clsx('w-1.5 h-1.5 rounded-full mr-1.5', 
                overallStatus === 'online' && 'bg-green-500 animate-pulse',
                overallStatus === 'degraded' && 'bg-yellow-500',
                overallStatus === 'offline' && 'bg-red-500',
                overallStatus === 'unknown' && 'bg-gray-400'
              )} />
              {overallStatus.charAt(0).toUpperCase() + overallStatus.slice(1)}
            </div>

            <div className="hidden sm:flex items-center gap-2 border-l border-gray-200 pl-3">
              {Object.entries(components).map(([key, value]) => {
                const Icon = statusIcons[key];
                return (
                  <div key={key} className="flex items-center gap-1.5" title={key}>
                    <Icon 
                      className={clsx('w-4 h-4', statusStyles[value]?.replace('bg-', 'text-').replace('text-', 'text-'))} 
                    />
                    <span className="text-xs text-gray-500 capitalize">{key.replace('_', ' ')}</span>
                  </div>
                );
              })}
            </div>

            {modelStatus?.model_version && (
              <div className="hidden md:flex items-center gap-1.5 px-2 py-1 bg-gray-50 rounded-lg border border-gray-200">
                <GitBranch className="w-3.5 h-3.5 text-gray-500" />
                <span className="text-xs font-mono text-gray-700">{modelStatus.model_version}</span>
                {modelStatus.is_active && (
                  <span className="status-badge status-online text-xs">Active</span>
                )}
              </div>
            )}

            <button 
              onClick={onRefresh}
              className="btn-secondary flex items-center gap-2"
              disabled={false}
            >
              <RefreshCw className="w-4 h-4" />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}