# Plan: LLM-Driven Report Generation with User Prompt Guidance

## Overview

**Goal:** When a user clicks "Novo Relatório" and enters a prompt (with a real LLM provider), the generated report must reflect genuine LLM analysis guided by that prompt — producing new insights, explanations, and suggestions — instead of merely tabulating the dashboard data.

**Root Cause:** `report_writer()` in `agent/graph.py` never calls `generate_interpretations()` from `agent/interpreter.py`. All seven report sections are built from raw tabulated data using string templates. The `user_prompt` from the state is only injected as a static blockquote in the executive summary; it is never forwarded to any LLM call.

**Approach:** Thread the `user_prompt` into `generate_interpretations()` so it modifies the LLM system prompt and per-section user prompts. Then call `generate_interpretations()` inside `report_writer()` and use its rich interpretations to replace the raw-data-only content of the narrative sections.

**Scope:** Two files change — `agent/interpreter.py` and `agent/graph.py`. No frontend, no API schema, no database changes required.

---

## Sub-Tasks

---

### Sub-Task 1 — Thread `user_prompt` through `generate_interpretations()`

**Intent:** The `generate_interpretations()` function currently ignores the user's free-text instruction. This sub-task adds a `user_prompt` parameter to that function and injects it into the LLM system prompt and into each per-section prompt so the LLM produces focused analysis on what the user asked.

**Expected Outcomes:**
- `generate_interpretations()` accepts an optional `user_prompt: str = ""` parameter.
- When `user_prompt` is non-empty, the system prompt gains a "Contexto adicional do analista" clause appended to `_SYSTEM_PROMPT`.
- Each `_llm_axis()` call and `_llm_executive_summary()` call receives the augmented system prompt.
- The `_llm_executive_summary()` prompt text explicitly references the user's instruction.
- Stub path: stub interpretations from `interpreter.py` (richer deterministic text) are used in place of the current raw-table-only sections — stub mode also benefits from better narrative output.

**Todo List:**
- [ ] Add `user_prompt: str = ""` parameter to `generate_interpretations()` in `agent/interpreter.py`.
- [ ] Inside `generate_interpretations()`, build a `system_prompt` local variable: start from `_SYSTEM_PROMPT` and, if `user_prompt` is non-empty, append `\n\nContexto adicional do analista: {user_prompt}`.
- [ ] Pass that `system_prompt` into every `_llm_axis()` and `_llm_executive_summary()` call.
- [ ] Update `_llm_axis()` signature to accept `system_prompt: str = _SYSTEM_PROMPT` and forward it to `llm.chat()`.
- [ ] Update `_llm_executive_summary()` signature likewise; also prepend the user instruction to the LLM prompt text so the model is explicitly told what aspect to focus on.

**Relevant Context:**
- `agent/interpreter.py` — `generate_interpretations()` at line 343, `_llm_axis()` at line 281, `_llm_executive_summary()` at line 298, `_SYSTEM_PROMPT` at line 26.

**Status:** [x] done

---

### Sub-Task 2 — Call `generate_interpretations()` inside `report_writer()`

**Intent:** Wire the existing interpretation engine into the report assembly step. Currently `report_writer()` builds narrative sections entirely from raw numbers. This sub-task replaces the narrative content of the key sections with rich LLM-generated interpretations when a real provider is selected, while keeping the raw data tables as supporting evidence.

**Expected Outcomes:**
- `report_writer()` calls `generate_interpretations()` using `llm_provider` from the environment (already set by `generate_report()` in `api/routes/report_gen.py`) and the `user_prompt` from state.
- Sections 1 (Executive Summary), 2 (Axis 1), 3 (Axis 2), and 4 (Axis 3) each prepend the LLM interpretation paragraph(s) before their existing raw-data table.
- Section 7 (Next Actions) is LLM-generated (or stub-generated), using the user prompt to shape the recommended actions (e.g. a CAPEX-focused prompt yields CAPEX-focused recommendations).
- When `llm_provider="stub"`, sections 1–4 and 7 use richer stub interpretations from `interpreter.py` instead of raw-table-only text — improving stub output quality as well.
- The `user_prompt` blockquote currently in the executive summary header is retained for auditability.

**Todo List:**
- [ ] Import `generate_interpretations` from `agent.interpreter` at the top of `agent/graph.py` (avoid circular import — check existing imports first).
- [ ] Inside `report_writer()`, read `llm_provider` from `os.environ.get("LLM_PROVIDER", "stub")`.
- [ ] Call `generate_interpretations(region, a1, a2, a3, hypotheses, llm_provider=llm_provider, user_prompt=user_prompt)` and capture the result dict as `interpretations`.
- [ ] In Section 1 (exec_summary), prepend `interpretations["executive_summary"]` after the `prompt_instruction` blockquote and before the bullet-list metrics.
- [ ] In Section 2 (axis1_body), prepend `interpretations["axis1_interpretation"]` followed by a blank line before the data table.
- [ ] In Section 3 (axis2_body), prepend `interpretations["axis2_interpretation"]` before the data table.
- [ ] In Section 4 (axis3_body), prepend `interpretations["axis3_interpretation"]` before the data table.
- [ ] Add a `"next_actions"` key to `generate_interpretations()` output: for LLM providers, call `llm.chat()` with a prompt that summarises the top priorities and includes the user instruction, asking for concrete next steps; for stub, derive from existing P1/P2 logic in `interpreter.py`.
- [ ] In Section 7 (actions_body), replace the hardcoded rule-based text with `interpretations["next_actions"]`.

**Relevant Context:**
- `agent/graph.py` — `report_writer()` from line 485, section assembly from line 531 onward.
- `api/routes/report_gen.py` — sets `os.environ["LLM_PROVIDER"]` at line 69 before calling `report_writer`.
- `agent/interpreter.py` — `generate_interpretations()` at line 343 (public API, already tested and fallback-safe).

**Status:** [x] done

---

### Sub-Task 3 — Validate end-to-end with an existing run

**Intent:** Confirm the change works correctly for all three provider scenarios: `stub` (no regression), a real LLM provider (insights appear and reflect the user prompt), and a failing LLM (fallback to stub text gracefully).

**Expected Outcomes:**
- Running `POST /agent/report` with `llm_provider="stub"` produces a report with the same structure but with richer stub narrative text in sections 1–4 and 7.
- Running with a real provider produces a report whose Section 1 and Sections 2-4 contain narrative paragraphs that reference concepts from the `user_prompt`.
- A `user_prompt` such as "Foque nos clusters P1 e destaque o risco de CAPEX" causes the executive summary and relevant axis sections to explicitly mention P1 clusters and CAPEX risk.
- If the LLM call raises an exception, the report still completes using stub text (fallback already implemented in `_llm_axis()`).

**Todo List:**
- [ ] Run the existing test suite (if any) to confirm no regressions — `pytest` or equivalent.
- [ ] Manually call `POST /agent/report` with a persisted `run_id`, `llm_provider="stub"`, and a `user_prompt` — inspect the returned markdown to confirm structure is intact.
- [ ] If a real LLM credential is available, repeat with `llm_provider="watsonx"` or `"openai"` and verify the narrative sections contain user-prompt-driven content.

**Relevant Context:**
- `runs/` directory — contains persisted run JSON files usable as `run_id` sources.
- `api/routes/report_gen.py` — the endpoint under test.
- `reports/` directory — output files will appear here for manual inspection.

**Status:** [x] done
