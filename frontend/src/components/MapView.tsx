import { useEffect } from 'react'
import { MapContainer, TileLayer, Polyline, CircleMarker, Popup, Tooltip, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { useApp } from '../AppContext'
import { getNetwork } from '../api'

function MapRecenter({ center }: { center: [number, number] }) {
  const map = useMap()
  useEffect(() => {
    map.setView(center, map.getZoom())
  }, [center, map])
  return null
}

export default function MapView() {
  const { scenario, network, setNetwork, activeMethod } = useApp()

  useEffect(() => {
    if (scenario && !network) {
      const method = activeMethod === 'all' ? 'qpso' : activeMethod
      getNetwork(scenario.id, method).then(setNetwork).catch(console.error)
    }
  }, [scenario, activeMethod, network, setNetwork])

  // Center on ICD or default Tughlakabad ICD
  const icdNode = scenario?.nodes.find(n => n.kind === 'icd') || scenario?.nodes[0]
  const center: [number, number] = icdNode ? [icdNode.lat, icdNode.lon] : [28.5010, 77.2822]

  return (
    <div className="map-area" style={{ height: '100%', width: '100%' }}>
      <MapContainer
        center={center}
        zoom={12}
        style={{ height: '100%', width: '100%' }}
        zoomControl={true}
      >
        <MapRecenter center={center} />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        />

        {/* Render ICD location */}
        {icdNode && (
          <CircleMarker
            center={[icdNode.lat, icdNode.lon]}
            radius={10}
            pathOptions={{ fillColor: '#6366f1', fillOpacity: 0.9, color: '#ffffff', weight: 3 }}
          >
            <Popup>
              <div style={{ color: '#000', fontFamily: 'sans-serif' }}>
                <strong>Tughlakabad ICD (Origin)</strong><br />
                Node ID: {icdNode.id}<br />
                Coordinates: {icdNode.lat.toFixed(4)}, {icdNode.lon.toFixed(4)}
              </div>
            </Popup>
            <Tooltip permanent direction="top" offset={[0, -10]}>
              <span style={{ fontFamily: 'monospace', fontWeight: 'bold' }}>ICD DEPOT</span>
            </Tooltip>
          </CircleMarker>
        )}

        {/* Render Destination container markers */}
        {scenario?.containers.map(container => {
          const destNode = scenario.nodes.find(n => n.id === container.destination_node)
          if (!destNode) return null

          const color = container.priority === 3 ? '#f87171' : container.priority === 2 ? '#fbbf24' : '#60a5fa'

          return (
            <CircleMarker
              key={container.id}
              center={[destNode.lat, destNode.lon]}
              radius={6}
              pathOptions={{ fillColor: color, fillOpacity: 0.85, color: '#000000', weight: 1 }}
            >
              <Popup>
                <div style={{ color: '#000', fontFamily: 'sans-serif' }}>
                  <strong>Container {container.id}</strong><br />
                  Dest Node: {container.destination_node}<br />
                  Weight: {container.weight_kg} kg<br />
                  Priority: P{container.priority}<br />
                  Time Window: [{container.earliest_time_min}m, {container.latest_time_min}m]
                </div>
              </Popup>
            </CircleMarker>
          )
        })}

        {/* Render Truck Route Polylines */}
        {network?.routes.map(route => (
          <Polyline
            key={route.truck_id}
            positions={route.polyline}
            pathOptions={{
              color: route.color,
              weight: 4,
              opacity: 0.85,
              lineCap: 'round',
              lineJoin: 'round',
            }}
          >
            <Popup>
              <div style={{ color: '#000', fontFamily: 'sans-serif' }}>
                <strong>Truck Route: {route.truck_id}</strong>
              </div>
            </Popup>
          </Polyline>
        ))}
      </MapContainer>

      {/* Map Legend */}
      <div style={{
        position: 'absolute',
        top: 14,
        right: 14,
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: '10px 14px',
        zIndex: 1000,
        fontSize: 11,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          Legend
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#6366f1', border: '2px solid #fff', display: 'inline-block' }} />
          <span>ICD Origin Hub</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#f87171', display: 'inline-block' }} />
          <span>P3 Urgent Container</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#fbbf24', display: 'inline-block' }} />
          <span>P2 Medium Container</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#60a5fa', display: 'inline-block' }} />
          <span>P1 Standard Container</span>
        </div>
      </div>
    </div>
  )
}
