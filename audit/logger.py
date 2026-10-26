"""AuditLogger — append-only event persistence for the Transparency Layer.

Backend selection (controlled by environment variables)
-------------------------------------------------------
AUDIT_BACKEND  "jsonl"      (default) Append to a local JSONL file.
               "postgres"   Write to a PostgreSQL table via psycopg2.

AUDIT_JSONL_PATH        Path to the JSONL log file (default: logs/audit.jsonl).
AUDIT_DB_DSN            PostgreSQL DSN for the postgres backend, e.g.
                        "postgresql://user:pass@localhost:5432/telecom_audit".

PII guardrails
--------------
The logger automatically strips any key in ``_PII_KEYS`` from ``tool_input``
before persisting.  Callers MUST NOT pass raw subscriber data; the guard is a
defence-in-depth measure, not the primary control.

Thread safety
-------------
The JSONL backend uses a threading.Lock for atomic line appends.  The
PostgreSQL backend relies on per-call connections (connection-per-write) which
is safe for moderate write rates.  For high-throughput production use, replace
with a connection pool (e.g. psycopg2.pool or asyncpg).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from audit.schema import AuditEvent

logger = logging.getLogger(__name__)

# ── PII key blocklist ──────────────────────────────────────────────────────
# Keys matching any of these names (case-insensitive) are removed from
# tool_input before the event is persisted.
_PII_KEYS: frozenset[str] = frozenset({
    "cpf", "cnpj", "nome", "name", "email", "phone", "telefone",
    "celular", "subscriber_id", "customer_id", "msisdn", "imsi",
    "password", "senha", "token", "secret", "api_key",
})


def _sanitise(data: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Remove PII keys from a dict (shallow, one-level deep)."""
    if data is None:
        return None
    return {k: v for k, v in data.items() if k.lower() not in _PII_KEYS}


# ── AuditLogger ────────────────────────────────────────────────────────────

