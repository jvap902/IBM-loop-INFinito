import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import type { Axis1HexagonResult, Axis2ClusterSummary, Axis3HexagonResult } from '../types'

// Forces Leaflet to recalculate tile layout after mount inside flex/grid containers
function InvalidateSizeOnMount() {
  const map = useMap()
  useEffect(() => {
    // Small delay ensures the container has its final CSS dimensions
    const t = setTimeout(() => map.invalidateSize(), 100)
    return () => clearTimeout(t)
  }, [map])
  return null
}

interface Props {
  axis1Results?: Axis1HexagonResult[]
  axis2Clusters?: Axis2ClusterSummary[]
  axis3Results?: Axis3HexagonResult[]
  height?: string
}

// Brazil center
const BRAZIL_CENTER: [number, number] = [-14.235, -51.925]
const BRAZIL_ZOOM = 4

export default function HexMap({ axis1Results, axis2Clusters, axis3Results, height = '360px' }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null)

  return (
    <div ref={wrapperRef} style={{ height, minHeight: height === '100%' ? 0 : height }} className="rounded border border-ind-border overflow-hidden flex flex-col">
      <div style={{ flex: 1, minHeight: 0 }}>
      <MapContainer
        center={BRAZIL_CENTER}
        zoom={BRAZIL_ZOOM}
        style={{ height: '100%', width: '100%' }}
        scrollWheelZoom={true}
      >
        <InvalidateSizeOnMount />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Axis 1 — critical hexagons (red) */}
        {axis1Results?.filter((h) => h.is_critical === 1).map((h) => (
          <CircleMarker
            key={h.h3_id}
            center={[h.lat_centroid, h.lon_centroid]}
            radius={5}
            pathOptions={{ color: '#ef4444', fillColor: '#ef4444', fillOpacity: 0.7, weight: 1 }}
          >
            <Popup>
              <div className="text-xs font-mono">
                <div className="font-bold text-red-600">Crítico — Eixo 1</div>
                <div>H3: {h.h3_id}</div>
                <div>Score anomalia: {h.anomaly_score.toFixed(3)}</div>
                <div>LOF: {h.lof_score.toFixed(3)}</div>
                {h.cloudflare_outage_overlap === 1 && (
                  <div className="text-orange-500 font-semibold">⚠ Overlap Cloudflare</div>
                )}
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* Axis 2 — expansion clusters (blue) */}
        {axis2Clusters?.filter((c) => c.is_noise === 0).map((c) => (
          <CircleMarker
            key={`c-${c.cluster_id}`}
            center={[c.lat_centroid, c.lon_centroid]}
            radius={7}
            pathOptions={{ color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.6, weight: 1 }}
          >
            <Popup>
              <div className="text-xs font-mono">
                <div className="font-bold text-blue-600">Cluster {c.cluster_id} — Eixo 2</div>
                {c.place_name && <div className="text-blue-500 text-[11px] mb-1">{c.place_name}</div>}
                <div>Tamanho: {c.cluster_size} hex</div>
                {c.avg_d_down != null && <div>Vel↓: {c.avg_d_down.toFixed(1)} Mbps</div>}
                {c.tam_estimate != null && (
                  <div>TAM: R$ {c.tam_estimate.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</div>
                )}
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* Axis 3 — market segments (green gradient by segment_id) */}
        {axis3Results?.map((h) => (
          <CircleMarker
            key={h.h3_id}
            center={[h.lat_centroid, h.lon_centroid]}
            radius={4}
            pathOptions={{ color: '#22c55e', fillColor: '#22c55e', fillOpacity: 0.5, weight: 1 }}
          >
            <Popup>
              <div className="text-xs font-mono">
                <div className="font-bold text-green-600">Segmento {h.segment_id} — Eixo 3</div>
                <div>{h.segment_name}</div>
                <div>H3: {h.h3_id}</div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      </div>

      {/* Legend */}
      <div className="flex gap-4 px-3 py-2 bg-ind-surface border-t border-ind-border text-xs text-ind-muted shrink-0">
        {axis1Results && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-red-500" />
            Eixo 1 Crítico
          </span>
        )}
        {axis2Clusters && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-blue-500" />
            Eixo 2 Clusters
          </span>
        )}
        {axis3Results && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-green-500" />
            Eixo 3 Segmentos
          </span>
        )}
      </div>
    </div>
  )
}
