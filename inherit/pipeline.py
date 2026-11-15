"""Run every stage against one repository and write the outputs."""

from __future__ import annotations

import difflib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .evidence import EvidenceStore
from .llm import LLMClient
from .mock import mock_handler
from .report import build_report, render_html
from .sandbox import Sandbox
from .stages.characterize import GENERATED_TEST_PATH, CharacterizationResult, characterize
from .stages.diagnose import DiagnosisResult, diagnose
from .stages.discover import discover_tests
from .stages.docs import DocEntry, document, render_docs
from .stages.environment import EnvironmentInfo, prepare_environment, record_collection_problems
from .stages.repair import RepairResult, verify_repair
from .stages.stability import Classification, StabilityResult, analyze_stability, classify_failure

# unstable tests to classify, bisect and (if order-dependent) diagnose and repair
DEFAULT_MAX_INVESTIGATIONS = int(os.getenv("INHERIT_MAX_INVESTIGATIONS", "10"))

Progress = Callable[[str, str], None]  # (stage, message)


@dataclass
class AnalysisResult:
    repo: str
    tests: list[str]
    stability: StabilityResult
    environment: EnvironmentInfo = field(default_factory=EnvironmentInfo)
    max_investigations: int = DEFAULT_MAX_INVESTIGATIONS
    classifications: list[Classification] = field(default_factory=list)
    diagnoses: list[DiagnosisResult] = field(default_factory=list)
    repairs: list[RepairResult] = field(default_factory=list)
    characterization: CharacterizationResult | None = None
    docs: list[DocEntry] = field(default_factory=list)
    stability_runs: int = 0
    repair_runs: int = 0
    seconds: float = 0.0


def unified_diff(repo: Path, patched: dict[str, str]) -> str:
    chunks = []
    for rel, new in patched.items():
        old_path = repo / rel
        old = old_path.read_text(encoding="utf-8").splitlines(keepends=True) if old_path.is_file() else []
        chunks += difflib.unified_diff(old, new.splitlines(keepends=True), f"a/{rel}", f"b/{rel}")
    return "".join(chunks)


def run_analysis(
    repo: str | Path, out_dir: str | Path, cfg: Config | None = None,
    stability_runs: int | None = None, repair_runs: int = 20,
    progress: Progress | None = None, llm: LLMClient | None = None,
    max_investigations: int | None = None,
) -> AnalysisResult:
    cfg = cfg or Config.from_env()
    repo, out = Path(repo).resolve(), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "evidence.db"
    if db.exists():
        db.unlink()
    store = EvidenceStore(str(db))
    say = progress or (lambda stage, msg: print(f"[{stage}] {msg}", flush=True))
    sb = Sandbox(cfg, store)
    llm = llm or LLMClient(cfg, store, mock_handler=mock_handler if cfg.llm_backend == "mock" else None)
    if cfg.llm_backend == "mock":
        say("setup", "No Token Factory key: using the offline mock model (heuristic inputs, no diagnosis).")
    start = time.monotonic()
    runs = stability_runs or cfg.stability_runs

    say("environment", "reading requirements")
    env = prepare_environment(sb, store, repo)
    if env.requirements:
        say("environment", f"{len(env.requirements)} requirement(s) from {', '.join(env.sources)}: {env.install_status}"
            + (f" ({env.install_error})" if env.install_error else ""))
    else:
        say("environment", "no third-party requirements declared")
    if env.skipped:
        say("environment", f"skipped {len(env.skipped)} requirement line(s) that need more than a prebuilt wheel")

    say("discover", "collecting tests")
    tests, collect_eid, collect_out = discover_tests(sb, repo)
    record_collection_problems(store, env, collect_out, collect_eid)
    say("discover", f"{len(tests)} tests found")
    if env.missing_modules:
        say("discover", f"tests could not import: {', '.join(env.missing_modules)}. Failures in those files are "
                        "an environment problem, not flakiness")

    say("stability", f"running the suite {runs} times in shuffled order")
    stab = analyze_stability(sb, repo, runs=runs)
    say("stability", f"unstable: {len(stab.unstable)}, always failing: {len(stab.always_failing)}")
    cap = max_investigations if max_investigations is not None else DEFAULT_MAX_INVESTIGATIONS
    result = AnalysisResult(str(repo), tests, stab, environment=env, max_investigations=cap,
                            stability_runs=runs, repair_runs=repair_runs)

    if len(stab.unstable) > cap:
        say("investigate", f"{len(stab.unstable)} unstable tests; investigating the {cap} that failed most often")
    ranked = sorted(stab.unstable, key=lambda t: (-stab.fail_counts[t], t))
    for i, victim in enumerate(ranked[:cap], 1):
        failing = next(r for r in stab.runs if r.outcomes.get(victim) in ("FAILED", "ERROR"))
        say("investigate", f"({i}/{min(cap, len(ranked))}) classifying {victim}")
        c = classify_failure(sb, store, repo, victim, failing, all_runs=stab.runs)
        result.classifications.append(c)
        role = "needs setup from" if c.kind == "depends_on_earlier_test" else "polluter(s)"
        say("investigate", f"{c.kind}" + (f"; {role}: {c.polluters}" if c.polluters else ""))
        if c.kind not in ("order_dependent", "depends_on_earlier_test"):
            continue
        say("diagnose", f"asking the reasoner model about {victim}")
        d = diagnose(sb, llm, store, repo, c)
        result.diagnoses.append(d)
        if d.diagnosis:
            say("diagnose", f"cause: {d.diagnosis.cause} ({d.diagnosis.confidence} confidence)")
            if d.diagnosis.edits:
                say("repair", f"checking the proposed patch with {repair_runs} shuffled runs")
            # a setup-dependent test must pass alone after the fix; an order-dependent one after its polluters
            check = [victim] if c.kind == "depends_on_earlier_test" else [*c.polluters, victim]
            r = verify_repair(sb, store, repo, victim, c.polluters, d.diagnosis.edits, runs=repair_runs,
                              known_unstable=set(stab.unstable) | set(stab.always_failing), check_order=check)
            result.repairs.append(r)
            say("repair", f"{r.status}: {r.reason}")
            if r.patched_files:
                patches = out / "patches"
                patches.mkdir(exist_ok=True)
                name = victim.replace("/", "_").replace("::", "__") + ".diff"
                (patches / name).write_text(unified_diff(repo, r.patched_files), encoding="utf-8")
        else:
            say("diagnose", f"no diagnosis: {d.error}")

    say("characterize", "probing functions and pinning observed behavior")
    char = characterize(sb, llm, store, repo, known_unstable=set(stab.unstable) | set(stab.always_failing))
    result.characterization = char
    say("characterize", f"{len(char.pinned)} behaviors pinned, {len(char.dropped)} generated tests dropped")
    gen = out / GENERATED_TEST_PATH
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text(char.test_source, encoding="utf-8")

    say("docs", "writing evidence-linked documentation")
    result.docs = document(llm, store, char)
    (out / "docs.md").write_text(render_docs(result.docs), encoding="utf-8")

    result.seconds = time.monotonic() - start
    report = build_report(result, store, cfg)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.html").write_text(render_html(report), encoding="utf-8")
    say("done", f"report written to {out / 'report.html'} in {result.seconds:.0f}s")
    store.close()
    return result
