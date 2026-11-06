import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import type { Axis1HexagonResult, Axis2ClusterSummary, Axis3HexagonResult } from '../types'

// Distinct colours for up to 10 K-Means segments
const SEGMENT_COLOURS = [
  '#22c55e', // S0 — green
  '#3b82f6', // S1 — blue
  '#f59e0b', // S2 — amber
  '#ec4899', // S3 — pink
  '#a78bfa', // S4 — purple
  '#06b6d4', // S5 — cyan
  '#f97316', // S6 — orange
  '#84cc16', // S7 — lime
  '#e11d48', // S8 — rose
  '#14b8a6', // S9 — teal
]

function segmentColour(segmentId: number): string {
  return SEGMENT_COLOURS[segmentId % SEGMENT_COLOURS.length]
}

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
  axis3VisibleSegments?: Set<number>
  height?: string
}

// Brazil center
const BRAZIL_CENTER: [number, number] = [-14.235, -51.925]
const BRAZIL_ZOOM = 4

export default function HexMap({ axis1Results, axis2Clusters, axis3Results, axis3VisibleSegments, height = '360px' }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null)

  return (
    <div ref={wrapperRef} style={{ height, minHeight: height === '100%' ? 0 : height, isolation: 'isolate' }} className="rounded border border-ind-border overflow-hidden flex flex-col">
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
                <div className="font-bold text-red-600">⚠ Manutenção Necessária</div>
                <div className="text-gray-500 text-[11px] mb-1">Infraestrutura degradada detectada</div>
                <div>H3: {h.h3_id}</div>
                <div>Score anomalia: {h.anomaly_score.toFixed(3)}</div>
                <div>LOF: {h.lof_score.toFixed(3)}</div>
                {h.cloudflare_outage_overlap === 1 && (
                  <div className="text-orange-500 font-semibold">⚠ Confirmado: queda Cloudflare</div>
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
                <div className="font-bold text-blue-600">💡 Oportunidade de Expansão</div>
                <div className="text-gray-500 text-[11px]">Cluster {c.cluster_id}{c.place_name ? ` — ${c.place_name}` : ''}</div>
                <div className="mb-1" />
                <div>Tamanho: {c.cluster_size} hex</div>
                {c.avg_d_down != null && <div>Vel↓: {c.avg_d_down.toFixed(1)} Mbps</div>}
                {c.tam_estimate != null && (
                  <div>TAM: R$ {c.tam_estimate.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</div>
                )}
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* Axis 3 — market segments (colour per segment_id, filtered by visibleSegments) */}
        {axis3Results?.filter((h) => !axis3VisibleSegments || axis3VisibleSegments.has(h.segment_id)).map((h) => {
          const col = segmentColour(h.segment_id)
          return (
            <CircleMarker
              key={h.h3_id}
              center={[h.lat_centroid, h.lon_centroid]}
              radius={4}
              pathOptions={{ color: col, fillColor: col, fillOpacity: 0.65, weight: 1 }}
            >
              <Popup>
                <div className="text-xs font-mono">
                  <div className="font-bold" style={{ color: col }}>Segmento S{h.segment_id}</div>
                  <div className="text-gray-500 text-[11px] mb-1">{h.segment_name}</div>
                  <div>H3: {h.h3_id}</div>
                  {h.centroid_distance != null && <div>Dist. centróide: {h.centroid_distance.toFixed(3)}</div>}
                </div>
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 px-3 py-2 bg-ind-surface border-t border-ind-border text-xs text-ind-muted shrink-0">
        {axis1Results && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-red-500 shrink-0" />
            <span><span className="text-ind-text font-medium">Manutenção Necessária</span> — infraestrutura degradada</span>
          </span>
        )}
        {axis2Clusters && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full bg-blue-500 shrink-0" />
            <span><span className="text-ind-text font-medium">Oportunidade de Expansão</span> — zona de alta demanda</span>
          </span>
        )}
        {axis3Results && (() => {
          // Build a deduplicated list of segments from the results
          const seen = new Map<number, string>()
          axis3Results.forEach((h) => { if (!seen.has(h.segment_id)) seen.set(h.segment_id, h.segment_name) })
          return Array.from(seen.entries()).sort((a, b) => a[0] - b[0]).map(([id, name]) => (
            <span key={id} className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: segmentColour(id) }} />
              <span><span className="text-ind-text font-medium">S{id}</span> — {name}</span>
            </span>
          ))
        })()}
      </div>
    </div>
  )
}
