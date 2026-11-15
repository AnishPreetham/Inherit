"""Run the suite repeatedly in shuffled order, flag unstable tests, and classify why."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..evidence import EvidenceStore
from ..sandbox import Sandbox
from .bisect import ddmin
from .discover import PYTEST_BASE

OUTCOME_RE = re.compile(r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
# --continue-on-collection-errors: one unimportable test file must not stop every other test from running
PYTEST_VERBOSE = [*PYTEST_BASE, "-v", "-o", "console_output_style=classic", "--continue-on-collection-errors"]
ISOLATION_RUNS = 5  # repeated so a test that is random even on its own is not mistaken for broken
REPLAY_RUNS = 2


@dataclass
class SuiteRun:
    seed: int | None
    evidence_id: str
    order: list[str]
    outcomes: dict[str, str]
    stdout: str = ""


@dataclass
class Classification:
    test: str
    # order_dependent:          fails only after certain earlier tests (polluters) ran
    # depends_on_earlier_test:  fails alone; passes only after certain earlier tests (state-setters) ran
    # nondeterministic:         fails intermittently even when run alone, or stops reproducing
    # fails_in_isolation:       fails alone and no passing order could be reproduced
    # not_reproducible:         failed during the shuffled runs, but never again when replayed
    kind: str
    polluters: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class StabilityResult:
    runs: list[SuiteRun]
    pass_counts: dict[str, int]
    fail_counts: dict[str, int]

    @property
    def unstable(self) -> list[str]:
        return sorted(t for t in self.fail_counts if self.fail_counts[t] and self.pass_counts.get(t))

    @property
    def always_failing(self) -> list[str]:
        return sorted(t for t in self.fail_counts if self.fail_counts[t] and not self.pass_counts.get(t))


def parse_outcomes(stdout: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for line in stdout.splitlines() if (m := OUTCOME_RE.match(line.strip()))]


def run_suite(
    sb: Sandbox, repo: str | Path, seed: int, kind: str = "suite_random",
    extra_files: dict[str, str] | None = None,
) -> SuiteRun:
    res = sb.run(repo, [*PYTEST_VERBOSE, f"--randomly-seed={seed}"], kind=kind, seed=seed, extra_files=extra_files)
    pairs = parse_outcomes(res.stdout)
    return SuiteRun(seed, res.evidence_id, [t for t, _ in pairs], dict(pairs))


def run_order(
    sb: Sandbox, repo: str | Path, order: list[str], kind: str,
    extra_files: dict[str, str] | None = None,
) -> SuiteRun:
    """Run exactly these tests, in exactly this order (randomisation disabled)."""
    res = sb.run(repo, [*PYTEST_VERBOSE, "-p", "no:randomly", *order], kind=kind, test_order=order,
                 extra_files=extra_files)
    pairs = parse_outcomes(res.stdout)
    run = SuiteRun(None, res.evidence_id, [t for t, _ in pairs], dict(pairs))
    run.stdout = res.stdout  # kept for diagnosis prompts
    return run


def analyze_stability(
    sb: Sandbox, repo: str | Path, runs: int = 20, base_seed: int = 1,
    kind: str = "suite_random", extra_files: dict[str, str] | None = None,
) -> StabilityResult:
    done = [run_suite(sb, repo, base_seed + i, kind, extra_files) for i in range(runs)]
    passes: dict[str, int] = {}
    fails: dict[str, int] = {}
    for run in done:
        for test, outcome in run.outcomes.items():
            fails.setdefault(test, 0)
            passes.setdefault(test, 0)
            if outcome in ("FAILED", "ERROR"):
                fails[test] += 1
            elif outcome == "PASSED":
                passes[test] += 1
    return StabilityResult(done, passes, fails)


def classify_failure(
    sb: Sandbox, store: EvidenceStore, repo: str | Path, victim: str, failing_run: SuiteRun,
    all_runs: list[SuiteRun] | None = None,
) -> Classification:
    """Decide why `victim` is unstable, bisecting to the tests responsible when the cause is ordering.

    `all_runs` (the shuffled runs) lets a test that fails alone be traced to the earlier
    test it silently depends on, using a run in which it passed.
    """
    evidence: list[str] = []

    def failed(run: SuiteRun) -> bool:
        evidence.append(run.evidence_id)
        return run.outcomes.get(victim) in ("FAILED", "ERROR")

    def preceding(run: SuiteRun) -> list[str]:
        return run.order[: run.order.index(victim)] if victim in run.order else []

    alone = [failed(run_order(sb, repo, [victim], "isolation")) for _ in range(ISOLATION_RUNS)]
    if all(alone):
        result = _classify_fails_alone(sb, repo, victim, all_runs or [], failed, preceding, evidence)
    elif any(alone):
        result = Classification(victim, "nondeterministic", evidence_ids=evidence,
                                note=f"failed in {sum(alone)} of {ISOLATION_RUNS} runs even when run alone, "
                                     "so the cause is inside the test or code (randomness, time, I/O), not ordering")
    else:
        predecessors = preceding(failing_run)
        replays = [failed(run_order(sb, repo, [*predecessors, victim], "replay_order")) for _ in range(REPLAY_RUNS)]
        if not any(replays):
            result = Classification(victim, "not_reproducible", evidence_ids=evidence,
                                    note="failed during the shuffled runs but replaying the same order did not "
                                         "reproduce it; cause unknown (possibly timing or randomness)")
        else:
            try:
                minimal = ddmin(predecessors, lambda s: failed(run_order(sb, repo, [*s, victim], "bisect")))
                result = Classification(victim, "order_dependent", polluters=minimal, evidence_ids=evidence,
                                        note=f"fails only after running {len(minimal)} specific earlier test(s)")
            except ValueError:
                result = Classification(victim, "nondeterministic", evidence_ids=evidence,
                                        note="the failing order stopped reproducing during bisection, so the "
                                             "failure is not explained by ordering alone")
    store.add_finding(
        "flaky_test", victim, result.kind,
        detail=f"{result.note}; polluters={result.polluters}",
        evidence_ids=result.evidence_ids,
    )
    return result


def _classify_fails_alone(sb, repo, victim, all_runs, failed, preceding, evidence) -> Classification:
    """The victim fails on its own. If it passed in some shuffled run, find what it needed first."""
    passing = next((r for r in all_runs if r.outcomes.get(victim) == "PASSED"), None)
    if passing is not None:
        predecessors = preceding(passing)

        def passes(subset: list[str]) -> bool:
            return not failed(run_order(sb, repo, [*subset, victim], "bisect_setup"))

        try:
            setters = ddmin(predecessors, passes) if predecessors else []
        except ValueError:
            setters = []
        if setters:
            return Classification(victim, "depends_on_earlier_test", polluters=setters, evidence_ids=evidence,
                                  note=f"fails when run alone; passes only after {len(setters)} specific earlier "
                                       "test(s) ran, so it relies on setup it does not do itself")
    return Classification(victim, "fails_in_isolation", evidence_ids=evidence,
                          note=f"failed in all {ISOLATION_RUNS} runs alone and no passing order could be reproduced")
