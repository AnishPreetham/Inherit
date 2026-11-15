import shutil
import warnings
from pathlib import Path

import pytest

from inherit.config import Config
from inherit.evidence import EvidenceStore
from inherit.sandbox import Sandbox
from inherit.stages.bisect import ddmin
from inherit.stages.discover import discover_tests
from inherit.stages.stability import analyze_stability, classify_failure, parse_outcomes

DEMO = Path(__file__).resolve().parent.parent / "demo_repo"
VICTIM = "tests/test_report.py::test_opening_stock_levels"
POLLUTER = "tests/test_inventory.py::test_reserve_all_apples"


# --- ddmin (pure) ---------------------------------------------------------
def test_ddmin_finds_single_culprit():
    items = list("abcdefgh")
    assert ddmin(items, lambda s: "e" in s) == ["e"]


def test_ddmin_finds_pair_that_must_coexist():
    items = list("abcdefgh")
    assert sorted(ddmin(items, lambda s: "b" in s and "g" in s)) == ["b", "g"]


def test_ddmin_returns_empty_if_fails_without_predecessors():
    assert ddmin(["a", "b"], lambda s: True) == []


def test_ddmin_rejects_nonfailing_input():
    with pytest.raises(ValueError):
        ddmin(["a"], lambda s: False)


def test_ddmin_runs_each_subset_once():
    seen = []

    def fails(s):
        seen.append(tuple(s))
        return "c" in s

    ddmin(list("abcdef"), fails)
    assert len(seen) == len(set(seen))


def test_parse_outcomes():
    out = "tests/a.py::test_x PASSED\ntests/a.py::test_y FAILED\nrandom noise\n"
    assert parse_outcomes(out) == [("tests/a.py::test_x", "PASSED"), ("tests/a.py::test_y", "FAILED")]


# --- end to end on the demo repo (local backend, fast) ----------------------
@pytest.fixture(scope="module")
def sandbox():
    cfg = Config(
        api_key="", base_url="", model_reasoner="", model_worker="", stability_runs=20,
        sandbox_image="inherit-sandbox", sandbox_timeout=60,
        sandbox_backend="local" if shutil.which("docker") is None else "local", llm_backend="mock",
    )
    store = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Sandbox(cfg, store), store


def test_discover_finds_demo_tests(sandbox):
    sb, _ = sandbox
    ids, eid, _ = discover_tests(sb, DEMO)
    assert VICTIM in ids and POLLUTER in ids and len(ids) == 11


def test_stability_flags_victim_and_bisect_finds_polluter(sandbox):
    sb, store = sandbox
    result = analyze_stability(sb, DEMO, runs=12)
    assert VICTIM in result.unstable
    assert result.always_failing == []
    failing = next(r for r in result.runs if r.outcomes.get(VICTIM) == "FAILED")
    c = classify_failure(sb, store, DEMO, VICTIM, failing)
    assert c.kind == "order_dependent"
    assert c.polluters == [POLLUTER]
    assert store.findings("flaky_test")[0]["status"] == "order_dependent"
