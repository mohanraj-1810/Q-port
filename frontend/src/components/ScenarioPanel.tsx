import { useState } from 'react'
import { useApp } from '../AppContext'
import { generateScenario, listScenarios } from '../api'

const SIZES = ['small', 'medium', 'large'] as const

export default function ScenarioPanel() {
  const { setScenario, setNetwork, setStatus, scenario } = useApp()
  const [size, setSize] = useState<'small' | 'medium' | 'large'>('small')
  const [seed, setSeed] = useState(42)
  const [loading, setLoading] = useState(false)
  const [existingIds, setExistingIds] = useState<string[]>([])
  const [showExisting, setShowExisting] = useState(false)

  const handleGenerate = async () => {
    setLoading(true)
    setStatus(`Generating ${size} scenario (seed ${seed})…`)
    try {
      const sc = await generateScenario(size, seed)
      setScenario(sc)
      setNetwork(null)
      setStatus(`Scenario '${sc.id}' ready — ${sc.containers.length} containers, ${sc.trucks.length} trucks`)
    } catch (e: any) {
      setStatus(`Error: ${e?.response?.data?.detail || e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const loadExisting = async () => {
    const ids = await listScenarios()
    setExistingIds(ids)
    setShowExisting(true)
  }

  const loadById = async (id: string) => {
    setLoading(true)
    setStatus(`Loading scenario '${id}'…`)
    try {
      const { getScenario } = await import('../api')
      const sc = await getScenario(id)
      setScenario(sc)
      setNetwork(null)
      setStatus(`Loaded '${id}'`)
      setShowExisting(false)
    } catch {
      setStatus('Load failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="panel-section">
      <div className="panel-title">Scenario</div>

      {/* Size selector */}
      <div className="tab-row" style={{ marginBottom: 10 }}>
        {SIZES.map(s => (
          <button key={s} className={`tab ${size === s ? 'active' : ''}`} onClick={() => setSize(s)}>
            {s}
          </button>
        ))}
      </div>

      {/* Seed */}
      <div style={{ marginBottom: 10 }}>
        <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
          Random seed
        </label>
        <input
          type="number"
          className="input"
          value={seed}
          onChange={e => setSeed(Number(e.target.value))}
          min={0}
          max={99999}
        />
      </div>

      <button className="btn btn-primary btn-full" onClick={handleGenerate} disabled={loading}>
        {loading ? <><span className="spinner" /> Generating…</> : '⚡ Generate Scenario'}
      </button>

      <button
        className="btn btn-secondary btn-full"
        style={{ marginTop: 6 }}
        onClick={loadExisting}
        disabled={loading}
      >
        📁 Load Existing
      </button>

      {/* Existing list */}
      {showExisting && (
        <div style={{ marginTop: 8, maxHeight: 120, overflowY: 'auto' }}>
          {existingIds.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No saved scenarios</div>
          )}
          {existingIds.map(id => (
            <button
              key={id}
              className="btn btn-secondary btn-full"
              style={{ marginBottom: 4, justifyContent: 'flex-start', fontSize: 12 }}
              onClick={() => loadById(id)}
            >
              {id}
            </button>
          ))}
        </div>
      )}

      {/* Current scenario info */}
      {scenario && (
        <div style={{ marginTop: 12 }}>
          <div className="metric">
            <span className="metric-label">ID</span>
            <span className="metric-value mono" style={{ fontSize: 11 }}>{scenario.id}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Containers</span>
            <span className="metric-value accent">{scenario.containers.length}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Trucks</span>
            <span className="metric-value accent">{scenario.trucks.length}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Network nodes</span>
            <span className="metric-value">{scenario.nodes.length}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Network edges</span>
            <span className="metric-value">{scenario.edges.length}</span>
          </div>
          {/* Priority breakdown */}
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            {[1, 2, 3].map(p => (
              <div key={p} style={{ flex: 1, textAlign: 'center' }}>
                <div className={`metric-value pri-${p}`} style={{ fontSize: 16 }}>
                  {scenario.containers.filter(c => c.priority === p).length}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  P{p}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
