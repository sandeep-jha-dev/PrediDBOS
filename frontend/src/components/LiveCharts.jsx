import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, 
  Tooltip, ResponsiveContainer, Legend, AreaChart, Area 
} from 'recharts';
import { clsx } from 'clsx';

const CHART_COLORS = {
  cpu: '#3b82f6',
  memory: '#10b981',
  diskRead: '#f59e0b',
  diskWrite: '#ef4444',
  executionTime: '#8b5cf6',
  cacheHit: '#06b6d4',
  predictionAccuracy: '#ec4899',
  prefetch: '#22c55e',
  noAction: '#6b7280',
};

function MetricChart({ title, data, lines, height = 200 }) {
  if (!data || data.length === 0) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <h4 className="font-medium text-gray-900">{title}</h4>
        </div>
        <div className="card-body flex items-center justify-center" style={{ height }}>
          <p className="text-gray-500 text-sm">No data available</p>
        </div>
      </div>
    );
  }

  // Filter out invalid data points
  const validData = data.filter(d => d && typeof d.time !== 'undefined');

  if (validData.length === 0) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <h4 className="font-medium text-gray-900">{title}</h4>
        </div>
        <div className="card-body flex items-center justify-center" style={{ height }}>
          <p className="text-gray-500 text-sm">No valid data points</p>
        </div>
      </div>
    );
  }

  return (
    <div className="card h-full">
      <div className="card-header">
        <h4 className="font-medium text-gray-900">{title}</h4>
      </div>
      <div className="card-body" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={validData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis 
              dataKey="time" 
              tick={{ fontSize: 10, fill: '#6b7280' }}
              tickFormatter={(v) => {
                try { return new Date(v).toLocaleTimeString(); } catch { return ''; }
              }}
              interval="preserveStartEnd"
            />
            <YAxis 
              tick={{ fontSize: 10, fill: '#6b7280' }}
              orientation="left"
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }}
              labelFormatter={(v) => {
                try { return new Date(v).toLocaleTimeString(); } catch { return ''; }
              }}
            />
            <Legend wrapperStyle={{ paddingTop: '10px' }} />
            {lines.map((line, idx) => (
              <Line
                key={line.key}
                type="monotone"
                dataKey={line.key}
                stroke={line.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
                name={line.name}
                animationDuration={300}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function AreaMetricChart({ title, data, key, color, name, height = 200 }) {
  if (!data || data.length === 0) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <h4 className="font-medium text-gray-900">{title}</h4>
        </div>
        <div className="card-body flex items-center justify-center" style={{ height }}>
          <p className="text-gray-500 text-sm">No data available</p>
        </div>
      </div>
    );
  }

  const validData = data.filter(d => d && typeof d.time !== 'undefined' && typeof d[key] === 'number');

  if (validData.length === 0) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <h4 className="font-medium text-gray-900">{title}</h4>
        </div>
        <div className="card-body flex items-center justify-center" style={{ height }}>
          <p className="text-gray-500 text-sm">No valid data points</p>
        </div>
      </div>
    );
  }

  return (
    <div className="card h-full">
      <div className="card-header">
        <h4 className="font-medium text-gray-900">{title}</h4>
      </div>
      <div className="card-body" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={validData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis 
              dataKey="time" 
              tick={{ fontSize: 10, fill: '#6b7280' }}
              tickFormatter={(v) => {
                try { return new Date(v).toLocaleTimeString(); } catch { return ''; }
              }}
              interval="preserveStartEnd"
            />
            <YAxis 
              tick={{ fontSize: 10, fill: '#6b7280' }}
              orientation="left"
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }}
              labelFormatter={(v) => {
                try { return new Date(v).toLocaleTimeString(); } catch { return ''; }
              }}
            />
            <Area
              type="monotone"
              dataKey={key}
              stroke={color}
              fill={color}
              fillOpacity={0.15}
              strokeWidth={2}
              name={name}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function LiveCharts({ performance, systemMetrics }) {
  const perfData = performance?.baseline || performance?.predidbos ? 
    Object.entries(performance).flatMap(([mode, metrics]) => 
      (metrics.history || []).map((point, i) => ({
        time: point.timestamp || point.minute,
        mode,
        execution_time_ms: point.avg_execution_time || point.execution_time_ms,
        disk_read_mb: point.disk_read_mb || point.disk_read_bytes / 1024 / 1024,
        cache_hit_rate: point.cache_hit_rate,
      }))
    ) : [];

  const osHistory = systemMetrics?.history || [];
  const formattedOsData = osHistory.map(p => ({
    time: p.timestamp,
    cpu: p.cpu_usage_percent,
    memory_used: p.memory_used_mb,
    memory_available: p.memory_available_mb,
    disk_read: p.disk_read_mbps,
    disk_write: p.disk_write_mbps,
    io_wait: p.io_wait_percent,
  })).filter(p => p.time && !isNaN(new Date(p.time).getTime()));

  const actionData = performance?.actions || [];
  const formattedActions = actionData.map(p => ({
    time: p.minute,
    prefetch: p.prefetch || 0,
    no_action: p.no_action || 0,
  })).filter(p => p.time && !isNaN(new Date(p.time).getTime()));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <MetricChart
        title="System Resources (Live)"
        data={formattedOsData.slice(-60)}
        lines={[
          { key: 'cpu', name: 'CPU %', color: CHART_COLORS.cpu },
          { key: 'memory_available', name: 'Available RAM (MB)', color: CHART_COLORS.memory },
          { key: 'disk_read', name: 'Disk Read MB/s', color: CHART_COLORS.diskRead },
          { key: 'disk_write', name: 'Disk Write MB/s', color: CHART_COLORS.diskWrite },
        ]}
      />

      <MetricChart
        title="Query Execution Time"
        data={perfData.slice(-60)}
        lines={[
          { key: 'execution_time_ms', name: 'Avg Time (ms)', color: CHART_COLORS.executionTime },
        ]}
      />

      <AreaMetricChart
        title="Cache Hit Rate"
        data={perfData.slice(-60)}
        key="cache_hit_rate"
        color={CHART_COLORS.cacheHit}
        name="Hit Rate"
      />

      <MetricChart
        title="PrediDBOS Actions"
        data={formattedActions.slice(-60)}
        lines={[
          { key: 'prefetch', name: 'Prefetch', color: CHART_COLORS.prefetch },
          { key: 'no_action', name: 'No Action', color: CHART_COLORS.noAction },
        ]}
      />
    </div>
  );
}