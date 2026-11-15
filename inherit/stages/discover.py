"""Discover the repo's pytest tests (no LLM involved)."""

from __future__ import annotations

from pathlib import Path

from ..sandbox import Sandbox

PYTEST_BASE = ["python", "-m", "pytest", "-p", "no:cacheprovider"]


def discover_tests(sb: Sandbox, repo: str | Path) -> tuple[list[str], str, str]:
    """Return (node ids in collection order, evidence id, collection output)."""
    res = sb.run(repo, [*PYTEST_BASE, "-p", "no:randomly", "--collect-only", "-q"], kind="collect")
    ids = [line.strip() for line in res.stdout.splitlines() if "::" in line and " " not in line.strip()]
    return ids, res.evidence_id, res.stdout + "\n" + res.stderr
