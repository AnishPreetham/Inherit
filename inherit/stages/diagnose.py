"""Ask the reasoner model why an order-dependent test fails, with the evidence in hand.

The model sees the polluter and victim test sources, the code they import, and a fresh
failure reproduced from the minimal order. It returns a structured diagnosis and,
for supported causes, a search-and-replace patch. Nothing here applies the patch.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..evidence import EvidenceStore
from ..llm import LLMClient, LLMError
from ..sandbox import Sandbox
from .stability import Classification, run_order

MAX_FILE_CHARS = 4000
MAX_FAILURE_CHARS = 3000

SUPPORTED_CAUSES = (
    "shared_mutable_state", "module_level_cache", "environment_variable_leak", "relies_on_other_test_setup",
)

SYSTEM_PROMPT = (
    "You diagnose order-dependent test failures in Python projects. Either a 'polluter' test leaves "
    "state behind that makes a 'victim' test fail when it runs afterwards, or a victim fails on its own "
    "because it silently relies on setup done by an earlier 'state-setter' test. You are given "
    "the sources and a real failure output.\n"
    "Reply with ONLY a JSON object:\n"
    '{"cause": one of ' + ", ".join(f'"{c}"' for c in SUPPORTED_CAUSES) + ', "unknown", '
    '"explanation": "<2-4 sentences grounded in the given code>", '
    '"confidence": "low" | "medium" | "high", '
    '"edits": [{"path": "<repo-relative file>", "old": "<exact existing text>", "new": "<replacement>"}]}\n'
    "Rules: each 'old' must be copied exactly from the given file and occur once. To create a "
    "new file (e.g. a conftest.py fixture), use an empty 'old'. Fix the isolation problem; never "
    "delete or weaken assertions. If you are not confident, return an empty edits list."
)


class Edit(BaseModel):
    path: str
    old: str = ""
    new: str


class Diagnosis(BaseModel):
    cause: Literal[
        "shared_mutable_state", "module_level_cache", "environment_variable_leak",
        "relies_on_other_test_setup", "unknown",
    ]
    explanation: str
    confidence: Literal["low", "medium", "high"]
    edits: list[Edit] = Field(default_factory=list)


@dataclass
class DiagnosisResult:
    victim: str
    polluters: list[str]
    diagnosis: Diagnosis | None
    repro_evidence: str
    error: str = ""


# --- source gathering ----------------------------------------------------------
def node_source(repo: Path, node_id: str) -> str:
    """Source of the test function named by a pytest node id like 'tests/x.py::Cls::test_y[p]'."""
    path, *names = node_id.split("::")
    target = names[-1].split("[")[0] if names else ""
    try:
        text = (repo / path).read_text(encoding="utf-8")
    except OSError:
        return ""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target:
            return ast.get_source_segment(text, node) or ""
    return ""


def imported_repo_files(repo: Path, test_files: list[str]) -> list[str]:
    """Repo-relative source files imported by the given test files (best effort)."""
    found: list[str] = []
    for rel in test_files:
        try:
            tree = ast.parse((repo / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for mod in modules:
                base = Path(*mod.split("."))
                for candidate in (base.with_suffix(".py"), base / "__init__.py"):
                    p = candidate.as_posix()
                    if (repo / candidate).is_file() and p not in found and (repo / candidate).stat().st_size:
                        found.append(p)
    return found


def _failure_excerpt(stdout: str) -> str:
    idx = stdout.find("FAILURES")
    return (stdout[idx:] if idx != -1 else stdout)[:MAX_FAILURE_CHARS]


def build_prompt(repo: Path, victim: str, polluters: list[str], failure: str, needs_setup: bool = False) -> str:
    test_files = sorted({n.split("::")[0] for n in [victim, *polluters]})
    if needs_setup:
        relation = (f"State-setter test(s): the victim fails when run alone and passes only after these ran "
                    f"(minimal set found by bisection): {polluters}")
        failure_label = "failure output when the victim runs alone"
    else:
        relation = f"Polluter test(s), minimal set found by bisection: {polluters}"
        failure_label = "failure output when run as polluters then victim"
    parts = [f"Victim test: {victim}", relation, ""]
    for node in [*polluters, victim]:
        parts += [f"--- source of {node} ---", node_source(repo, node), ""]
    for rel in [*test_files, *imported_repo_files(repo, test_files)]:
        text = (repo / rel).read_text(encoding="utf-8")[:MAX_FILE_CHARS]
        parts += [f"--- file {rel} ---", text, ""]
    parts += [f"--- {failure_label} ---", failure]
    return "\n".join(parts)


# --- stage entry point ---------------------------------------------------------
def diagnose(
    sb: Sandbox, llm: LLMClient, store: EvidenceStore, repo: str | Path, classification: Classification
) -> DiagnosisResult:
    repo = Path(repo)
    victim, polluters = classification.test, classification.polluters
    needs_setup = classification.kind == "depends_on_earlier_test"
    # reproduce the failure fresh: alone for a setup-dependent test, after its polluters otherwise
    repro = run_order(sb, repo, [victim] if needs_setup else [*polluters, victim], "diagnose_repro")
    result = DiagnosisResult(victim, polluters, None, repro.evidence_id)
    if repro.outcomes.get(victim) not in ("FAILED", "ERROR"):
        result.error = "the failure no longer reproduces"
        return result
    prompt = build_prompt(repo, victim, polluters, _failure_excerpt(repro.stdout), needs_setup)
    try:
        result.diagnosis = llm.complete_json("reasoner", SYSTEM_PROMPT, prompt, Diagnosis, task=f"diagnose:{victim}")
    except LLMError as exc:
        result.error = str(exc)
    d = result.diagnosis
    store.add_finding(
        "diagnosis", victim, d.cause if d else "failed",
        detail=(f"{d.explanation} (confidence: {d.confidence}; model-generated, unverified)" if d else result.error),
        evidence_ids=[*classification.evidence_ids, repro.evidence_id],
    )
    return result
