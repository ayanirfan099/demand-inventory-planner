#!/usr/bin/env python3
"""Emit a CI log tail as a GitHub Actions error annotation.

Why this exists: Actions logs and artifacts are served from a blob host that some restricted
development sandboxes cannot reach, while the checks API is reachable. A workflow annotation
carries up to ~64 kB of text and is readable from anywhere, so a failed browser test stays
debuggable without downloading anything.

Usage (CI only):  python3 scripts/ci-echo-failure.py /tmp/pw.log
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_CHARS = 4000


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ci-echo-failure.py <logfile>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else "(no log captured)"
    tail = text[-MAX_CHARS:]

    # Workflow-command escaping: % first, then newlines.
    escaped = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title=Playwright failure tail::{escaped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
