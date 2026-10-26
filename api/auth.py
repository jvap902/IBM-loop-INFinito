"""API Key authentication middleware and dependency.

The valid key set is read from the environment variable ``TOOL_API_KEYS``
(comma-separated list of keys, e.g. ``key-abc,key-xyz``).  As a fallback,
the legacy single-key variable ``TOOL_API_KEY`` is also accepted.

Keys are never hardcoded.  Set at least one of those variables before
starting the server.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

# ── Key loading ────────────────────────────────────────────────────────────

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _load_valid_keys() -> frozenset[str]:
    """Load the set of accepted API keys from environment variables.

    Reads ``TOOL_API_KEYS`` (comma-separated) first; falls back to
    ``TOOL_API_KEY`` for single-key setups.  Returns an empty frozenset
    when neither variable is set (all requests will be rejected).
    """
    raw_multi = os.getenv("TOOL_API_KEYS", "")
    keys: list[str] = [k.strip() for k in raw_multi.split(",") if k.strip()]

    if not keys:
        single = os.getenv("TOOL_API_KEY", "").strip()
        if single:
            keys = [single]

    return frozenset(keys)


# ── FastAPI dependency ─────────────────────────────────────────────────────

async def require_api_key(
    api_key: Optional[str] = Security(_API_KEY_HEADER),
) -> str:
    """FastAPI dependency that enforces API key authentication.

    Raises ``HTTP 401`` when no key is provided.
    Raises ``HTTP 403`` when the key is present but invalid.

    Returns the validated key string on success.
    """
    valid_keys = _load_valid_keys()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )

    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key
