/**
 * Centralised mapping of ML model feature names to business-readable labels.
 * Single source of truth — any component that needs to display a feature name
 * must import from here instead of using raw backend keys.
 *
 * X_HI_COLUMNS (10 core features) + aggregated metrics used in Eixo 2 clusters.
 */

export const FEATURE_LABELS: Record<string, string> = {
  // Core model features (X_HI_COLUMNS)
  d_down: "Velocidade de Download (Mbps)",
  d_up: "Velocidade de Upload (Mbps)",
  lat: "Latência (ms)",
  vol_test: "Volume de Testes (testes/dispositivo)",
  n_dom: "Domicílios",
  n_com: "Estabelecimentos Comerciais",
  ren_med: "Renda Média (R$)",
  n_erb: "Torres de Celular",
  HHI: "Concentração de Mercado (HHI)",
  vol_reclam: "Reclamações (por 1k acessos)",

  // Aggregated metrics used in Eixo 2 cluster explanations
  avg_d_down: "Vel. Download Média (Mbps)",
  avg_n_dom: "Domicílios por Hexágono",
  avg_HHI: "Concentração de Mercado Média (HHI)",
}

/**
 * Returns the business-readable label for a model feature name.
 * Falls back to the raw feature key when no mapping is found.
 *
 * @param feature - Raw feature name from the backend (e.g. "lat", "d_down")
 * @returns Human-readable label with unit in parentheses, or the raw name as fallback
 */
export function getFeatureLabel(feature: string): string {
  return FEATURE_LABELS[feature] ?? feature
}
