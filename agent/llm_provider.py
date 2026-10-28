"""LLM Abstraction Layer — swappable LLM provider for the Operational Agent.

Supported providers
-------------------
watsonx   IBM watsonx.ai (default)  — ibm-watsonx-ai SDK
openai    OpenAI GPT-4o             — openai SDK
gemini    Google Gemini             — google-genai SDK (v2)

Provider selection
------------------
Set the environment variable ``LLM_PROVIDER`` to one of ``"watsonx"``,
``"openai"``, or ``"gemini"``.  All providers fall back gracefully to a
``StubProvider`` when their SDK is not installed or credentials are absent,
so the rest of the agent graph can still run in environments without LLM
access (e.g. CI).

Usage
-----
    from agent.llm_provider import get_llm_provider

    llm = get_llm_provider()
    response = llm.chat("Summarise the following cluster data: …")
    tool_result = llm.tool_call(
        system_prompt="You are a telecom infra analyst.",
        user_message="Which axes should I run for region X?",
        tools=[{"name": "select_axes", "description": "…", "parameters": {…}}],
    )

Interface contract
------------------
``chat(prompt, *, system_prompt, temperature, max_tokens) → str``
    Plain text completion / chat response.

``tool_call(user_message, *, system_prompt, tools, temperature) → dict``
    Returns the first tool call chosen by the model as a dict with keys
    ``name`` and ``arguments`` (dict).  If the model returns plain text
    instead of a structured call the dict has ``name="text"`` and
    ``arguments={"text": <response>}``.
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Base protocol ──────────────────────────────────────────────────────────


class BaseLLMProvider(ABC):
    """Abstract interface every LLM provider must implement."""

    @abstractmethod
    def chat(
        self,
        prompt: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """Return a plain-text completion for *prompt*."""

    @abstractmethod
    def tool_call(
        self,
        user_message: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        tools: list[dict[str, Any]],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Request a structured tool call and return ``{name, arguments}``."""


# ── IBM watsonx.ai provider ────────────────────────────────────────────────


