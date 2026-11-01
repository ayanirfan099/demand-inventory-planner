#!/usr/bin/env python3
"""Write the API's OpenAPI document to packages/contracts/openapi.json.

The snapshot is the machine-readable half of the cross-component contract: browser clients
and reviewers can read it without running the API, and
``packages/contracts/tests/test_contracts.py`` fails when it drifts from the code.

Usage:
    ./.venv/bin/python scripts/export-openapi.py          # write the snapshot
    ./.venv/bin/python scripts/export-openapi.py --check   # exit 1 if it is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "packages" / "contracts" / "openapi.json"


def build_document() -> dict:
    from app.main import create_app

    return create_app().openapi()


def serialise(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    document = build_document()
    rendered = serialise(document)

    if "--check" in argv:
        current = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.exists() else ""
        if current != rendered:
            print("openapi.json is stale; run scripts/export-openapi.py", file=sys.stderr)
            return 1
        print("openapi.json is current")
        return 0

    SNAPSHOT.write_text(rendered, encoding="utf-8")
    path_count = len(document.get("paths", {}))
    print(f"wrote {SNAPSHOT.relative_to(REPO_ROOT)} ({path_count} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
