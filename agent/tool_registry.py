"""Tool Registry Abstraction — dynamic discovery and invocation of API tools.

The registry loads the tool catalogue from ``GET /v1/tools`` at startup
and exposes an ``invoke_tool`` method that the axis runner nodes use.
Using this layer instead of hard-coded URLs means the agent graph is
decoupled from the underlying framework: swapping LangGraph for CrewAI or
AutoGen only requires replacing the graph nodes, not touching this module.

Retry strategy
--------------
Up to ``MAX_RETRIES`` attempts with exponential back-off:
    attempt 1 → immediate
    attempt 2 → 1 s delay
    attempt 3 → 2 s delay

Timeout
-------
Connect: 10 s, Read: 120 s (ML pipelines can be slow on first run).

Environment variables
---------------------
TOOL_API_BASE_URL   Base URL of the FastAPI service (default: http://localhost:8000).
TOOL_API_KEY        API key sent in ``X-API-Key`` header.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MAX_RETRIES: int = 3
_BACKOFF_BASE: float = 1.0  # seconds; attempt n waits (n-1) * _BACKOFF_BASE

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 120.0

# ── Registry ───────────────────────────────────────────────────────────────


class ToolRegistry:
    """Dynamic tool registry that wraps the FastAPI ``/v1/tools`` catalogue.

    Usage
    -----
    Synchronous (within an existing asyncio loop use the async variant):

        registry = ToolRegistry()
        result = registry.invoke_tool_sync("axis1_run", {"contamination": 0.05})

    Asynchronous:

        registry = ToolRegistry()
        result = await registry.invoke_tool("axis1_run", {"contamination": 0.05})

    The ``catalogue`` property returns the raw list of ``ToolDefinition``
    dicts fetched from the API.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._base_url = (
            base_url or os.getenv("TOOL_API_BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        self._api_key = api_key or os.getenv("TOOL_API_KEY", "")
        self._catalogue: list[dict[str, Any]] = []
        self._catalogue_loaded: bool = False

    # ── Catalogue ──────────────────────────────────────────────────────────

    @property
    def catalogue(self) -> list[dict[str, Any]]:
        """Return the cached tool catalogue (may be empty if not loaded yet)."""
        return self._catalogue

    async def load_catalogue(self) -> list[dict[str, Any]]:
        """Fetch and cache the tool catalogue from ``GET /v1/tools``.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._catalogue_loaded:
            return self._catalogue

        url = f"{self._base_url}/v1/tools"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
        ) as client:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                    self._catalogue = data.get("tools", [])
                    self._catalogue_loaded = True
                    logger.info(
                        "[tool_registry] Loaded %d tools from %s",
                        len(self._catalogue), url,
                    )
                    return self._catalogue
                except Exception as exc:
                    if attempt < MAX_RETRIES:
                        wait = (attempt) * _BACKOFF_BASE
                        logger.warning(
                            "[tool_registry] catalogue load attempt %d/%d failed: %s — retrying in %.1fs",
                            attempt, MAX_RETRIES, exc, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "[tool_registry] Failed to load catalogue after %d attempts: %s",
                            MAX_RETRIES, exc,
                        )
                        self._catalogue = []
                        self._catalogue_loaded = True  # avoid infinite retry
        return self._catalogue

    def load_catalogue_sync(self) -> list[dict[str, Any]]:
        """Synchronous wrapper around :meth:`load_catalogue`."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already inside an event loop (e.g. Jupyter / FastAPI)
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self.load_catalogue())
                    return future.result()
            return loop.run_until_complete(self.load_catalogue())
        except RuntimeError:
            return asyncio.run(self.load_catalogue())

    # ── Tool lookup ────────────────────────────────────────────────────────

    def get_tool_definition(self, tool_id: str) -> Optional[dict[str, Any]]:
        """Return the catalogue entry for *tool_id*, or ``None`` if not found."""
        for tool in self._catalogue:
            if tool.get("tool_id") == tool_id:
                return tool
        return None

    # ── Invocation (async) ─────────────────────────────────────────────────

    async def invoke_tool(
        self,
        tool_id: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Invoke a tool by its catalogue ``tool_id`` and return the JSON response.

        Parameters
        ----------
        tool_id : Tool identifier as returned by ``GET /v1/tools``.
        params  : Request body dict; defaults to an empty dict.

        Returns
        -------
        Parsed JSON response dict from the tool endpoint.

        Raises
        ------
        RuntimeError
            If all retry attempts fail or the tool is not found in the catalogue.
        """
        if not self._catalogue_loaded:
            await self.load_catalogue()

        tool_def = self.get_tool_definition(tool_id)
        if tool_def is None:
            # Fallback: derive endpoint from tool_id convention
            endpoint = f"/v1/tools/{tool_id.replace('_', '/')}"
            method = "POST"
            logger.warning(
                "[tool_registry] tool_id '%s' not in catalogue; guessing endpoint %s",
                tool_id, endpoint,
            )
        else:
            endpoint = tool_def.get("endpoint", "")
            method = tool_def.get("method", "POST").upper()

        url = f"{self._base_url}{endpoint}"
        headers = {"X-API-Key": self._api_key} if self._api_key else {}
        payload = params or {}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
        ) as client:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    t0 = time.perf_counter()
                    if method == "GET":
                        resp = await client.get(url, headers=headers, params=payload)
                    else:
                        resp = await client.post(url, headers=headers, json=payload)

                    duration = round(time.perf_counter() - t0, 3)
                    resp.raise_for_status()
                    result = resp.json()
                    logger.info(
                        "[tool_registry] %s %s → %d in %.3fs",
                        method, url, resp.status_code, duration,
                    )
                    return result

                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "[tool_registry] HTTP %d from %s (attempt %d/%d): %s",
                        exc.response.status_code, url, attempt, MAX_RETRIES,
                        exc.response.text[:200],
                    )
                    if exc.response.status_code in (400, 401, 403, 404, 422):
                        # Non-retryable client error
                        raise RuntimeError(
                            f"Tool '{tool_id}' returned HTTP {exc.response.status_code}: "
                            f"{exc.response.text[:200]}"
                        ) from exc
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(attempt * _BACKOFF_BASE)
                    else:
                        raise RuntimeError(
                            f"Tool '{tool_id}' failed after {MAX_RETRIES} attempts."
                        ) from exc

                except Exception as exc:
                    if attempt < MAX_RETRIES:
                        wait = attempt * _BACKOFF_BASE
                        logger.warning(
                            "[tool_registry] %s attempt %d/%d failed: %s — retry in %.1fs",
                            tool_id, attempt, MAX_RETRIES, exc, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        raise RuntimeError(
                            f"Tool '{tool_id}' failed after {MAX_RETRIES} attempts: {exc}"
                        ) from exc

        # Should never be reached
        raise RuntimeError(f"Tool '{tool_id}' invocation exited retry loop unexpectedly.")

    # ── Invocation (sync convenience wrapper) ─────────────────────────────

    def invoke_tool_sync(
        self,
        tool_id: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Synchronous wrapper around :meth:`invoke_tool`."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self.invoke_tool(tool_id, params))
                    return future.result()
            return loop.run_until_complete(self.invoke_tool(tool_id, params))
        except RuntimeError as exc:
            # asyncio.get_event_loop() can raise RuntimeError in some contexts
            if "no current event loop" in str(exc).lower() or "running" not in str(exc).lower():
                return asyncio.run(self.invoke_tool(tool_id, params))
            raise


# ── Module-level singleton ─────────────────────────────────────────────────

_default_registry: Optional[ToolRegistry] = None


def get_tool_registry(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ToolRegistry:
    """Return the module-level ToolRegistry singleton.

    Parameters are only used on first creation; subsequent calls return the
    cached singleton regardless of the arguments.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry(base_url=base_url, api_key=api_key)
    return _default_registry


def reset_registry() -> None:
    """Reset the module-level singleton (useful in tests)."""
    global _default_registry
    _default_registry = None
