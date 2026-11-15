"""Prepare the repository's environment and explain import problems instead of hiding them.

Requirements are read from requirements*.txt files and pyproject.toml ([project] dependencies
and the usual test/dev extras). Lines pip could only satisfy by running code or reaching
outside the index (editable installs, local paths, VCS URLs, nested -r files) are skipped
and listed in the report. After collection, any "No module named ..." errors are reported
as an environment problem, so failing tests are not mistaken for flaky or broken ones.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..evidence import EvidenceStore
from ..sandbox import Sandbox

REQUIREMENT_FILES = (
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt", "requirements_dev.txt",
    "requirements_test.txt", "test-requirements.txt", "dev-requirements.txt",
)
PYPROJECT_EXTRAS = ("test", "tests", "testing", "dev")
UNSUPPORTED_PREFIXES = ("-", "git+", "hg+", "svn+", "bzr+", ".", "/", "file:", "http:", "https:")
# the sandbox already provides these at fixed versions
PROVIDED = {"pytest", "pytest-randomly", "pytest_randomly"}
MISSING_MODULE_RE = re.compile(r"No module named '([\w.]+)'")
COLLECT_ERROR_RE = re.compile(r"^ERROR collecting (\S+)", re.MULTILINE)


@dataclass
class EnvironmentInfo:
    sources: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    install_status: str = "not_needed"  # not_needed | installed | cached | failed
    install_evidence: str = ""
    install_error: str = ""
    missing_modules: list[str] = field(default_factory=list)
    collection_errors: list[str] = field(default_factory=list)


def _name(req: str) -> str:
    return re.split(r"[\s<>=!~;\[@]", req, maxsplit=1)[0].lower()


def gather_requirements(repo: str | Path) -> EnvironmentInfo:
    repo = Path(repo)
    info = EnvironmentInfo()
    seen: set[str] = set()

    def add(req: str, source: str) -> None:
        req = req.split(" #", 1)[0].strip()
        if not req or req.startswith("#"):
            return
        if req.startswith(UNSUPPORTED_PREFIXES) or " @ " in req:
            info.skipped.append(f"{req} ({source}: not installable from prebuilt wheels)")
            return
        if _name(req) in PROVIDED:
            return
        if req not in seen:
            seen.add(req)
            info.requirements.append(req)

    for name in REQUIREMENT_FILES:
        path = repo / name
        if path.is_file():
            info.sources.append(name)
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                add(line, name)

    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        project = data.get("project", {})
        deps = list(project.get("dependencies", []))
        for extra in PYPROJECT_EXTRAS:
            deps += project.get("optional-dependencies", {}).get(extra, [])
        if deps:
            info.sources.append("pyproject.toml")
            for d in deps:
                add(d, "pyproject.toml")
    return info


def prepare_environment(sb: Sandbox, store: EvidenceStore, repo: str | Path) -> EnvironmentInfo:
    info = gather_requirements(repo)
    if not info.requirements:
        return info
    res = sb.install_dependencies(info.requirements)
    info.install_evidence = res.evidence_id
    if res.exit_code == 0:
        info.install_status = "cached" if res.stdout == "cached" else "installed"
    else:
        info.install_status = "failed"
        tail = [line for line in (res.stderr or res.stdout).splitlines() if line.strip()][-3:]
        info.install_error = " ".join(tail)[:500] or "pip failed"
        store.add_finding("environment", "dependencies", "install_failed",
                          detail=info.install_error, evidence_ids=[res.evidence_id])
    return info


def record_collection_problems(
    store: EvidenceStore, info: EnvironmentInfo, collect_stdout: str, collect_evidence: str,
) -> None:
    info.collection_errors = sorted(set(COLLECT_ERROR_RE.findall(collect_stdout)))
    info.missing_modules = sorted(set(MISSING_MODULE_RE.findall(collect_stdout)))
    if info.missing_modules:
        store.add_finding(
            "environment", "imports", "missing_modules",
            detail=f"tests could not import: {', '.join(info.missing_modules)}",
            evidence_ids=[collect_evidence],
        )
