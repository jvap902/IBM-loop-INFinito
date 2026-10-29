"""Agent Chat route — ``POST /v1/agent/chat``.

Allows the user to ask questions about an existing analysis run in natural
language.  The full ``report_json`` from the run is injected as context so
the LLM can answer questions about clusters, hexagons, TAM, segments, etc.

Requires ``X-API-Key`` header (same as all other ``/v1/*`` endpoints).

Stub behaviour
--------------
When ``LLM_PROVIDER=stub`` (or no LLM is configured), the endpoint returns
an informative message explaining that a real LLM provider must be configured
for chat functionality, rather than raising an error.
"""
from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Annotated, Optional

from api.auth import require_api_key
from api.schemas import SourceItem

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent Chat"])

# ── Schemas ────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: Annotated[str, Field(description="'user' or 'assistant'")]
    content: Annotated[str, Field(description="Message text.")]


class AgentChatRequest(BaseModel):
    """Request body for ``POST /v1/agent/chat``."""

    question: Annotated[str, Field(
        description="The user's question about the analysis results.",
        min_length=1,
        max_length=2000,
    )]
    report_context: Annotated[dict, Field(
        description=(
            "The full or summarised report_json from the last agent run. "
            "Should include summary, investment_hypotheses, axis summaries, "
            "and interpretations. Trimmed to avoid token limits."
        ),
    )]
    history: Annotated[Optional[list[ChatMessage]], Field(
        default=None,
        description="Previous messages in this chat session for multi-turn context.",
    )] = None


class AgentChatResponse(BaseModel):
    """Response body for ``POST /v1/agent/chat``."""

    answer: Annotated[str, Field(description="The agent's answer in Portuguese.")]
    is_stub: Annotated[bool, Field(
        description="True when no real LLM is configured — answer is a guidance message.",
    )] = False
    sources: Annotated[list[SourceItem], Field(
        description="Context sections that were injected into the LLM prompt for this answer.",
        default_factory=list,
    )]


# ── System prompt ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Você é um analista especialista em infraestrutura de telecomunicações do Brasil.
O usuário acabou de executar uma análise de rede e quer fazer perguntas sobre os resultados.

Contexto disponível: resultados dos três eixos analíticos (detecção de anomalias de \
infraestrutura, clustering de oportunidades de expansão e segmentação de mercado), \
hipóteses de investimento com TAM estimado, e sumários de cada pipeline de ML.

Regras:
- Responda SEMPRE em português do Brasil.
- Seja direto, quantitativo e orientado a decisão.
- Se a pergunta puder ser respondida com dados do contexto, cite os números exatos.
- Se a informação não estiver no contexto, diga claramente que não está disponível \
  nos dados do run atual.
