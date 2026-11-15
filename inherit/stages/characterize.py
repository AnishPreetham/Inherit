"""Characterize behavior: propose inputs, probe them twice, pin only what repeats.

Generated tests are templated from recorded results, never written freehand by the model,
so every pinned assertion matches an execution in the evidence store.
"""

from __future__ import annotations

import ast
import builtins
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from ..evidence import EvidenceStore
from ..llm import LLMClient, LLMError
from ..sandbox import Sandbox
from .bisect import ddmin
from .stability import run_order, run_suite

GATE_RUNS = 5
SKIP_FILES = {"conftest.py", "setup.py"}
SKIP_DIRS = {"tests", "test", ".git", "__pycache__", ".venv", "venv", "node_modules"}
MAX_CASES = 8
GENERATED_TEST_PATH = "tests/test_inherit_characterization.py"

SYSTEM_PROMPT = (
    "You generate test inputs for Python functions so their real behavior can be observed. "
    "Reply with ONLY a JSON object of the form "
    '{"cases": [{"args": [...], "kwargs": {}}]}. '
    "Use only JSON-serialisable values. Include typical inputs, boundary values, and a few "
    "invalid inputs. Do not predict outputs."
)


class InputCase(BaseModel):
    args: list = Field(default_factory=list)
    kwargs: dict = Field(default_factory=dict)


class InputProposal(BaseModel):
    cases: list[InputCase]


@dataclass
class FunctionInfo:
    module: str
    name: str
    signature: str
    source: str
    has_docstring: bool

    @property
    def qualified(self) -> str:
        return f"{self.module}.{self.name}"


@dataclass
class PinnedCase:
    function: FunctionInfo
    args: list
    kwargs: dict
    outcome: dict  # status/repr or exc_type/exc_message from the probe
    evidence_ids: list[str]
    flagged: bool = False
    test_name: str = ""

    @property
    def mutated(self) -> list[str]:
        return self.outcome.get("mutated") or []


@dataclass
class CharacterizationResult:
    functions: list[FunctionInfo]
    pinned: list[PinnedCase] = field(default_factory=list)
    nondeterministic: int = 0
    stateful_excluded: int = 0
    failed_functions: dict[str, str] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    gate_runs: int = 0
    gate_evidence: list[str] = field(default_factory=list)
    test_source: str = ""
    validation_evidence: str = ""
    validation_passed: bool | None = None


# --- function discovery (AST, no execution) ----------------------------------
def discover_functions(repo: str | Path) -> list[FunctionInfo]:
    repo = Path(repo)
    found: list[FunctionInfo] = []
    for path in sorted(repo.rglob("*.py")):
        rel = path.relative_to(repo)
        if path.name in SKIP_FILES or path.name.startswith("test_") or SKIP_DIRS & set(rel.parts[:-1]):
            continue
        parts = rel.with_suffix("").parts
        if parts[0] == "src" and len(parts) > 1:  # src/ layout: src/ is on the path, not a package
            parts = parts[1:]
        module = ".".join(parts)
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef,)) and not node.name.startswith("_"):
                found.append(
                    FunctionInfo(
                        module=module,
                        name=node.name,
                        signature=f"{node.name}({ast.unparse(node.args)})",
                        source=ast.get_source_segment(text, node) or "",
                        has_docstring=ast.get_docstring(node) is not None,
                    )
                )
    return found


# --- probing ------------------------------------------------------------------
def _signature_key(result: dict | None) -> tuple | None:
    if result is None:
        return None
    return (
        result.get("status"), result.get("repr"), result.get("exc_type"), result.get("exc_message"),
        tuple(result.get("mutated") or ()),
    )


def _dedupe(cases: list[InputCase]) -> list[InputCase]:
    seen, out = set(), []
    for c in cases:
        key = json.dumps([c.args, c.kwargs], sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:MAX_CASES]


def characterize_function(
    sb: Sandbox, llm: LLMClient, repo: str | Path, fn: FunctionInfo, result: CharacterizationResult
) -> None:
    try:
        proposal = llm.complete_json(
            "worker", SYSTEM_PROMPT,
            f"Module: {fn.module}\nFunction signature: {fn.signature}\nSource:\n{fn.source}",
            InputProposal, task=f"inputs:{fn.qualified}",
        )
    except LLMError as exc:
        result.failed_functions[fn.qualified] = f"input generation failed: {exc}"
        return
    cases = _dedupe(proposal.cases)
    if not cases:
        result.failed_functions[fn.qualified] = "model proposed no usable inputs"
        return
    payload = [c.model_dump() for c in cases]
    e1, run1, timed1 = sb.probe_batch(repo, fn.module, fn.name, payload)
    e2, run2, timed2 = sb.probe_batch(repo, fn.module, fn.name, payload)
    if timed1 or timed2:
        result.failed_functions[fn.qualified] = "timed out while probing"
        return
    for case, r1, r2 in zip(cases, run1, run2):
        if r1 is None or r2 is None or r1.get("status") == "import_error":
            result.failed_functions[fn.qualified] = (r1 or r2 or {}).get("exc_message", "no result recorded")
            continue
        if _signature_key(r1) != _signature_key(r2):
            result.nondeterministic += 1
            continue
        if r1.get("restore_failed"):
            # mutates module state we cannot copy, so a pinned test would leak state
            result.stateful_excluded += 1
            continue
        result.pinned.append(
            PinnedCase(fn, case.args, case.kwargs, r1, [e1, e2], flagged=r1["status"] == "raised")
        )


