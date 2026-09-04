import { AppProvider, useApp } from './AppContext'
import ScenarioPanel from './components/ScenarioPanel'
import SolvePanel from './components/SolvePanel'
import EventPanel from './components/EventPanel'
import BenchmarkTable from './components/BenchmarkTable'
import MapView from './components/MapView'

function MainLayout() {
  const { status } = useApp()

  return (
    <div className="app-shell">
      {/* Top Navigation Bar */}
      <header className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 6,
            background: 'linear-gradient(135deg, #6366f1, #3b82f6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 700, fontSize: 14, color: '#fff'
          }}>
            Q
          </div>
          <div>
            <h1 style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.02em', margin: 0, lineHeight: 1.2 }}>
              Q-PORT <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--accent)', marginLeft: 6 }}>PROTOTYPE</span>
            </h1>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0 }}>
              Quantum-Inspired Dynamic Container Routing & Fleet Optimization (SIH26137)
            </p>
          </div>
        </div>
      </header>

      {/* Control Sidebar */}
      <aside className="sidebar">
        <ScenarioPanel />
        <SolvePanel />
        <EventPanel />
        <BenchmarkTable />

        <div className="status-bar">
          Status: {status}
        </div>
      </aside>

      {/* Main Interactive Map View */}
      <main className="map-area">
        <MapView />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <MainLayout />
    </AppProvider>
  )
}
