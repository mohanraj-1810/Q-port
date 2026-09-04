/**
 * Q-PORT API client
 * All calls go through the Vite proxy → http://localhost:8000
 */
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export interface Node {
  id: string
  lat: number
  lon: number
  kind: 'icd' | 'destination' | 'waypoint'
}

export interface Edge {
  from_node: string
  to_node: string
  distance_km: number
  base_time_min: number
  traffic_multiplier: number
}

export interface Container {
  id: string
  origin_node: string
  destination_node: string
  weight_kg: number
  priority: 1 | 2 | 3
  earliest_time_min: number
  latest_time_min: number
  status: 'pending' | 'assigned' | 'delivered' | 'unassignable'
}

export interface Truck {
  id: string
  capacity_kg: number
  current_node: string
  available: boolean
  speed_kmph: number
}

export interface Assignment {
  truck_id: string
  container_sequence: string[]
}

export interface Solution {
  assignments: Assignment[]
  total_distance_km: number
  total_time_min: number
  total_waiting_min: number
  total_cost: number
  constraint_violations: number
  fitness: number
  method: 'qpso' | 'ortools' | 'ga'
  runtime_ms: number
}

export interface Scenario {
  id: string
  size: 'small' | 'medium' | 'large'
  seed: number
  nodes: Node[]
  edges: Edge[]
  containers: Container[]
  trucks: Truck[]
  icd_node_id: string
}

export interface NetworkResponse {
  nodes: Node[]
  edges: Edge[]
  routes: RoutePolyline[]
}

export interface RoutePolyline {
  truck_id: string
  color: string
  polyline: [number, number][]
}

export interface BenchmarkResult {
  scenario_id: string
  results: Solution[]
}

export interface EventPayload {
  type: 'traffic_change' | 'truck_breakdown' | 'new_container' | 'priority_change' | 'deadline_change'
  timestamp_min: number
  payload: Record<string, unknown>
}

export interface EventResponse {
  before: Solution
  after: Solution
  affected_container_ids: string[]
  runtime_ms_incremental: number
  runtime_ms_full_replan: number
}

// ─── API calls ──────────────────────────────────────────────────────────────

export const generateScenario = (size: string, seed: number) =>
  api.post<Scenario>('/scenario/generate', { size, seed }).then(r => r.data)

export const getScenario = (id: string) =>
  api.get<Scenario>(`/scenario/${id}`).then(r => r.data)

export const listScenarios = () =>
  api.get<{ scenario_ids: string[] }>('/scenarios').then(r => r.data.scenario_ids)

export const solveScenario = (scenario_id: string, method: string) =>
  api.post<Solution | Solution[]>('/solve', { scenario_id, method }).then(r => r.data)

export const getNetwork = (scenario_id: string, method = 'qpso') =>
  api.get<NetworkResponse>(`/scenario/${scenario_id}/network?method=${method}`).then(r => r.data)

export const benchmarkScenario = (scenario_id: string) =>
  api.get<BenchmarkResult>(`/benchmark/${scenario_id}`).then(r => r.data)

export const injectEvent = (scenario_id: string, event: EventPayload) =>
  api.post<EventResponse>('/event', { scenario_id, event }).then(r => r.data)