class AuditLogger:
    """Central event logger for the Transparency & Auditability Layer.

    Usage
    -----
    >>> from audit.logger import AuditLogger
    >>> al = AuditLogger()
    >>> al.log_tool_call(
    ...     run_id="abc-123",
    ...     agent_id="operational",
    ...     tool_name="axis1_run",
    ...     tool_input={"contamination": 0.05},
    ...     tool_output_summary={"n_critical": 12, "duration_seconds": 1.4},
    ... )
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        jsonl_path: Optional[str] = None,
        db_dsn: Optional[str] = None,
    ) -> None:
        self._backend: str = (
            backend
            or os.getenv("AUDIT_BACKEND", "jsonl")
        ).lower()
        self._jsonl_path = Path(
            jsonl_path
            or os.getenv("AUDIT_JSONL_PATH", "logs/audit.jsonl")
        )
        self._db_dsn: str = db_dsn or os.getenv("AUDIT_DB_DSN", "")
        self._lock = threading.Lock()

        if self._backend == "jsonl":
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "[audit] AuditLogger initialised (jsonl → %s)", self._jsonl_path
            )
        elif self._backend == "postgres":
            self._ensure_pg_table()
            logger.info("[audit] AuditLogger initialised (postgres)")
        else:
            raise ValueError(
                f"[audit] Unknown AUDIT_BACKEND '{self._backend}'. "
                "Choose 'jsonl' or 'postgres'."
            )

    # ── Public high-level methods ──────────────────────────────────────────

    def log_tool_call(
        self,
        *,
        run_id: str,
        agent_id: str = "operational",
        tool_name: str,
        tool_input: Optional[dict[str, Any]] = None,
        tool_output_summary: Optional[dict[str, Any]] = None,
        model_version: Optional[str] = None,
        explanation: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record a tool-call event."""
        event = AuditEvent(
            event_type="tool_call",
            agent_id=agent_id,  # type: ignore[arg-type]
            run_id=run_id,
            model_version=model_version,
            tool_name=tool_name,
            tool_input=_sanitise(tool_input),
            tool_output_summary=tool_output_summary,
            explanation=explanation,
        )
        self._persist(event)
        return event

    def log_reasoning(
        self,
        *,
        run_id: str,
        agent_id: str = "planner",
        reasoning_text: str,
        model_version: Optional[str] = None,
    ) -> AuditEvent:
        """Record a Chain-of-Thought reasoning step."""
        event = AuditEvent(
            event_type="reasoning_step",
            agent_id=agent_id,  # type: ignore[arg-type]
            run_id=run_id,
            model_version=model_version,
            reasoning_text=reasoning_text,
        )
        self._persist(event)
        return event

    def log_model_run(
        self,
        *,
        run_id: str,
        agent_id: str = "system",
        tool_name: str,
        model_version: Optional[str] = None,
        tool_input: Optional[dict[str, Any]] = None,
        tool_output_summary: Optional[dict[str, Any]] = None,
        explanation: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record an ML model execution event."""
        event = AuditEvent(
            event_type="model_run",
            agent_id=agent_id,  # type: ignore[arg-type]
            run_id=run_id,
            model_version=model_version,
            tool_name=tool_name,
            tool_input=_sanitise(tool_input),
            tool_output_summary=tool_output_summary,
            explanation=explanation,
        )
        self._persist(event)
        return event

    # ── Persistence layer ──────────────────────────────────────────────────

    def _persist(self, event: AuditEvent) -> None:
        """Dispatch to the configured backend."""
        try:
            if self._backend == "jsonl":
                self._write_jsonl(event)
            else:
                self._write_postgres(event)
        except Exception as exc:
            # Logging failures must never crash the API — degrade gracefully.
            logger.error("[audit] Failed to persist event %s: %s", event.event_id, exc)

    def _write_jsonl(self, event: AuditEvent) -> None:
        """Append one JSON line to the JSONL file (thread-safe)."""
        line = event.model_dump_json() + "\n"
        with self._lock:
            with self._jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def _write_postgres(self, event: AuditEvent) -> None:
        """INSERT one row into the ``audit_events`` table."""
        try:
            import psycopg2  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "psycopg2 is required for the postgres backend: "
                "pip install psycopg2-binary"
            ) from exc

        row = event.model_dump()
        row["timestamp"] = event.timestamp.isoformat()
        row["tool_input"] = json.dumps(row["tool_input"]) if row["tool_input"] else None
        row["tool_output_summary"] = (
            json.dumps(row["tool_output_summary"])
            if row["tool_output_summary"]
            else None
        )
        row["explanation"] = (
            json.dumps(row["explanation"]) if row["explanation"] else None
        )

        sql = """
            INSERT INTO audit_events (
                event_id, timestamp, agent_id, event_type,
                tool_name, tool_input, tool_output_summary,
                reasoning_text, run_id, model_version, explanation
            ) VALUES (
                %(event_id)s, %(timestamp)s, %(agent_id)s, %(event_type)s,
                %(tool_name)s, %(tool_input)s, %(tool_output_summary)s,
                %(reasoning_text)s, %(run_id)s, %(model_version)s, %(explanation)s
            )
        """
        with psycopg2.connect(self._db_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, row)
            conn.commit()

    def _ensure_pg_table(self) -> None:
        """Create ``audit_events`` table if it does not exist."""
        try:
            import psycopg2  # noqa: PLC0415
        except ImportError:
            logger.warning(
                "[audit] psycopg2 not installed; skipping table creation check."
            )
            return

        ddl = """
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id            TEXT PRIMARY KEY,
                timestamp           TIMESTAMPTZ NOT NULL,
                agent_id            TEXT,
                event_type          TEXT NOT NULL,
                tool_name           TEXT,
                tool_input          JSONB,
                tool_output_summary JSONB,
                reasoning_text      TEXT,
                run_id              TEXT,
                model_version       TEXT,
                explanation         JSONB,
                created_at          TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_audit_agent_id
                ON audit_events (agent_id);
            CREATE INDEX IF NOT EXISTS idx_audit_event_type
                ON audit_events (event_type);
            CREATE INDEX IF NOT EXISTS idx_audit_run_id
                ON audit_events (run_id);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_events (timestamp);
        """
        try:
            with psycopg2.connect(self._db_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(ddl)
                conn.commit()
        except Exception as exc:
            logger.warning("[audit] Could not create audit_events table: %s", exc)

    # ── Query helper (JSONL backend only) ──────────────────────────────────

    def read_events(
        self,
        *,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        run_id: Optional[str] = None,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[AuditEvent]:
        """Read and filter events from the JSONL file.

        Parameters
        ----------
        agent_id    : Filter by agent identifier (exact match).
        event_type  : Filter by event type (exact match).
        run_id      : Filter by run identifier (exact match).
        date_start  : Return events at or after this UTC datetime.
        date_end    : Return events at or before this UTC datetime.
        limit       : Maximum number of events to return (newest first).

        Returns
        -------
        List of AuditEvent objects matching the filters, most recent first.

        Notes
        -----
        This is a linear scan over the JSONL file — suitable for development
        and low-volume audit queries.  For production, use the PostgreSQL
        backend with indexed queries instead.
        """
        if self._backend != "jsonl":
            raise NotImplementedError(
                "read_events() is only supported for the jsonl backend. "
                "Query the audit_events table directly for postgres."
            )

        if not self._jsonl_path.exists():
            return []

        results: list[AuditEvent] = []
        with self._lock:
            with self._jsonl_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = AuditEvent.model_validate_json(line)
                    except Exception:
                        continue

                    if agent_id and evt.agent_id != agent_id:
                        continue
                    if event_type and evt.event_type != event_type:
                        continue
                    if run_id and evt.run_id != run_id:
                        continue

                    # Normalise timestamp for comparison (ensure UTC-aware)
                    ts = evt.timestamp
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                    if date_start:
                        ds = date_start if date_start.tzinfo else date_start.replace(tzinfo=timezone.utc)
                        if ts < ds:
                            continue
                    if date_end:
                        de = date_end if date_end.tzinfo else date_end.replace(tzinfo=timezone.utc)
                        if ts > de:
                            continue

                    results.append(evt)

        # Return newest-first, capped at limit
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]


# ── Module-level singleton ─────────────────────────────────────────────────

_default_logger: Optional[AuditLogger] = None
_singleton_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """Return the module-level AuditLogger singleton.

    The singleton is created lazily on first call, using the environment
    variables ``AUDIT_BACKEND`` and ``AUDIT_JSONL_PATH`` / ``AUDIT_DB_DSN``.
    """
    global _default_logger
    if _default_logger is None:
        with _singleton_lock:
            if _default_logger is None:
                _default_logger = AuditLogger()
    return _default_logger
