"""Business-language interpretation engine for the Telecom AI Platform.

Generates human-readable, actionable explanations for each analytical axis
result and for cross-axis investment hypotheses.

Two modes
---------
Stub (no LLM)
    Deterministic rule-based engine that inspects the actual data values and
    produces contextualised, quantitatively grounded explanations in
    Portuguese.  The output reads like an analyst wrote it — not a template.

LLM (watsonx / openai)
    The same data is fed to the LLM as a structured prompt.  The LLM adds
    sector knowledge, risk context, and narrative quality on top of the
    rule-based baseline.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Você é um analista sênior de infraestrutura de telecomunicações no Brasil. "
    "Sua função é transformar dados técnicos de análise de rede em insights acionáveis "
    "para gestores e diretores de operações — sem jargões estatísticos desnecessários. "
    "Seja direto, quantitativo e orientado a decisão. Máximo 4 parágrafos por seção. "
    "NUNCA invente dados que não estejam no contexto fornecido. "
    "NUNCA mencione dados pessoais de assinantes (conformidade LGPD)."
)

# ── Stub: deterministic rule-based interpretations ─────────────────────────

def _stub_axis1(a1: dict[str, Any]) -> str:
    n_critical = a1.get("n_critical", 0)
    total = a1.get("total_hexagons_scored", 0)
    rate = a1.get("anomaly_rate", 0.0) * 100
    results = a1.get("results", [])
    top = [r for r in results if r.get("is_critical")][:3]
    duration = a1.get("duration_seconds", 0)

    # Severity classification
    if rate > 8:
        severity = "CRÍTICO"
        action = "Intervenção imediata recomendada nas regiões sinalizadas."
    elif rate > 4:
        severity = "ELEVADO"
        action = "Priorize inspeção de campo nas próximas 2 semanas."
    elif rate > 1:
        severity = "MODERADO"
        action = "Monitoramento reforçado; planejar manutenção preventiva."
    else:
        severity = "BAIXO"
        action = "Infraestrutura estável. Manter ciclos regulares de monitoramento."

    cloudflare_count = sum(1 for r in top if r.get("cloudflare_outage_overlap") == 1)
    cf_note = (
        f" {cloudflare_count} desses hexágonos coincidem com eventos de outage registrados "
        "pelo Cloudflare Radar, confirmando degradação real de conectividade."
        if cloudflare_count > 0 else ""
    )

    top_scores = [f"{r['h3_id']} (score {r['anomaly_score']:.2f})" for r in top[:3]]
    top_str = ", ".join(top_scores) if top_scores else "N/D"

    lof_high = sum(1 for r in results if r.get("lof_score", 0) > 0.7 and r.get("is_critical"))

    return (
        f"**Situação geral: {severity}**\n\n"
        f"O modelo IsolationForest + LOF analisou {total:,} hexágonos H3 e identificou "
        f"**{n_critical} ({rate:.1f}%)** com padrões anômalos de desempenho — "
        f"combinando latência elevada, baixa velocidade de download e volume anormal de reclamações. "
        f"{action}\n\n"
        f"Os hexágonos mais críticos são: {top_str}.{cf_note}\n\n"
        f"{lof_high} hexágonos apresentam score LOF acima de 0.70, indicando isolamento "
        f"estatístico severo — provável degradação localizada de equipamento ou congestionamento "
        f"de backhaul. Análise concluída em {duration:.1f}s."
    )


def _stub_axis2(a2: dict[str, Any]) -> str:
    n_clusters = a2.get("n_clusters", 0)
    total = a2.get("total_hexagons_processed", 0)
    noise_rate = a2.get("noise_rate", 0.0) * 100
    clusters = [c for c in a2.get("clusters", []) if not c.get("is_noise")]
    duration = a2.get("duration_seconds", 0)

    if not clusters:
        return "_Eixo 2 não gerou clusters nesta análise._"

    # Top cluster by estimated TAM
    top_c = max(clusters, key=lambda c: c.get("tam_estimate") or 0)
    top_tam = top_c.get("tam_estimate") or 0
    top_dom = top_c.get("avg_n_dom") or 0
    top_speed = top_c.get("avg_d_down") or 0
    top_hhi = top_c.get("avg_HHI") or 0
    top_size = top_c.get("cluster_size", 0)

    # Low-speed opportunity clusters (below 30 Mbps)
    low_speed = [c for c in clusters if (c.get("avg_d_down") or 999) < 30]
    high_dom = sorted(clusters, key=lambda c: c.get("avg_n_dom") or 0, reverse=True)[:2]

    market_conc = "alta concentração (baixa concorrência)" if top_hhi > 5000 else "mercado competitivo"

    high_dom_ids = ", ".join(f"C{c['cluster_id']}" for c in high_dom)
    return (
        f"O algoritmo UMAP + HDBSCAN agrupou {total:,} hexágonos em "
        f"**{n_clusters} clusters de oportunidade** ({noise_rate:.1f}% classificados como ruído). "
        f"Cada cluster representa uma zona geográfica contígua com perfil de demanda similar, "
        f"identificando onde há escala para expansão de rede com retorno previsível.\n\n"
        f"**Maior oportunidade:** Cluster {top_c.get('cluster_id')} — "
        f"{top_size} hexágonos, média de {top_dom:.0f} domicílios/hex, "
        f"velocidade atual de {top_speed:.1f} Mbps, {market_conc}. "
        f"TAM estimado de **R$ {top_tam:,.0f}/ano**.\n\n"
        f"{len(low_speed)} cluster(s) com velocidade média abaixo de 30 Mbps representam "
        f"populações com conectividade precária — prioridade máxima para programas de "
        f"universalização e financiamentos FUST/FUNTTEL.\n\n"
        f"Os 2 clusters com maior densidade domiciliar ({high_dom_ids}) "
        f"têm potencial de absorção de planos residenciais em larga escala. "
        f"Análise concluída em {duration:.1f}s."
    )


def _stub_axis3(a3: dict[str, Any]) -> str:
    n_segments = a3.get("n_segments", 0)
    total = a3.get("total_hexagons_segmented", 0)
    sil = a3.get("silhouette_score_global")
    profiles = a3.get("segment_profiles", [])
    duration = a3.get("duration_seconds", 0)

    if not profiles:
        return "_Eixo 3 não gerou segmentos nesta análise._"

    sil_str = f"{sil:.2f}" if sil is not None else "N/D"
    sil_quality = (
        "separação estatística boa" if (sil or 0) > 0.35
        else "separação moderada — segmentos com sobreposição parcial de perfil"
        if (sil or 0) > 0.15
        else "sobreposição significativa — interpretar segmentos com cautela"
    )

    premium = [p for p in profiles if "premium" in p.get("segment_name", "").lower()]
    vulneravel = [p for p in profiles if "vulnerab" in p.get("segment_name", "").lower()]
    essencial = [p for p in profiles if "essencial" in p.get("segment_name", "").lower()]

    premium_frac = sum(p["hexagon_fraction"] for p in premium) * 100
    vuln_frac = sum(p["hexagon_fraction"] for p in vulneravel) * 100
    ess_frac = sum(p["hexagon_fraction"] for p in essencial) * 100

    biggest = max(profiles, key=lambda p: p["hexagon_count"])

    return (
        f"O K-Means++ segmentou {total:,} hexágonos em **{n_segments} perfis de mercado** "
        f"(Silhouette Score: {sil_str} — {sil_quality}). "
        f"Esta segmentação orienta campanhas promocionais diferenciadas por perfil socioeconômico "
        f"e de conectividade.\n\n"
        + (
            f"**Segmento Premium ({premium_frac:.1f}% dos hexágonos):** "
            f"regiões com renda elevada e boa conectividade atual. "
            f"Alvo para planos de alta velocidade, TV e pacotes convergentes.\n\n"
            if premium else ""
        )
        + (
            f"**Conectividade Essencial ({ess_frac:.1f}%):** "
            f"maior segmento em extensão territorial. "
            f"Prioridade para planos de entrada, banda larga acessível e programas sociais. "
            f"Sensível a preço — promoções com fidelização tendem a funcionar melhor que descontos únicos.\n\n"
            if essencial else ""
        )
        + (
            f"**Alta Vulnerabilidade Competitiva ({vuln_frac:.1f}%):** "
            f"zonas com múltiplos provedores e alta taxa de churn histórico. "
            f"Requer estratégia de retenção ativa — SLA diferenciado, suporte prioritário ou "
            f"benefícios de fidelidade.\n\n"
            if vulneravel else ""
        )
        + f"O segmento dominante em tamanho é '{biggest['segment_name']}' "
        f"com {biggest['hexagon_count']:,} hexágonos ({biggest['hexagon_fraction']*100:.1f}%). "
        f"Análise concluída em {duration:.1f}s."
    )


def _stub_hypothesis(h: dict[str, Any]) -> str:
    cid = h.get("cluster_id")
    priority = h.get("priority_class", "P3_STANDARD_EXPANSION")
    tam = h.get("tam_estimate_brl", 0)
    n_dom = h.get("avg_n_dom", 0)
    speed = h.get("avg_d_down_mbps", 0)
    hhi = h.get("avg_hhi", 0)
    size = h.get("cluster_size_hexagons", 0)
    arpu = h.get("arpu_assumed_brl", 89.9)
    pen = h.get("penetration_rate_assumed", 0.35)

    market = (
        "mercado muito concentrado (baixíssima concorrência — janela estratégica)" if hhi > 7000
        else "alta concentração (oportunidade com pouca disputa)" if hhi > 5000
        else "concentração moderada" if hhi > 3000
        else "mercado competitivo (risco de guerra de preços)"
    )

    speed_note = (
        f"A velocidade média atual de {speed:.1f} Mbps está **abaixo de 25 Mbps**, "
        "enquadrando-se como área subatendida pelos critérios da ANATEL. "
        "Isso abre margem para projetos com incentivos regulatórios." if speed < 25
        else f"A velocidade média de {speed:.1f} Mbps indica infraestrutura razoável — "
        "a estratégia deve focar em aumento de capacidade e upsell, não em cobertura básica."
    )

    unserved_hh = int(n_dom * size * (1 - pen))
    monthly_rev = unserved_hh * arpu

    priority_label = {
        "P1_CRITICAL_EXPANSION": "P1 — Intervencao Imediata",
        "P2_EXPANSION_CHURN_RISK": "P2 — Acao Urgente",
        "P3_STANDARD_EXPANSION": "P3 — Planejamento de Medio Prazo",
    }.get(priority, priority)

    return (
        f"**{priority_label}**\n\n"
        f"Cluster {cid} concentra {size} hexágonos com média de {n_dom:.0f} domicílios cada. "
        f"Estimativa de **{unserved_hh:,} domicílios não atendidos** (assumindo {pen*100:.0f}% "
        f"de penetração atual), com potencial de receita mensal de "
        f"**R$ {monthly_rev:,.0f}/mês** ao ARPU de R$ {arpu:.2f}.\n\n"
        f"{speed_note}\n\n"
        f"Concentração de mercado: {market} (HHI={hhi:.0f}). "
        f"TAM anualizado estimado: **R$ {tam:,.0f}**. "
        f"CAPEX proxy (15% TAM): R$ {tam*0.15:,.0f}."
    )


def _stub_executive_summary(
    a1: dict[str, Any],
    a2: dict[str, Any],
    a3: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    region: str,
) -> str:
    n_critical = a1.get("n_critical", 0) if a1 else 0
    rate = (a1.get("anomaly_rate", 0.0) * 100) if a1 else 0
    n_clusters = a2.get("n_clusters", 0) if a2 else 0
    n_segments = a3.get("n_segments", 0) if a3 else 0
    total_tam = sum(h.get("tam_estimate_brl", 0) for h in hypotheses)
    p1 = sum(1 for h in hypotheses if "P1" in h.get("priority_class", ""))
    top_h = hypotheses[0] if hypotheses else None

    infra_status = (
        "requer atenção imediata" if rate > 5
        else "monitoramento reforçado recomendado" if rate > 2
        else "está estável"
    )

    top_note = (
        f" A maior oportunidade individual é o Cluster {top_h['cluster_id']} "
        f"com TAM de R$ {top_h['tam_estimate_brl']:,.0f}/ano."
        if top_h else ""
    )

    p1_note = (
        f" **{p1} cluster(s) classificados como P1 (emergência)** — "
        "baixa velocidade somada a alta densidade domiciliar exige ação imediata."
        if p1 > 0 else ""
    )

    return (
        f"A análise da região **{region}** revela uma infraestrutura que {infra_status}: "
        f"{n_critical} hexágonos ({rate:.1f}% do total) apresentam anomalias que comprometem "
        f"a qualidade de serviço percebida pelos assinantes.\n\n"
        f"Paralelamente, o algoritmo de clustering identificou **{n_clusters} zonas de expansão** "
        f"com perfil de demanda estruturado, e {n_segments} segmentos de mercado distintos "
        f"foram mapeados para orientar campanhas diferenciadas.\n\n"
        f"O mercado endereçável total estimado é de **R$ {total_tam:,.0f}/ano** — "
        f"representando domicílios ainda não atendidos com planos de banda larga fixa.{top_note}{p1_note}"
    )


# ── LLM: rich interpretations ──────────────────────────────────────────────

def _llm_axis(llm: Any, axis_name: str, data: dict[str, Any], stub_fallback: str) -> str:
    """Generate LLM interpretation for a single axis result."""
    import json as _json
    prompt = (
        f"Analise os seguintes resultados do {axis_name} da plataforma Telecom AI e "
        f"escreva uma interpretação em linguagem de negócio, orientada a decisão, "
        f"em português do Brasil. Foque em impacto operacional e comercial.\n\n"
        f"Dados:\n{_json.dumps(data, ensure_ascii=False, default=str, indent=2)}\n\n"
        f"Use no máximo 4 parágrafos. Seja específico com os números dos dados."
    )
    try:
        return llm.chat(prompt, system_prompt=_SYSTEM_PROMPT, temperature=0.3, max_tokens=600)
    except Exception as exc:
        logger.warning("[interpreter] LLM call failed for %s: %s — using stub", axis_name, exc)
        return stub_fallback


def _llm_executive_summary(
    llm: Any,
    a1: dict[str, Any],
    a2: dict[str, Any],
    a3: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    region: str,
    stub_fallback: str,
) -> str:
    import json as _json
    context = {
        "region": region,
        "axis1_summary": {
            "n_critical": a1.get("n_critical"),
            "anomaly_rate": a1.get("anomaly_rate"),
            "total_hexagons": a1.get("total_hexagons_scored"),
        } if a1 else None,
        "axis2_summary": {
            "n_clusters": a2.get("n_clusters"),
            "noise_rate": a2.get("noise_rate"),
        } if a2 else None,
        "axis3_summary": {
            "n_segments": a3.get("n_segments"),
            "silhouette": a3.get("silhouette_score_global"),
        } if a3 else None,
        "total_tam_brl": sum(h.get("tam_estimate_brl", 0) for h in hypotheses),
        "n_hypotheses": len(hypotheses),
        "p1_count": sum(1 for h in hypotheses if "P1" in h.get("priority_class", "")),
    }
    prompt = (
        f"Com base nos seguintes dados de análise de rede para a região {region}, "
        f"escreva um sumário executivo em português do Brasil — 3 parágrafos, "
        f"orientado a C-level, conectando os três eixos de análise (infraestrutura, "
        f"expansão e segmentação) em uma narrativa coesa com recomendação de prioridade.\n\n"
        f"Dados:\n{_json.dumps(context, ensure_ascii=False, indent=2)}"
    )
    try:
        return llm.chat(prompt, system_prompt=_SYSTEM_PROMPT, temperature=0.4, max_tokens=500)
    except Exception as exc:
        logger.warning("[interpreter] LLM executive summary failed: %s — using stub", exc)
        return stub_fallback


# ── Public API ─────────────────────────────────────────────────────────────

def generate_interpretations(
    region: str,
    a1: dict[str, Any],
    a2: dict[str, Any],
    a3: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    llm_provider: str = "stub",
) -> dict[str, Any]:
    """Generate business-language interpretations for all analysis results.

    Returns a dict with keys:
        executive_summary   — top-level narrative for C-level consumption
        axis1_interpretation — business interpretation of anomaly detection results
        axis2_interpretation — business interpretation of expansion cluster results
        axis3_interpretation — business interpretation of market segmentation results
        hypothesis_interpretations — list of per-hypothesis rich rationales
                                     (same order as hypotheses input)
    """
    from agent.llm_provider import StubProvider, get_llm_provider

    use_llm = llm_provider.lower() not in ("stub", "")
    llm = get_llm_provider(llm_provider) if use_llm else None
    is_stub = isinstance(llm, StubProvider) if llm else True

    logger.info(
        "[interpreter] Generating interpretations — provider=%s, use_llm=%s",
        llm_provider, not is_stub,
    )

    # ── Stub interpretations (always computed as fallback) ──────────────────
    stub_exec = _stub_executive_summary(a1, a2, a3, hypotheses, region)
    stub_a1 = _stub_axis1(a1) if a1 else "_Eixo 1 não executado._"
    stub_a2 = _stub_axis2(a2) if a2 else "_Eixo 2 não executado._"
    stub_a3 = _stub_axis3(a3) if a3 else "_Eixo 3 não executado._"
    stub_hyps = [_stub_hypothesis(h) for h in hypotheses]

    if is_stub:
        return {
            "executive_summary": stub_exec,
            "axis1_interpretation": stub_a1,
            "axis2_interpretation": stub_a2,
            "axis3_interpretation": stub_a3,
            "hypothesis_interpretations": stub_hyps,
        }

    # ── LLM interpretations ─────────────────────────────────────────────────
    return {
        "executive_summary": _llm_executive_summary(
            llm, a1, a2, a3, hypotheses, region, stub_exec
        ),
        "axis1_interpretation": _llm_axis(llm, "Eixo 1 (Detecção de Anomalias)", a1, stub_a1) if a1 else stub_a1,
        "axis2_interpretation": _llm_axis(llm, "Eixo 2 (Clustering de Expansão)", a2, stub_a2) if a2 else stub_a2,
        "axis3_interpretation": _llm_axis(llm, "Eixo 3 (Segmentação de Mercado)", a3, stub_a3) if a3 else stub_a3,
        "hypothesis_interpretations": stub_hyps,  # per-hypothesis LLM calls would be too slow; use deterministic
    }
