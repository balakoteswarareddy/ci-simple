#!/usr/bin/env python3
"""Harden generated workflows: resolve tag-pinned actions to immutable SHAs.

The renderer emits readable tag pins (actions/checkout@v4). Before production
use, run this to pin every third-party action to its commit SHA:

    python backend/scripts/pin_actions.py --workflow .github/workflows/ci.yml --write

Requires network access to api.github.com (GITHUB_TOKEN optional, raises rate
limits). `--check` exits 1 when any tag pin remains (CI gate).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.request
import json

USES_RE = re.compile(r"^(\s*(?:-\s+)?uses\s*:\s*)([^\s#]+)(.*)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def resolve_sha(owner: str, repo: str, ref: str, token: str) -> str:
    url = f"{API}/repos/{owner}/{repo}/commits/{ref}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "ci-agent-pin-actions/0.1",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["sha"]


def pin_line(line: str, cache: dict, token: str, check_only: bool) -> tuple[str, bool]:
    """Return (new_line, changed)."""
    match = USES_RE.match(line.rstrip("\n"))
    if not match:
        return line, False
    prefix, uses, suffix = match.groups()
    if uses.startswith(("./", "docker://")) or "@" not in uses:
        return line, False
    name, ref = uses.split("@", 1)
    if SHA_RE.match(ref):
        return line, False
    parts = name.split("/")
    if len(parts) < 2:
        return line, False
    owner, repo = parts[0], parts[1]
    if check_only:
        return line, True  # True = still unpinned
    key = (owner, repo, ref)
    if key not in cache:
        cache[key] = resolve_sha(owner, repo, ref, token)
    sha = cache[key]
    comment = f" # {ref}" if f"# {ref}" not in suffix else ""
    return f"{prefix}{name}@{sha}{suffix}{comment}\n" if line.endswith("\n") else f"{prefix}{name}@{sha}{suffix}{comment}", True


def main() -> int:
    parser = argparse.ArgumentParser(description="Pin github actions to SHAs.")
    parser.add_argument("--workflow", required=True, help="workflow file to process")
    parser.add_argument("--write", action="store_true", help="modify the file in place")
    parser.add_argument("--check", action="store_true", help="exit 1 if any tag pin remains")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    with open(args.workflow, encoding="utf-8") as fh:
        lines = fh.readlines()
    cache: dict = {}
    changed_any = False
    out_lines = []
    for line in lines:
        try:
            new_line, changed = pin_line(line, cache, token, check_only=args.check)
        except Exception as exc:
            print(f"warning: could not resolve {line.strip()}: {exc}", file=sys.stderr)
            out_lines.append(line)
            continue
        out_lines.append(new_line)
        changed_any = changed_any or changed

    if args.check:
        if changed_any:
            print("unpinned actions remain", file=sys.stderr)
            return 1
        print("all actions pinned")
        return 0
    if args.write:
        with open(args.workflow, "w", encoding="utf-8") as fh:
            fh.writelines(out_lines)
        print(f"pinned {args.workflow} ({len(cache)} resolved)")
    else:
        sys.stdout.writelines(out_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
