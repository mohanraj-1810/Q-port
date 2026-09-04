import { useState } from 'react'
import { useApp } from '../AppContext'
import { solveScenario, getNetwork, type Solution } from '../api'

const METHODS = [
  { id: 'qpso', label: 'QPSO (Core)' },
  { id: 'ortools', label: 'OR-Tools' },
  { id: 'ga', label: 'Genetic Alg' },
  { id: 'all', label: 'All (Benchmark)' },
]

export default function SolvePanel() {
  const { scenario, solutions, setSolution, setNetwork, activeMethod, setActiveMethod, setStatus } = useApp()
  const [loading, setLoading] = useState(false)

  const handleSolve = async () => {
    if (!scenario) return
    setLoading(true)
    setStatus(`Running ${activeMethod.toUpperCase()} solver on scenario '${scenario.id}'…`)

    try {
      const res = await solveScenario(scenario.id, activeMethod)
      
      if (Array.isArray(res)) {
        res.forEach((sol: Solution) => setSolution(sol.method, sol))
        // fetch network routes for current active method or qpso
        const net = await getNetwork(scenario.id, activeMethod === 'all' ? 'qpso' : activeMethod)
        setNetwork(net)
      } else {
        setSolution(res.method, res)
        const net = await getNetwork(scenario.id, res.method)
        setNetwork(net)
      }

      setStatus(`Optimization complete for ${activeMethod.toUpperCase()}`)
    } catch (e: any) {
      setStatus(`Solve failed: ${e?.response?.data?.detail || e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const currentSol = solutions[activeMethod === 'all' ? 'qpso' : activeMethod]

  return (
    <div className="panel-section">
      <div className="panel-title">Optimization Solver</div>

      <div className="tab-row" style={{ marginBottom: 10 }}>
        {METHODS.map(m => (
          <button
            key={m.id}
            className={`tab ${activeMethod === m.id ? 'active' : ''}`}
            onClick={() => setActiveMethod(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>

      <button
        className="btn btn-primary btn-full"
        onClick={handleSolve}
        disabled={!scenario || loading}
      >
        {loading ? <><span className="spinner" /> Solving…</> : `🚀 Solve with ${activeMethod.toUpperCase()}`}
      </button>

      {currentSol && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span className={`badge badge-${currentSol.method}`}>{currentSol.method.toUpperCase()}</span>
            <span className="metric-value mono success">{currentSol.runtime_ms.toFixed(1)} ms</span>
          </div>

          <div className="metric">
            <span className="metric-label">Fitness Score</span>
            <span className="metric-value mono accent">{currentSol.fitness.toFixed(4)}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Total Distance</span>
            <span className="metric-value mono">{currentSol.total_distance_km.toFixed(1)} km</span>
          </div>
          <div className="metric">
            <span className="metric-label">Total Travel Time</span>
            <span className="metric-value mono">{currentSol.total_time_min.toFixed(1)} min</span>
          </div>
          <div className="metric">
            <span className="metric-label">Total Cost</span>
            <span className="metric-value mono">₹{currentSol.total_cost.toLocaleString()}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Violations</span>
            <span className={`metric-value mono ${currentSol.constraint_violations > 0 ? 'danger' : 'success'}`}>
              {currentSol.constraint_violations}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Trucks Used</span>
            <span className="metric-value mono">
              {currentSol.assignments.filter(a => a.container_sequence.length > 0).length} / {scenario?.trucks.length}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
