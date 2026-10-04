import { Cpu, MemoryStick, HardDrive, Activity, Database, Wifi, Clock } from 'lucide-react';
import { clsx } from 'clsx';

const METRICS = [
  { key: 'cpu_usage_percent', label: 'CPU Usage', icon: Cpu, unit: '%', max: 100, color: 'text-blue-600', bgColor: 'bg-blue-100' },
  { key: 'memory_usage_percent', label: 'Memory Usage', icon: MemoryStick, unit: '%', max: 100, color: 'text-green-600', bgColor: 'bg-green-100' },
  { key: 'memory_available_mb', label: 'Available RAM', icon: MemoryStick, unit: ' GB', max: null, color: 'text-emerald-600', bgColor: 'bg-emerald-100', format: (v) => v ? Number((v / 1024).toFixed(1)) : null },
  { key: 'disk_read_mbps', label: 'Disk Read', icon: HardDrive, unit: ' MB/s', max: null, color: 'text-orange-600', bgColor: 'bg-orange-100' },
  { key: 'disk_write_mbps', label: 'Disk Write', icon: HardDrive, unit: ' MB/s', max: null, color: 'text-red-600', bgColor: 'bg-red-100' },
  { key: 'io_wait_percent', label: 'I/O Wait', icon: Activity, unit: '%', max: 100, color: 'text-purple-600', bgColor: 'bg-purple-100' },
];

function formatTimestamp(ts) {
  if (!ts) return '—';
  try {
    const date = new Date(ts);
    if (isNaN(date.getTime())) return '—';
    return date.toLocaleTimeString();
  } catch {
    return '—';
  }
}

export default function SystemMetrics({ metrics }) {
  const memoryUsagePercent = metrics.memory_total_mb && metrics.memory_used_mb
    ? Number(((metrics.memory_used_mb / metrics.memory_total_mb) * 100).toFixed(1))
    : null;

  const displayMetrics = METRICS.map(m => ({
    ...m,
    value: m.key === 'memory_usage_percent' ? memoryUsagePercent : metrics[m.key],
    formattedValue: m.format ? m.format(metrics[m.key]) : metrics[m.key],
  }));

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      {displayMetrics.map((metric) => {
        const rawValue = metric.formattedValue ?? metric.value;
        const numValue = typeof rawValue === 'string' ? Number(rawValue) : rawValue;
        const isValidNumber = typeof numValue === 'number' && !isNaN(numValue);
        const displayValue = isValidNumber ? numValue : '—';
        const percent = metric.max && isValidNumber ? Math.min(100, (numValue / metric.max) * 100) : null;

        return (
          <div key={metric.key} className="metric-card">
            <div className="flex items-center justify-between mb-2">
              <div className={clsx('p-2 rounded-lg', metric.bgColor)}>
                <metric.icon className={clsx('w-5 h-5', metric.color)} />
              </div>
              {percent !== null && (
                <div className="w-24 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                  <div 
                    className={clsx('h-full rounded-full transition-all duration-500', metric.color.replace('text-', 'bg-'))}
                    style={{ width: `${percent}%` }}
                  />
                </div>
              )}
            </div>
            <div className="metric-value font-mono">{displayValue}{metric.unit && typeof displayValue !== 'string' ? metric.unit : ''}</div>
            <div className="metric-label">{metric.label}</div>
          </div>
        );
      })}
      {metrics.timestamp && (
        <div className="col-span-2 md:col-span-3 lg:col-span-6 flex items-center justify-end text-xs text-gray-500 mt-2">
          <Clock className="w-3.5 h-3.5 mr-1" />
          Last update: {formatTimestamp(metrics.timestamp)}
        </div>
      )}
    </div>
  );
}