"""Telecom AI Platform — Operational Agent (Sub-Task 6).

LangGraph-based orchestration agent that coordinates the three analytical
axes (Axis 1: Maintenance, Axis 2: Expansion, Axis 3: Churn/Promotions),
cross-interprets their outputs, and generates prescriptive infrastructure
investment reports.

Architecture
------------
StateGraph nodes:
    gap_detector      → identify stale / unanalysed regions
    tool_selector     → LLM-guided axis selection
    axis1_runner      → HTTP call to POST /v1/tools/axis1/run
    axis2_runner      → HTTP call to POST /v1/tools/axis2/run
    axis3_runner      → HTTP call to POST /v1/tools/axis3/run
    result_interpreter → cross-axis synthesis + TAM estimation
    report_writer     → structured Markdown + JSON report

Public surface
--------------
    from agent.graph import build_graph
    from agent.state import AgentState
    from agent.run   import run_agent
"""
