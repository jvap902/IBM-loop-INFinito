#!/usr/bin/env python3
"""Export the FastAPI OpenAPI 3.1 schema to ``openapi.yaml``.

Usage
-----
    python export_openapi.py               # writes to ./openapi.yaml
    python export_openapi.py --out /path/to/output.yaml

The script imports the FastAPI ``app`` object directly — no running server
is required.  It uses ``app.openapi()`` (FastAPI's built-in schema generator)
and serialises the result as YAML via ``PyYAML``.

The ``openapi.yaml`` at the repository root is the **single source of truth**
for all tool contracts and is consumed by the LangGraph tool-calling layer in
Sub-Task 6.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml  # PyYAML — install with: pip install PyYAML


def export(out_path: Path) -> None:
    """Generate and write the OpenAPI schema to *out_path*."""
    # Import here so that the FastAPI app is fully configured before we
    # call .openapi() — this also catches import errors early.
    from api.main import app  # noqa: PLC0415

    schema: dict = app.openapi()

    # FastAPI 0.100+ defaults to OpenAPI 3.1.0 — confirm or patch.
    schema.setdefault("openapi", "3.1.0")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.dump(schema, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # Also write a JSON copy for consumers that prefer JSON.
    json_path = out_path.with_suffix(".json")
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(schema, fh, ensure_ascii=False, indent=2)

    print(f"[OK] OpenAPI schema written to: {out_path.resolve()}")
    print(f"[OK] OpenAPI JSON copy written to: {json_path.resolve()}")
    endpoints = [
        f"  {path} [{', '.join(methods.keys()).upper()}]"
        for path, methods in schema.get("paths", {}).items()
    ]
    print(f"  Documented endpoints ({len(endpoints)}):")
    for ep in endpoints:
        print(ep)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the Telecom AI Platform Tool API OpenAPI schema."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("openapi.yaml"),
        help="Output YAML file path (default: ./openapi.yaml).",
    )
    args = parser.parse_args()

    try:
        export(args.out)
    except Exception as exc:
        print(f"[FAIL] Export failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
