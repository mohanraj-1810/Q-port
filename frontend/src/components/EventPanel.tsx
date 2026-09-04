import { useState } from 'react'
import { useApp } from '../AppContext'
import { injectEvent, getNetwork, type EventPayload } from '../api'

export default function EventPanel() {
  const { scenario, solutions, eventResult, setEventResult, setSolution, setNetwork, setStatus } = useApp()
  const [eventType, setEventType] = useState<EventPayload['type']>('truck_breakdown')
  const [loading, setLoading] = useState(false)

  // Event parameters
  const [selectedTruck, setSelectedTruck] = useState('')
  const [trafficMultiplier, setTrafficMultiplier] = useState(2.5)
  const [newWeight] = useState(12000)

  const handleInject = async () => {
    if (!scenario) return
    const currentSol = solutions.qpso || solutions.ortools || solutions.ga
    if (!currentSol) {
      setStatus('Please solve the scenario first before injecting events!')
      return
    }

    setLoading(true)
    setStatus(`Injecting disruption event '${eventType}'…`)

    let payload: Record<string, unknown> = {}
    if (eventType === 'truck_breakdown') {
      const truckId = selectedTruck || scenario.trucks[0]?.id
      payload = { truck_id: truckId }
    } else if (eventType === 'traffic_change') {
      const edge = scenario.edges[0]
      payload = { edge: [edge.from_node, edge.to_node], new_multiplier: trafficMultiplier }
    } else if (eventType === 'new_container') {
      payload = {
        id: `C_DYN_${Date.now().toString().slice(-4)}`,
        origin_node: scenario.icd_node_id,
        destination_node: scenario.nodes[scenario.nodes.length - 1].id,
        weight_kg: newWeight,
        priority: 3,
        earliest_time_min: 0,
        latest_time_min: 240,
        status: 'pending',
      }
    } else if (eventType === 'priority_change') {
      payload = { container_id: scenario.containers[0].id, new_priority: 3 }
    } else if (eventType === 'deadline_change') {
      payload = { container_id: scenario.containers[0].id, new_latest_time_min: 90 }
    }

    try {
      const event: EventPayload = {
        type: eventType,
        timestamp_min: 30,
        payload,
      }
      const res = await injectEvent(scenario.id, event)
      setEventResult(res)
      setSolution('qpso', res.after)

      // refresh map network
      const net = await getNetwork(scenario.id, 'qpso')
      setNetwork(net)

      setStatus(`Event processed! Affected containers: ${res.affected_container_ids.join(', ') || 'None'}`)
    } catch (e: any) {
      setStatus(`Event failed: ${e?.response?.data?.detail || e.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="panel-section">
      <div className="panel-title">Dynamic Event Injection</div>

      <div style={{ marginBottom: 10 }}>
        <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
          Disruption Type
        </label>
        <select
          className="select"
          value={eventType}
          onChange={e => setEventType(e.target.value as any)}
        >
          <option value="truck_breakdown">🚛 Truck Breakdown</option>
          <option value="traffic_change">🚥 Traffic Congestion</option>
          <option value="new_container">📦 New Urgent Container</option>
          <option value="priority_change">⚡ Priority Escalation</option>
          <option value="deadline_change">⏰ Deadline Tightened</option>
        </select>
      </div>

      {eventType === 'truck_breakdown' && scenario && (
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
            Select Breakdown Truck
          </label>
          <select
            className="select"
            value={selectedTruck}
            onChange={e => setSelectedTruck(e.target.value)}
          >
            {scenario.trucks.map(t => (
              <option key={t.id} value={t.id}>
                {t.id} ({t.capacity_kg}kg capacity)
              </option>
            ))}
          </select>
        </div>
      )}

      {eventType === 'traffic_change' && (
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
            Congestion Multiplier ({trafficMultiplier}x)
          </label>
          <input
            type="range"
            min="1.5"
            max="5.0"
            step="0.5"
            value={trafficMultiplier}
            onChange={e => setTrafficMultiplier(Number(e.target.value))}
            style={{ width: '100%' }}
          />
        </div>
      )}

      <button
        className="btn btn-danger btn-full"
        onClick={handleInject}
        disabled={!scenario || loading}
      >
        {loading ? <><span className="spinner" /> Re-optimizing…</> : '💥 Inject Event & Re-optimize'}
      </button>

      {/* Incremental vs Full Re-plan Callout */}
      {eventResult && (
        <div className="runtime-callout">
          <div className="title">⚡ Incremental vs Full Re-Plan Proof</div>
          <div className="runtime-vs">
            <div>
              <div className="runtime-val fast">{eventResult.runtime_ms_incremental.toFixed(1)} ms</div>
              <div className="runtime-label">Warm-Start QPSO</div>
            </div>
            <div className="runtime-sep">vs</div>
            <div>
              <div className="runtime-val slow">{eventResult.runtime_ms_full_replan.toFixed(1)} ms</div>
              <div className="runtime-label">Full Scratch Re-Plan</div>
            </div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
            Speedup factor: <strong className="pri-1">
              {(eventResult.runtime_ms_full_replan / Math.max(0.1, eventResult.runtime_ms_incremental)).toFixed(1)}x faster
            </strong> (Affected containers: {eventResult.affected_container_ids.length})
          </div>
        </div>
      )}
    </div>
  )
}
