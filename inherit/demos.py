"""Bundled demo projects: discovery, and checking a report against what each demo is built to show.

Each demo folder holds a demo.json with a title, a summary, what it shows, and an "expect"
block. `check_report` compares an analysis report with those expectations, so a demo can't
silently stop demonstrating what its description promises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIRS = [ROOT / "demo_repo", *sorted((ROOT / "demos").glob("*/"))]
SAMPLES_DIR = ROOT / "samples"


def load_demos() -> dict[str, dict[str, Any]]:
    demos: dict[str, dict[str, Any]] = {}
    for path in DEMO_DIRS:
        meta = path / "demo.json"
        if meta.is_file():
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["path"] = path
            demos[data["id"]] = data
    return demos


def check_report(report: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    """Return a list of mismatches between a report and a demo's expectations (empty = as designed)."""
    problems: list[str] = []
    by_test = {u["test"]: u for u in report["stability"]["unstable"]}
    for kind in ("order_dependent", "depends_on_earlier_test"):
        for victim, related in expect.get(kind, {}).items():
            got = by_test.get(victim)
            if got is None:
                problems.append(f"{victim} was not found unstable")
            elif got["classification"] != kind:
                problems.append(f"{victim} classified {got['classification']}, expected {kind}")
            elif sorted(got["polluters"]) != sorted(related):
                problems.append(f"{victim} traced to {got['polluters']}, expected {related}")
    for victim in expect.get("nondeterministic", []):
        got = by_test.get(victim)
        if got is None or got["classification"] != "nondeterministic":
            problems.append(f"{victim} expected nondeterministic, got {got['classification'] if got else 'stable'}")
    if "unstable" in expect and sorted(by_test) != sorted(expect["unstable"]):
        problems.append(f"unstable tests {sorted(by_test)}, expected {expect['unstable']}")
    if "always_failing" in expect and sorted(report["stability"]["always_failing"]) != sorted(expect["always_failing"]):
        problems.append(f"always failing {report['stability']['always_failing']}, expected {expect['always_failing']}")
    env = report.get("environment", {})
    status = env.get("install_status")
    if status == "cached":  # same outcome as installed, reused from an earlier analysis
        status = "installed"
    if "install_status" in expect and status != expect["install_status"]:
        problems.append(f"install status {env.get('install_status')}, expected {expect['install_status']}")
    for module in expect.get("missing_modules", []):
        if module not in env.get("missing_modules", []):
            problems.append(f"missing module {module} not reported")
    return problems
