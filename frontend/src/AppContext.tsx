import { createContext, useContext, useState, type ReactNode } from 'react'
import type { Scenario, Solution, NetworkResponse, EventResponse } from './api'

interface AppState {
  scenario: Scenario | null
  setScenario: (s: Scenario | null) => void
  solutions: Record<string, Solution>   // method → Solution
  setSolution: (method: string, sol: Solution) => void
  network: NetworkResponse | null
  setNetwork: (n: NetworkResponse | null) => void
  activeMethod: string
  setActiveMethod: (m: string) => void
  eventResult: EventResponse | null
  setEventResult: (r: EventResponse | null) => void
  status: string
  setStatus: (s: string) => void
}

const AppContext = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [solutions, setSolutions] = useState<Record<string, Solution>>({})
  const [network, setNetwork] = useState<NetworkResponse | null>(null)
  const [activeMethod, setActiveMethod] = useState('qpso')
  const [eventResult, setEventResult] = useState<EventResponse | null>(null)
  const [status, setStatus] = useState('Ready')

  const setSolution = (method: string, sol: Solution) =>
    setSolutions(prev => ({ ...prev, [method]: sol }))

  return (
    <AppContext.Provider value={{
      scenario, setScenario,
      solutions, setSolution,
      network, setNetwork,
      activeMethod, setActiveMethod,
      eventResult, setEventResult,
      status, setStatus,
    }}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be inside AppProvider')
  return ctx
}