# --- templated test generation ------------------------------------------------
def _literal_safe(text: str) -> bool:
    try:
        ast.literal_eval(text)
        return True
    except (ValueError, SyntaxError):
        return False


def _call_expr(p: PinnedCase) -> str:
    parts = [repr(a) for a in p.args] + [f"{k}={v!r}" for k, v in p.kwargs.items()]
    return f"{p.function.module}.{p.function.name}({', '.join(parts)})"


def _isolation_lines(p: PinnedCase) -> list[str]:
    """Recreate the module state the call was observed with; monkeypatch undoes it afterwards.

    Literal state is set to its recorded value, so a pin holds even if another test already
    changed that state. Non-literal state that the call mutates gets a private copy instead.
    """
    mod = p.function.module
    lines = []
    state = p.outcome.get("state_before") or {}
    for name, rep in sorted(state.items()):
        if _literal_safe(rep):
            lines.append(f"    monkeypatch.setattr({mod}, {name!r}, {rep})")
        elif name in p.mutated:
            lines.append(f"    monkeypatch.setattr({mod}, {name!r}, copy.deepcopy({mod}.{name}))")
    for name in p.mutated:
        if name not in state:
            lines.append(f"    monkeypatch.setattr({mod}, {name!r}, copy.deepcopy({mod}.{name}))")
    # environment variables the call read, set (or cleared) to what it saw when observed
    for key, value in sorted((p.outcome.get("env_reads") or {}).items()):
        if value is None:
            lines.append(f"    monkeypatch.delenv({key!r}, raising=False)")
        else:
            lines.append(f"    monkeypatch.setenv({key!r}, {value!r})")
    return lines


def render_tests(pinned: list[PinnedCase]) -> str:
    modules = sorted({p.function.module for p in pinned})
    lines = [
        '"""Characterization tests generated by Inherit.',
        "",
        "Each test pins behavior OBSERVED when the code ran; it records what the code does today,",
        "not what it should do. Review tests marked REVIEW before treating them as correct.",
        "Module state and the environment variables a call read are reset to what was recorded when",
        "it was observed (monkeypatch restores them afterwards), so these tests neither depend on nor",
        "leak into other tests' state.",
        '"""',
        "import copy",
        "",
        "import pytest",
        *(f"import {m}" for m in modules),
        "",
    ]
    counters: dict[str, int] = {}
    for p in pinned:
        if not p.test_name:  # names are assigned once so findings keep pointing at the right test
            base = re.sub(r"\W", "_", p.function.qualified)
            counters[base] = counters.get(base, 0) + 1
            p.test_name = f"test_{base}_case_{counters[base]}"
        isolate = _isolation_lines(p)
        params = "monkeypatch" if isolate else ""
        header = f"def {p.test_name}({params}):  # evidence: {', '.join(p.evidence_ids)}"
        if p.outcome["status"] == "returned":
            expected = p.outcome["repr"]
            lines += [header, *isolate]
            if _literal_safe(expected):
                lines += [f"    assert {_call_expr(p)} == {expected}"]
            else:
                lines += [f"    assert repr({_call_expr(p)}) == {expected!r}"]
        else:
            exc, msg = p.outcome["exc_type"], p.outcome.get("exc_message", "")
            lines += [f"# REVIEW: raises {exc} for these inputs; confirm this is intended", header, *isolate]
            if exc in _BUILTIN_EXC:
                lines += [
                    f"    with pytest.raises({exc}) as info:",
                    f"        {_call_expr(p)}",
                    f"    assert str(info.value) == {msg!r}",
                ]
            else:
                lines += [
                    "    with pytest.raises(Exception) as info:",
                    f"        {_call_expr(p)}",
                    f"    assert type(info.value).__name__ == {exc!r}",
                    f"    assert str(info.value) == {msg!r}",
                ]
        lines.append("")
    return "\n".join(lines)


