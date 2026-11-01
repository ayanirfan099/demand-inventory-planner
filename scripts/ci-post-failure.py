#!/usr/bin/env python3
"""Post the tail of a CI log as a pull-request comment (diagnostics only).

Why this exists: Actions logs and artifacts live on a blob host that some restricted
development sandboxes cannot reach, while the GitHub API is reachable. When a browser test
fails, the tail of its output is echoed onto the pull request so the failure is inspectable
from anywhere.

Usage (CI only):
    python3 scripts/ci-post-failure.py /tmp/pw.log

Requires GH_TOKEN, GITHUB_REPOSITORY and PR_NUMBER. Never posts when PR_NUMBER is absent.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

MAX_CHARS = 6000


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ci-post-failure.py <logfile>", file=sys.stderr)
        return 2

    token = os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if not (token and repo and pr_number):
        print("missing GH_TOKEN, GITHUB_REPOSITORY or PR_NUMBER; skipping comment")
        return 0

    log_path = Path(sys.argv[1])
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else "(no log captured)"
    tail = text[-MAX_CHARS:]
    run_id = os.environ.get("GITHUB_RUN_ID", "?")
    body = f"Playwright failed in CI (run {run_id}).\n\n```\n{tail}\n```"

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
        data=json.dumps({"body": body}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "forecastops-ci",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        print("comment posted:", response.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
