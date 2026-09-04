import { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { useApp } from '../AppContext'
import { benchmarkScenario, type Solution } from '../api'

export default function BenchmarkTable() {
  const { scenario, solutions, setSolution, setStatus } = useApp()
  const [loading, setLoading] = useState(false)
  const [showChart, setShowChart] = useState(true)

  const runBenchmark = async () => {
    if (!scenario) return
    setLoading(true)
    setStatus(`Running full 3-way benchmark on scenario '${scenario.id}'…`)
    try {
      const res = await benchmarkScenario(scenario.id)
      res.results.forEach(sol => setSolution(sol.method, sol))
      setStatus('Benchmark complete!')
    } catch (e: any) {
      setStatus(`Benchmark failed: ${e?.response?.data?.detail || e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const solList: Solution[] = ['qpso', 'ortools', 'ga']
    .map(m => solutions[m])
    .filter(Boolean)

  if (solList.length === 0) {
    return (
      <div className="panel-section">
        <div className="panel-title">Benchmark comparison</div>
        <button
          className="btn btn-secondary btn-full"
          onClick={runBenchmark}
          disabled={!scenario || loading}
        >
          {loading ? <><span className="spinner" /> Benchmarking…</> : '📊 Run Benchmark (QPSO vs OR-Tools vs GA)'}
        </button>
      </div>
    )
  }

  const chartData = [
    {
      metric: 'Distance (km)',
      QPSO: solutions.qpso?.total_distance_km || 0,
      'OR-Tools': solutions.ortools?.total_distance_km || 0,
      GA: solutions.ga?.total_distance_km || 0,
    },
    {
      metric: 'Time (min)',
      QPSO: solutions.qpso?.total_time_min || 0,
      'OR-Tools': solutions.ortools?.total_time_min || 0,
      GA: solutions.ga?.total_time_min || 0,
    },
    {
      metric: 'Cost (₹k)',
      QPSO: (solutions.qpso?.total_cost || 0) / 1000,
      'OR-Tools': (solutions.ortools?.total_cost || 0) / 1000,
      GA: (solutions.ga?.total_cost || 0) / 1000,
    },
    {
      metric: 'Runtime (ms)',
      QPSO: solutions.qpso?.runtime_ms || 0,
      'OR-Tools': solutions.ortools?.runtime_ms || 0,
      GA: solutions.ga?.runtime_ms || 0,
    },
  ]

  return (
    <div className="panel-section">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div className="panel-title" style={{ margin: 0 }}>Benchmark Matrix</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="btn btn-sm btn-secondary" onClick={() => setShowChart(!showChart)}>
            {showChart ? 'Table View' : 'Chart View'}
          </button>
          <button className="btn btn-sm btn-primary" onClick={runBenchmark} disabled={loading}>
            {loading ? <span className="spinner" /> : 'Re-run'}
          </button>
        </div>
      </div>

      {!showChart ? (
        <table className="bench-table">
          <thead>
            <tr>
              <th>Method</th>
              <th>Fitness</th>
              <th>Dist (km)</th>
              <th>Time (m)</th>
              <th>Cost (₹)</th>
              <th>Viol</th>
              <th>Run (ms)</th>
            </tr>
          </thead>
          <tbody>
            {solList.map(sol => (
              <tr key={sol.method}>
                <td>
                  <span className={`badge badge-${sol.method}`}>{sol.method.toUpperCase()}</span>
                </td>
                <td className="accent">{sol.fitness.toFixed(4)}</td>
                <td>{sol.total_distance_km.toFixed(1)}</td>
                <td>{sol.total_time_min.toFixed(1)}</td>
                <td>₹{sol.total_cost.toLocaleString()}</td>
                <td className={sol.constraint_violations > 0 ? 'worst' : 'best'}>
                  {sol.constraint_violations}
                </td>
                <td className="success">{sol.runtime_ms.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ width: '100%', height: 180, marginTop: 10 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <XAxis dataKey="metric" stroke="#555570" tick={{ fill: '#8888aa', fontSize: 11 }} />
              <YAxis stroke="#555570" tick={{ fill: '#8888aa', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: '#16161f', borderColor: '#2a2a3d', color: '#f0f0f8', borderRadius: 6 }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="QPSO" fill="#818cf8" radius={[4, 4, 0, 0]} />
              <Bar dataKey="OR-Tools" fill="#4ade80" radius={[4, 4, 0, 0]} />
              <Bar dataKey="GA" fill="#fb923c" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