class WatsonxProvider(BaseLLMProvider):
    """IBM watsonx.ai provider using the ``ibm-watsonx-ai`` SDK.

    Required environment variables
    --------------------------------
    WATSONX_API_KEY      IBM Cloud API key.
    WATSONX_PROJECT_ID   watsonx.ai project UUID.
    WATSONX_URL          Service endpoint (default: us-south.ml.cloud.ibm.com).
    WATSONX_MODEL_ID     Model deployment ID (default: ibm/granite-13b-chat-v2).
    """

    _DEFAULT_MODEL = "ibm/granite-13b-chat-v2"

    def __init__(self) -> None:
        self._api_key = os.getenv("WATSONX_API_KEY", "")
        self._project_id = os.getenv("WATSONX_PROJECT_ID", "")
        self._url = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        self._model_id = os.getenv("WATSONX_MODEL_ID", self._DEFAULT_MODEL)
        self._client: Any = None

        if not self._api_key or not self._project_id:
            logger.warning(
                "[llm] WatsonxProvider: WATSONX_API_KEY or WATSONX_PROJECT_ID "
                "not set — provider will raise on first call."
            )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from ibm_watsonx_ai import APIClient, Credentials  # type: ignore
            from ibm_watsonx_ai.foundation_models import ModelInference  # type: ignore

            credentials = Credentials(url=self._url, api_key=self._api_key)
            self._client = ModelInference(
                model_id=self._model_id,
                credentials=credentials,
                project_id=self._project_id,
            )
            return self._client
        except ImportError as exc:
            raise ImportError(
                "ibm-watsonx-ai is required for WatsonxProvider. "
                "Install with: pip install ibm-watsonx-ai"
            ) from exc

    def chat(
        self,
        prompt: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        client = self._get_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        response = client.chat(
            messages=messages,
            params={"temperature": temperature, "max_new_tokens": max_tokens},
        )
        # ibm-watsonx-ai returns choices[0].message.content
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            return str(response)

    def tool_call(
        self,
        user_message: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        tools: list[dict[str, Any]],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Simulate tool-call by injecting tool specs into the prompt."""
        tools_desc = json.dumps(tools, indent=2)
        augmented_prompt = (
            f"Available tools:\n{tools_desc}\n\n"
            "Based on the context, respond ONLY with a JSON object of the form:\n"
            '{"name": "<tool_name>", "arguments": {<key: value>}}\n\n'
            f"User request: {user_message}"
        )
        raw = self.chat(
            augmented_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        return _parse_tool_response(raw, tools)


# ── OpenAI provider ────────────────────────────────────────────────────────


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT-4o provider using the official ``openai`` SDK.

    Required environment variables
    --------------------------------
    OPENAI_API_KEY    OpenAI API key.
    OPENAI_MODEL_ID   Model name (default: gpt-4o).
    """

    _DEFAULT_MODEL = "gpt-4o"

    def __init__(self) -> None:
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        self._model_id = os.getenv("OPENAI_MODEL_ID", self._DEFAULT_MODEL)
        self._client: Any = None

        if not self._api_key:
            logger.warning(
                "[llm] OpenAIProvider: OPENAI_API_KEY not set — "
                "provider will raise on first call."
            )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import openai  # type: ignore

            self._client = openai.OpenAI(api_key=self._api_key)
            return self._client
        except ImportError as exc:
            raise ImportError(
                "openai is required for OpenAIProvider. "
                "Install with: pip install openai"
            ) from exc

    def chat(
        self,
        prompt: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    def tool_call(
        self,
        user_message: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        tools: list[dict[str, Any]],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        client = self._get_client()
        # Convert to OpenAI function-calling format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]
        response = client.chat.completions.create(
            model=self._model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            tools=openai_tools,
            tool_choice="auto",
            temperature=temperature,
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {"raw": tc.function.arguments}
            return {"name": tc.function.name, "arguments": args}
        # No tool call — return plain text
        return {"name": "text", "arguments": {"text": msg.content or ""}}


# ── Google Gemini provider ─────────────────────────────────────────────────


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider — REST API via httpx (no SDK dependency).

    Calls the Gemini generateContent REST endpoint directly to avoid SDK-level
    hangs, thinking mode leakage, and version-compatibility issues.

    Required environment variables
    --------------------------------
    GEMINI_API_KEY    Google AI Studio API key.
    GEMINI_MODEL_ID   Model name (default: gemini-2.0-flash-lite).

    Get a free key at https://aistudio.google.com/app/apikey
    """

    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    _DEFAULT_MODEL = "gemini-3.5-flash"
    _TIMEOUT = 60.0

    def __init__(self) -> None:
        self._api_key = os.getenv("GEMINI_API_KEY", "")
        self._model_id = os.getenv("GEMINI_MODEL_ID", self._DEFAULT_MODEL)

        if not self._api_key:
            logger.warning(
                "[llm] GeminiProvider: GEMINI_API_KEY not set — "
                "provider will raise on first call."
            )

    def _post(self, prompt: str, system_prompt: str, temperature: float, max_tokens: int) -> str:
        """POST to Gemini generateContent REST endpoint and return the answer text."""
        import time
        import httpx  # already a project dependency

        url = f"{self._BASE_URL}/{self._model_id}:generateContent?key={self._api_key}"
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                # Disable thinking mode — avoids multi-second thinking delays and
                # "thought" token leakage corrupting the actual response text.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = httpx.post(url, json=payload, timeout=self._TIMEOUT)
                if resp.status_code in (429, 503) and attempt < 2:
                    wait = 4 * (attempt + 1)
                    logger.warning("[llm] Gemini HTTP %d attempt %d — retry in %ds", resp.status_code, attempt + 1, wait)
                    time.sleep(wait)
                    last_exc = Exception(f"HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ValueError(f"Gemini: no candidates — {data.get('promptFeedback')}")
                parts = candidates[0].get("content", {}).get("parts", [])
                # Skip thought parts (present in thinking models)
                texts = [p["text"] for p in parts if p.get("text") and not p.get("thought")]
                if not texts:
                    finish = candidates[0].get("finishReason", "UNKNOWN")
                    raise ValueError(f"Gemini: empty response parts (finishReason={finish})")
                return " ".join(texts).strip()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < 2:
                    logger.warning("[llm] Gemini network error attempt %d: %s", attempt + 1, exc)
                    time.sleep(2)
                    continue
                raise
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in (429, 503) and attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    def chat(
        self,
        prompt: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        return self._post(prompt, system_prompt, temperature, max_tokens)

    def tool_call(
        self,
        user_message: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        tools: list[dict[str, Any]],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Simulate tool-call by injecting tool specs into the prompt (JSON mode)."""
        tools_desc = json.dumps(tools, indent=2, ensure_ascii=False)
        augmented_prompt = (
            f"Available tools:\n{tools_desc}\n\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            '{"name": "<tool_name>", "arguments": {<key: value>}}\n\n'
            "Do not include any explanation or markdown fences.\n\n"
            f"User request: {user_message}"
        )
        raw = self.chat(
            augmented_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        return _parse_tool_response(raw, tools)


# ── Stub provider (for CI / no-credential environments) ───────────────────


class StubProvider(BaseLLMProvider):
    """Deterministic stub used when no real LLM credentials are configured.

    Returns predictable responses so the agent graph can complete end-to-end
    in tests without external API calls.
    """

    def chat(
        self,
        prompt: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        logger.info("[llm] StubProvider.chat called (no real LLM configured)")
        return (
            "STUB RESPONSE: LLM provider not configured. "
            "Set LLM_PROVIDER=watsonx or LLM_PROVIDER=openai with valid credentials."
        )

    def tool_call(
        self,
        user_message: str,
        *,
        system_prompt: str = "You are a helpful telecom infrastructure analyst.",
        tools: list[dict[str, Any]],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        logger.info("[llm] StubProvider.tool_call — returning all axes by default")
        # By default select all three axes so the graph can run fully
        tool_name = tools[0]["name"] if tools else "select_axes"
        return {
            "name": tool_name,
            "arguments": {"axes": ["axis1", "axis2", "axis3"], "rationale": "Stub: running all axes."},
        }


# ── Factory ────────────────────────────────────────────────────────────────


def get_llm_provider(provider: Optional[str] = None) -> BaseLLMProvider:
    """Return the configured LLM provider instance.

    Parameters
    ----------
    provider : Override for the ``LLM_PROVIDER`` environment variable.
               Accepts ``"watsonx"``, ``"openai"``, or ``"stub"``.
    """
    selected = (provider or os.getenv("LLM_PROVIDER", "stub")).lower().strip()
    logger.info("[llm] Using LLM provider: %s", selected)

    if selected == "watsonx":
        return WatsonxProvider()
    if selected == "openai":
        return OpenAIProvider()
    if selected == "gemini":
        return GeminiProvider()
    if selected == "stub":
        return StubProvider()

    logger.warning(
        "[llm] Unknown LLM_PROVIDER '%s' — falling back to StubProvider.", selected
    )
    return StubProvider()


# ── Internal helpers ───────────────────────────────────────────────────────


def _parse_tool_response(raw: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract a ``{name, arguments}`` dict from a raw LLM string.

    Tries JSON extraction first; falls back to returning the raw text.
    """
    # Try to find a JSON block in the response
    raw = raw.strip()
    # Strip markdown fences if present
    for fence in ("```json", "```"):
        if raw.startswith(fence):
            raw = raw[len(fence):]
        if raw.endswith("```"):
            raw = raw[:-3]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "name" in parsed:
            return {
                "name": str(parsed.get("name", "")),
                "arguments": parsed.get("arguments", parsed.get("args", {})),
            }
    except (json.JSONDecodeError, ValueError):
        pass

    # Last resort: return as plain text payload
    return {"name": "text", "arguments": {"text": raw}}
