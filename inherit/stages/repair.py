"""Check a proposed repair by running it, never by trusting the explanation.

A patch is applied only to sandbox copies. It is accepted as "verified" only if the minimal
failing order now passes, repeated shuffled runs show no failures, and the patch does not
remove assertions. Every check is recorded as evidence and the report states its limits.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..evidence import EvidenceStore
from ..sandbox import Sandbox
from .diagnose import Edit
from .stability import analyze_stability, run_order


@dataclass
class RepairResult:
    victim: str
    status: str  # verified | not_verified | rejected | invalid_patch | no_patch
    reason: str = ""
    patched_files: dict[str, str] = field(default_factory=dict)
    diff_summary: list[str] = field(default_factory=list)
    min_order_passed: bool | None = None
    runs: int = 0
    victim_failures: int = 0
    other_failures: dict[str, int] = field(default_factory=dict)
    known_unstable_failures: dict[str, int] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)


class PatchError(ValueError):
    pass


def _safe_rel(path: str) -> str:
    p = PurePosixPath(path.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise PatchError(f"path escapes the repository: {path}")
    if p.suffix != ".py":
        raise PatchError(f"only .py files may be patched: {path}")
    return p.as_posix()


def apply_edits(repo: Path, edits: list[Edit]) -> dict[str, str]:
    """Return {rel_path: new_content}. Original files are never modified."""
    out: dict[str, str] = {}
    for e in edits:
        rel = _safe_rel(e.path)
        exists = (repo / rel).is_file()
        current = out.get(rel, (repo / rel).read_text(encoding="utf-8") if exists else None)
        if e.old == "":
            if current is not None and current.strip():
                raise PatchError(f"empty 'old' only allowed for new or empty files: {rel}")
            out[rel] = e.new
            continue
        if current is None:
            raise PatchError(f"file does not exist: {rel}")
        count = current.count(e.old)
        if count != 1:
            raise PatchError(f"'old' text must occur exactly once in {rel}, found {count}")
        out[rel] = current.replace(e.old, e.new, 1)
    return out


def count_asserts(source: str) -> int:
    """Assertions in a file: assert statements plus pytest.raises blocks."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return -1
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            n += 1
        elif isinstance(node, ast.Attribute) and node.attr == "raises":
            n += 1
    return n


def weakened_files(repo: Path, patched: dict[str, str]) -> list[str]:
    weak = []
    for rel, new in patched.items():
        old_path = repo / rel
        old = old_path.read_text(encoding="utf-8") if old_path.is_file() else ""
        if count_asserts(new) < 0 or count_asserts(new) < count_asserts(old):
            weak.append(rel)
    return weak


def verify_repair(
    sb: Sandbox, store: EvidenceStore, repo: str | Path, victim: str, polluters: list[str],
    edits: list[Edit], runs: int = 20, base_seed: int = 1000, known_unstable: set[str] | None = None,
    check_order: list[str] | None = None,
) -> RepairResult:
    """`known_unstable`: tests already unstable before the patch; their failures are reported
    separately instead of counting against this repair.
    `check_order`: the order that failed before and must pass after (default: polluters, then victim)."""
    repo = Path(repo)
    result = RepairResult(victim, "no_patch")
    if not edits:
        result.reason = "no patch proposed"
        return _record(store, result)
    try:
        patched = apply_edits(repo, edits)
    except PatchError as exc:
        result.status, result.reason = "invalid_patch", str(exc)
        return _record(store, result)
    result.patched_files = patched
    result.diff_summary = [f"{e.path}: replace {len(e.old)} chars with {len(e.new)} chars" for e in edits]

    weak = weakened_files(repo, patched)
    if weak:
        result.status = "rejected"
        result.reason = f"patch removes assertions or breaks syntax in {weak}; refusing to weaken tests"
        return _record(store, result)

    order_run = run_order(sb, repo, check_order or [*polluters, victim], "repair_min_order", extra_files=patched)
    result.evidence_ids.append(order_run.evidence_id)
    result.min_order_passed = order_run.outcomes.get(victim) == "PASSED"

    stab = analyze_stability(sb, repo, runs=runs, base_seed=base_seed, kind="repair_random", extra_files=patched)
    result.evidence_ids += [r.evidence_id for r in stab.runs]
    result.runs = runs
    result.victim_failures = stab.fail_counts.get(victim, 0)
    known = set(known_unstable or ()) - {victim}
    result.other_failures = {t: n for t, n in stab.fail_counts.items() if n and t != victim and t not in known}
    result.known_unstable_failures = {t: n for t, n in stab.fail_counts.items() if n and t in known}

    if result.min_order_passed and result.victim_failures == 0 and not result.other_failures:
        result.status = "verified"
        result.reason = (
            f"minimal failing order now passes; the victim had no failures in {runs}/{runs} shuffled runs "
            f"(seeds {base_seed}-{base_seed + runs - 1}) and no other test newly failed."
        )
        if result.known_unstable_failures:
            result.reason += (f" Separately known-unstable tests still failed: "
                              f"{', '.join(sorted(result.known_unstable_failures))}.")
        result.reason += " Untested orders and environments remain unverified."
    else:
        result.status = "not_verified"
        problems = []
        if not result.min_order_passed:
            problems.append("minimal failing order still fails")
        if result.victim_failures:
            problems.append(f"victim failed {result.victim_failures}/{runs} shuffled runs")
        if result.other_failures:
            problems.append(f"other tests failed: {result.other_failures}")
        result.reason = "; ".join(problems)
    return _record(store, result)


def _record(store: EvidenceStore, result: RepairResult) -> RepairResult:
    store.add_finding("repair", result.victim, result.status, detail=result.reason, evidence_ids=result.evidence_ids)
    return result