_BUILTIN_EXC = {
    name for name, obj in vars(builtins).items() if isinstance(obj, type) and issubclass(obj, BaseException)
}


# --- stage entry point ---------------------------------------------------------
def characterize(
    sb: Sandbox, llm: LLMClient, store: EvidenceStore, repo: str | Path,
    functions: list[FunctionInfo] | None = None, known_unstable: set[str] | None = None,
) -> CharacterizationResult:
    functions = functions if functions is not None else discover_functions(repo)
    result = CharacterizationResult(functions=functions)
    for fn in functions:
        characterize_function(sb, llm, repo, fn, result)
    for p in result.pinned:
        if p.flagged:
            store.add_finding(
                "review_pinned_behavior", p.function.qualified, "needs_review",
                detail=f"raises {p.outcome['exc_type']}: {p.outcome.get('exc_message', '')} "
                       f"for args={p.args} kwargs={p.kwargs}",
                evidence_ids=p.evidence_ids,
            )
    result.test_source = render_tests(result.pinned)
    if result.pinned:
        gate_generated_tests(sb, store, repo, result, known_unstable=known_unstable)
        res = sb.run(
            repo, ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", GENERATED_TEST_PATH],
            kind="characterization_validation", extra_files={GENERATED_TEST_PATH: result.test_source},
        )
        result.validation_evidence = res.evidence_id
        result.validation_passed = res.exit_code == 0
    return result


def gate_generated_tests(
    sb: Sandbox, store: EvidenceStore, repo: str | Path, result: CharacterizationResult,
    runs: int = GATE_RUNS, base_seed: int = 500, known_unstable: set[str] | None = None,
) -> None:
    """Run generated tests together with the existing suite in shuffled order; drop any that fail.

    Running them with the existing suite also catches generated tests that pollute it.
    Tests already known to be unstable (from the stability stage) are not blamed on generated tests.
    """
    known_unstable = known_unstable or set()
    prefix = GENERATED_TEST_PATH + "::"
    extra = {GENERATED_TEST_PATH: result.test_source}

    baseline = [run_suite(sb, repo, base_seed + i, kind="gate_baseline") for i in range(runs)]
    gated = [run_suite(sb, repo, base_seed + i, kind="gate_generated", extra_files=extra) for i in range(runs)]
    # one fixed run with every generated test first, so leaks into the existing suite are always exercised
    gated.append(run_order(sb, repo, [GENERATED_TEST_PATH, "."], "gate_generated_first", extra_files=extra))
    result.gate_runs = len(gated)
    result.gate_evidence += [r.evidence_id for r in [*baseline, *gated]]

    baseline_failures = {t for r in baseline for t, o in r.outcomes.items() if o in ("FAILED", "ERROR")}
    failing = {t[len(prefix):] for r in gated for t, o in r.outcomes.items()
               if t.startswith(prefix) and o in ("FAILED", "ERROR")}
    reasons = {name: "failed in shuffled gate runs (possibly polluted by an existing test)" for name in failing}

    for run in gated:
        for victim, outcome in run.outcomes.items():
            if (outcome not in ("FAILED", "ERROR") or victim.startswith(prefix)
                    or victim in baseline_failures or victim in known_unstable):
                continue
            # an existing test broke only when generated tests were present: bisect for the polluter
            preds = [t for t in run.order[: run.order.index(victim)] if t.startswith(prefix)]
            culprits = _bisect_generated(sb, repo, extra, preds, victim, result.gate_evidence)
            for c in culprits:
                name = c[len(prefix):]
                failing.add(name)
                reasons[name] = f"leaks state into existing test {victim}"

    if not failing:
        return
    kept = []
    for p in result.pinned:
        if p.test_name in failing:
            result.dropped.append(p.test_name)
            store.add_finding(
                "generated_test_dropped", p.function.qualified, "dropped",
                detail=f"{p.test_name}: {reasons[p.test_name]}",
                evidence_ids=[*p.evidence_ids, *result.gate_evidence],
            )
        else:
            kept.append(p)
    result.pinned = kept
    result.test_source = render_tests(kept)


def _bisect_generated(
    sb: Sandbox, repo: str | Path, extra: dict[str, str], preds: list[str], victim: str, evidence: list[str],
) -> list[str]:
    """Minimal generated tests that make `victim` fail; all of `preds` if not reproducible."""
    def fails(subset: list[str]) -> bool:
        run = run_order(sb, repo, [*subset, victim], "gate_bisect", extra_files=extra)
        evidence.append(run.evidence_id)
        return run.outcomes.get(victim) in ("FAILED", "ERROR")

    try:
        return ddmin(preds, fails) if preds else []
    except ValueError:
        return preds