- NUNCA invente dados que não estejam no contexto.
- NUNCA mencione dados pessoais de assinantes (conformidade LGPD).
- Máximo 4 parágrafos por resposta.
"""

_STUB_ANSWER = (
    "O chat com o agente requer um provedor LLM real configurado no servidor. "
    "Atualmente o sistema está rodando com o provedor 'stub' (sem LLM).\n\n"
    "Para habilitar o chat, adicione uma das opções abaixo no arquivo `.env` do backend:\n\n"
    "- Google Gemini (grátis): `LLM_PROVIDER=gemini` + `GEMINI_API_KEY=AIza...`\n"
    "  → Obtenha a chave em https://aistudio.google.com/app/apikey\n\n"
    "- OpenAI: `LLM_PROVIDER=openai` + `OPENAI_API_KEY=sk-...`\n\n"
    "- IBM watsonx.ai: `LLM_PROVIDER=watsonx` + `WATSONX_API_KEY` + `WATSONX_PROJECT_ID`\n\n"
    "Após configurar, reinicie o backend com `.\\start-backend.ps1`."
)


# ── Helper: build context string from report_json ─────────────────────────

def _build_context(report: dict) -> str:
    """Extract and format the most relevant fields from report_json for the LLM context."""
    region = report.get("region_scope", "desconhecida")
    axes = ", ".join(report.get("axes_executed", []))
    summary = report.get("summary", {})

    lines = [
        f"REGIÃO ANALISADA: {region}",
        f"EIXOS EXECUTADOS: {axes}",
        "",
        "=== RESUMO GERAL ===",
        f"- Hexágonos com anomalias críticas: {summary.get('n_critical_hexagons', 0)}",
        f"- Clusters de expansão: {summary.get('n_expansion_clusters', 0)}",
        f"- Segmentos de mercado: {summary.get('n_market_segments', 0)}",
        f"- Hipóteses de investimento: {summary.get('n_investment_hypotheses', 0)}",
        f"- TAM total estimado: R$ {summary.get('total_tam_brl', 0):,.2f}",
        f"- CAPEX proxy (15% TAM): R$ {summary.get('capex_proxy_brl', 0):,.2f}",
        f"- Clusters P1 (emergência): {summary.get('p1_clusters', 0)}",
        f"- Clusters P2 (urgente): {summary.get('p2_clusters', 0)}",
    ]

    # Axis 1
    a1 = report.get("axis1_summary") or {}
    if a1:
        lines += [
            "",
            "=== EIXO 1 — INFRAESTRUTURA (IsolationForest + LOF) ===",
            f"- Hexágonos analisados: {a1.get('total_hexagons_scored', 0):,}",
            f"- Hexágonos críticos: {a1.get('n_critical', 0)} ({(a1.get('anomaly_rate', 0)*100):.1f}%)",
            f"- Duração: {a1.get('duration_seconds', 0):.1f}s",
        ]

    # Axis 2
    a2 = report.get("axis2_summary") or {}
    if a2:
        lines += [
            "",
            "=== EIXO 2 — EXPANSÃO (UMAP + HDBSCAN) ===",
            f"- Total processado: {a2.get('total_hexagons_processed', 0):,}",
            f"- Clusters identificados: {a2.get('n_clusters', 0)}",
            f"- Taxa de ruído: {(a2.get('noise_rate', 0)*100):.1f}%",
        ]
        clusters = a2.get("clusters", [])[:8]
        for c in clusters:
            if not c.get("is_noise"):
                lines.append(
                    f"  · Cluster {c['cluster_id']}: {c['cluster_size']} hex, "
                    f"vel={c.get('avg_d_down') or 0:.1f} Mbps, "
                    f"dom/hex={c.get('avg_n_dom') or 0:.0f}, "
                    f"HHI={c.get('avg_HHI') or 0:.0f}, "
                    f"TAM=R${c.get('tam_estimate') or 0:,.0f}"
                )

    # Axis 3
    a3 = report.get("axis3_summary") or {}
    if a3:
        lines += [
            "",
            "=== EIXO 3 — SEGMENTAÇÃO (K-Means++) ===",
            f"- Segmentos: {a3.get('n_segments', 0)}",
            f"- Silhouette global: {a3.get('silhouette_score_global') or 'N/D'}",
        ]
        for seg in a3.get("segment_profiles", []):
            lines.append(
                f"  · Segmento {seg['segment_id']} '{seg['segment_name']}': "
                f"{seg['hexagon_count']} hex ({seg['hexagon_fraction']*100:.1f}%)"
            )

    # Top hypotheses
    hyps = report.get("investment_hypotheses", [])[:10]
    if hyps:
        lines += ["", "=== TOP 10 HIPÓTESES DE INVESTIMENTO ==="]
        for h in hyps:
            lines.append(
                f"  · Cluster {h['cluster_id']} [{h['priority_class']}]: "
                f"TAM=R${h['tam_estimate_brl']:,.0f}, "
                f"vel={h['avg_d_down_mbps']:.1f}Mbps, "
                f"dom/hex={h['avg_n_dom']:.0f}, HHI={h['avg_hhi']:.0f} — "
                f"{h.get('rationale', '')}"
            )

    # Interpretations (condensed)
    interp = report.get("interpretations") or {}
    exec_summ = interp.get("executive_summary", "")
    if exec_summ:
        lines += ["", "=== SUMÁRIO EXECUTIVO DO AGENTE ===", exec_summ[:800]]

    # SHAP / Z-score feature explanations
    explanations = report.get("explanations") or {}

    exp1 = explanations.get("axis1") or {}
    if exp1.get("status") == "ok":
        top = (exp1.get("top_features") or [])[:3]
        if top:
            lines += [
                "",
                "=== SHAP — EIXO 1 (features que mais contribuíram para anomalias) ===",
                f"Método: {exp1.get('method', 'N/D')} | Hexágonos explicados: {exp1.get('n_explained', 'N/D')}",
            ]
            for f in top:
                lines.append(f"  · {f['feature']}: {f['shap_value']:.4f}")

    exp2 = explanations.get("axis2") or {}
    if exp2.get("status") == "ok":
        clusters_exp = exp2.get("clusters") or {}
        if clusters_exp:
            lines += [
                "",
                "=== SHAP — EIXO 2 (Z-score por cluster de expansão) ===",
                f"Método: {exp2.get('method', 'N/D')}",
            ]
            for cluster_key, cdata in list(clusters_exp.items())[:3]:
                top_f = (cdata.get("top_features") or [])[:3]
                lines.append(f"  Cluster {cluster_key}:")
                for f in top_f:
                    lines.append(
                        f"    · {f['feature']}: z={f['z_score']:.4f} "
                        f"(cluster={f.get('cluster_mean', 0):.2f}, global={f.get('global_mean', 0):.2f})"
                    )

    exp3 = explanations.get("axis3") or {}
    if exp3.get("status") == "ok":
        segments_exp = exp3.get("segments") or {}
        if segments_exp:
            lines += [
                "",
                "=== SHAP — EIXO 3 (features que mais contribuíram para segmentação) ===",
                f"Método: {exp3.get('method', 'N/D')} | Amostras explicadas: {exp3.get('n_explained', 'N/D')}",
            ]
            for seg_key, sdata in segments_exp.items():
                top_f = (sdata.get("top_features") or [])[:3]
                lines.append(f"  Segmento {seg_key}:")
                for f in top_f:
                    lines.append(f"    · {f['feature']}: {f['shap_value']:.4f}")

    return "\n".join(lines)


# ── Helper: build sources list from report_json ───────────────────────────

def _build_sources(report: dict) -> list[SourceItem]:
    """Return one SourceItem per non-empty report section used in the LLM context."""
    items: list[SourceItem] = []

    region = report.get("region_scope")
    axes = report.get("axes_executed") or []
    if region:
        items.append(SourceItem(
            section="Região & Escopo",
            values=[f"Região: {region}", f"Eixos: {', '.join(axes)}"],
        ))

    summary = report.get("summary") or {}
    if summary:
        items.append(SourceItem(
            section="Resumo Geral",
            values=[
                f"{summary.get('n_critical_hexagons', 0)} hexágonos críticos",
                f"{summary.get('n_expansion_clusters', 0)} clusters de expansão",
                f"TAM total R$ {summary.get('total_tam_brl', 0):,.0f}",
            ],
        ))

    a1 = report.get("axis1_summary") or {}
    if a1:
        items.append(SourceItem(
            section="Eixo 1 — Infraestrutura",
            values=[
                f"{a1.get('n_critical', 0)} críticos",
                f"taxa anomalia {(a1.get('anomaly_rate', 0)*100):.1f}%",
                f"{a1.get('total_hexagons_scored', 0):,} hexágonos",
            ],
        ))

    a2 = report.get("axis2_summary") or {}
    if a2:
        clusters_non_noise = [c for c in (a2.get("clusters") or []) if not c.get("is_noise")]
        items.append(SourceItem(
            section="Eixo 2 — Expansão",
            values=[
                f"{a2.get('n_clusters', 0)} clusters",
                f"ruído {(a2.get('noise_rate', 0)*100):.1f}%",
                f"{len(clusters_non_noise)} clusters reais",
            ],
        ))

    a3 = report.get("axis3_summary") or {}
    if a3:
        segs = a3.get("segment_profiles") or []
        items.append(SourceItem(
            section="Eixo 3 — Segmentação",
            values=[
                f"{a3.get('n_segments', 0)} segmentos",
                f"silhouette {a3.get('silhouette_score_global') or 'N/D'}",
                f"{len(segs)} perfis",
            ],
        ))

    hyps = report.get("investment_hypotheses") or []
    if hyps:
        p1 = sum(1 for h in hyps if h.get("priority_class") == "P1")
        items.append(SourceItem(
            section="Hipóteses de Investimento",
            values=[
                f"{len(hyps)} hipóteses",
                f"{p1} P1 (emergência)",
                f"TAM maior: R$ {max((h.get('tam_estimate_brl', 0) for h in hyps), default=0):,.0f}",
            ],
        ))

    interp = report.get("interpretations") or {}
    if interp.get("executive_summary"):
        items.append(SourceItem(
            section="Sumário Executivo",
            values=["interpretação do agente incluída"],
        ))

    explanations = report.get("explanations") or {}
    shap_axes: list[str] = []
    if (explanations.get("axis1") or {}).get("status") == "ok":
        shap_axes.append("Eixo 1")
    if (explanations.get("axis2") or {}).get("status") == "ok":
        shap_axes.append("Eixo 2")
    if (explanations.get("axis3") or {}).get("status") == "ok":
        shap_axes.append("Eixo 3")
    if shap_axes:
        items.append(SourceItem(
            section="SHAP / Features Explicativas",
            values=[f"disponível para: {', '.join(shap_axes)}"],
        ))

    return items


# ── Route ──────────────────────────────────────────────────────────────────

@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    summary="Chat with the agent about analysis results",
    description=(
        "Ask a natural-language question about the most recent analysis run. "
        "The full report context is provided in the request body so the LLM "
        "can answer questions about clusters, hexagons, TAM, segments, etc.\n\n"
        "Requires a real LLM provider (``LLM_PROVIDER=gemini``, ``openai`` or ``watsonx``). "
        "Returns a guidance message when ``LLM_PROVIDER=stub``."
    ),
)
async def agent_chat(
    request: AgentChatRequest,
    _api_key: str = Depends(require_api_key),
) -> AgentChatResponse:
    from agent.llm_provider import get_llm_provider, StubProvider

    # Use the provider from the request context if present (injected by the frontend),
    # otherwise fall back to the server-level env var.
    ctx_provider = (request.report_context or {}).get("llm_provider_hint", "")
    llm_provider_name = str(ctx_provider) if ctx_provider else os.getenv("LLM_PROVIDER", "stub")
    llm = get_llm_provider(llm_provider_name)

    if isinstance(llm, StubProvider):
        sources = _build_sources(request.report_context)
        return AgentChatResponse(answer=_STUB_ANSWER, is_stub=True, sources=sources)

    # Build context from the provided report
    try:
        context_str = _build_context(request.report_context)
    except Exception as exc:
        logger.warning("[chat] Failed to build context: %s", exc)
        context_str = json.dumps(request.report_context, ensure_ascii=False, default=str)[:3000]

    # Build the full prompt including conversation history
    history = request.history or []
    history_text = ""
    if history:
        history_text = "\n\n=== HISTÓRICO DA CONVERSA ===\n"
        for msg in history[-6:]:  # last 6 messages for context window management
            role_label = "Usuário" if msg.role == "user" else "Agente"
            history_text += f"\n{role_label}: {msg.content}"
        history_text += "\n"

    prompt = (
        f"=== DADOS DA ANÁLISE ===\n{context_str}\n"
        f"{history_text}"
        f"\n=== PERGUNTA DO USUÁRIO ===\n{request.question}"
    )

    try:
        answer = llm.chat(
            prompt,
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=800,
        )
    except Exception as exc:
        logger.exception("[chat] LLM call failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM call failed: {exc}",
        ) from exc

    sources = _build_sources(request.report_context)
    return AgentChatResponse(answer=answer, is_stub=False, sources=sources)
