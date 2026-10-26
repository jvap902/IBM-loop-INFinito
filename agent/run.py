"""CLI entry point for the Operational Agent — Sub-Task 6.

Usage
-----
    python -m agent.run --region BR-SP --axes axis1 axis2 axis3
    python -m agent.run --region 855198c7fffffff --force
    python -m agent.run --region all --axes axis2 axis3 --output-dir reports/

Arguments
---------
--region      Human-readable region label or H3 parent cell ID (res 5/6).
              Use "all" to analyse the full Gold Feature Store.
--axes        One or more of: axis1, axis2, axis3.  Defaults to all three.
--force       Skip freshness checks and re-run all axes unconditionally.
--output-dir  Directory to save the Markdown and JSON reports (default: reports/).
--api-base    Base URL of the Tool API (overrides TOOL_API_BASE_URL env var).
--api-key     API key for the Tool API (overrides TOOL_API_KEY env var).
--llm         LLM provider: watsonx | openai | stub (overrides LLM_PROVIDER env var).

Output
------
reports/{region}_{YYYY-MM-DD}.md    Prescriptive Markdown report.
reports/{region}_{YYYY-MM-DD}.json  Machine-readable JSON report.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# LangGraph and Typer are optional at import time so the rest of the project
# can be imported without these dependencies installed.
try:
    import typer  # type: ignore
except ImportError:
    print(
        "ERROR: typer is required to run the CLI. "
        "Install with: pip install typer",
        file=sys.stderr,
    )
    sys.exit(1)

from agent.graph import build_graph
from agent.state import AgentState
from agent.tool_registry import ToolRegistry, reset_registry

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

app = typer.Typer(
    name="telecom-agent",
    help="Telecom AI Operational Agent — generates prescriptive infrastructure reports.",
    add_completion=False,
)


@app.command()
def run_agent(
    region: str = typer.Option(
        "all",
        "--region",
        help="Region label or H3 parent cell ID. Use 'all' for the full dataset.",
    ),
    axes: Optional[List[str]] = typer.Option(
        None,
        "--axes",
        help="Axes to execute: axis1, axis2, axis3. Defaults to all three.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip freshness checks and re-run all selected axes.",
    ),
    output_dir: Path = typer.Option(
        Path("reports"),
        "--output-dir",
        help="Directory where Markdown and JSON reports are saved.",
    ),
    api_base: Optional[str] = typer.Option(
        None,
        "--api-base",
        help="Base URL of the Tool API (overrides TOOL_API_BASE_URL).",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="X-API-Key for the Tool API (overrides TOOL_API_KEY).",
    ),
    llm: Optional[str] = typer.Option(
        None,
        "--llm",
        help="LLM provider: watsonx | openai | stub (overrides LLM_PROVIDER).",
    ),
) -> None:
    """Run the Operational Agent and save the prescriptive infrastructure report."""

    # ── Environment overrides ──────────────────────────────────────────────
    if api_base:
        os.environ["TOOL_API_BASE_URL"] = api_base
    if api_key:
        os.environ["TOOL_API_KEY"] = api_key
    if llm:
        os.environ["LLM_PROVIDER"] = llm

    # ── Normalise axes ────────────────────────────────────────────────────
    valid_axes = {"axis1", "axis2", "axis3"}
    if axes:
        requested_axes = [a.lower().strip() for a in axes if a.lower().strip() in valid_axes]
        invalid = [a for a in axes if a.lower().strip() not in valid_axes]
        if invalid:
            typer.echo(f"⚠️  Unknown axes ignored: {invalid}", err=True)
    else:
        requested_axes = ["axis1", "axis2", "axis3"]

    if not requested_axes:
        typer.echo("❌ No valid axes specified. Use --axes axis1 axis2 axis3", err=True)
        raise typer.Exit(code=1)

    # ── Prepare tool registry ─────────────────────────────────────────────
    reset_registry()
    registry = ToolRegistry(
        base_url=os.getenv("TOOL_API_BASE_URL", "http://localhost:8000"),
        api_key=os.getenv("TOOL_API_KEY", ""),
    )

    # ── Build initial state ───────────────────────────────────────────────
    run_id = str(uuid.uuid4())
    initial_state: AgentState = {
        "region_scope": region,
        "axes_requested": requested_axes,
        "force": force,
        "run_id": run_id,
        "audit_trail": [],
        "errors": [],
    }

    typer.echo(
        f"\n🚀 Telecom Operational Agent\n"
        f"   Region  : {region}\n"
        f"   Axes    : {requested_axes}\n"
        f"   Force   : {force}\n"
        f"   Run ID  : {run_id}\n"
        f"   API Base: {os.getenv('TOOL_API_BASE_URL', 'http://localhost:8000')}\n"
        f"   LLM     : {os.getenv('LLM_PROVIDER', 'stub')}\n"
    )

    # ── Execute graph ─────────────────────────────────────────────────────
    typer.echo("⏳ Running agent graph…")
    try:
        compiled_graph = build_graph(registry=registry)
        final_state: AgentState = compiled_graph.invoke(initial_state)
    except Exception as exc:
        typer.echo(f"❌ Agent execution failed: {exc}", err=True)
        logger.exception("Agent graph execution failed")
        raise typer.Exit(code=2) from exc

    # ── Save reports ──────────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Sanitise region for use in filename
    safe_region = region.replace("/", "-").replace(" ", "_").replace(":", "-")[:50]
    base_name = f"{safe_region}_{date_str}"

    md_path = output_dir / f"{base_name}.md"
    json_path = output_dir / f"{base_name}.json"

    report_markdown = final_state.get("report_markdown", "")
    report_json = final_state.get("report_json", {})
    errors = final_state.get("errors", [])

    md_path.write_text(report_markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(report_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    typer.echo(f"\n✅ Report saved:")
    typer.echo(f"   📄 {md_path}")
    typer.echo(f"   🗂  {json_path}")

    # ── Audit summary ─────────────────────────────────────────────────────
    audit_trail = final_state.get("audit_trail", [])
    typer.echo(f"\n📋 Audit trail: {len(audit_trail)} events recorded (run_id={run_id})")

    if errors:
        typer.echo(f"\n⚠️  {len(errors)} error(s) during execution:")
        for err in errors:
            typer.echo(f"   • [{err.get('node', '?')}] {err.get('error', 'unknown')}")

    # ── Print executive summary ───────────────────────────────────────────
    summary = report_json.get("summary", {})
    typer.echo(
        f"\n📊 Summary:\n"
        f"   Critical hexagons (Axis 1) : {summary.get('n_critical_hexagons', 0)}\n"
        f"   Expansion clusters (Axis 2): {summary.get('n_expansion_clusters', 0)}\n"
        f"   Market segments  (Axis 3)  : {summary.get('n_market_segments', 0)}\n"
        f"   Investment hypotheses      : {summary.get('n_investment_hypotheses', 0)}\n"
        f"   Total TAM estimate         : R$ {summary.get('total_tam_brl', 0.0):,.2f}\n"
    )


def main() -> None:
    """Module entry point when invoked as ``python -m agent.run``."""
    app()


if __name__ == "__main__":
    main()
