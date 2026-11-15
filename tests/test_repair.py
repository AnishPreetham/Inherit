import json
import warnings
from pathlib import Path

import pytest

from inherit.config import Config
from inherit.evidence import EvidenceStore
from inherit.llm import LLMClient
from inherit.sandbox import Sandbox
from inherit.stages.diagnose import Edit, build_prompt, diagnose, imported_repo_files, node_source
from inherit.stages.repair import PatchError, apply_edits, count_asserts, verify_repair
from inherit.stages.stability import Classification

DEMO = Path(__file__).resolve().parent.parent / "demo_repo"
VICTIM = "tests/test_report.py::test_opening_stock_levels"
POLLUTER = "tests/test_inventory.py::test_reserve_all_apples"
OTHER_FLAKY = "tests/test_settings.py::test_default_price_format"  # the demo's env-var leak


def test_unrelated_known_flake_does_not_block_verification(env):
    sb, store, _ = env
    r = verify_repair(sb, store, DEMO, VICTIM, [POLLUTER], [Edit(**GOOD_FIX)], runs=8, known_unstable={OTHER_FLAKY})
    assert r.status == "verified", r.reason
    assert OTHER_FLAKY not in r.other_failures

GOOD_FIX = {
    "path": "tests/test_inventory.py",
    "old": '    inventory.reserve("apple", 5)\n    assert inventory.available("apple") == 0\n',
    "new": '    inventory.reserve("apple", 5)\n    try:\n        assert inventory.available("apple") == 0\n'
           '    finally:\n        inventory.STOCK["apple"] = 5\n',
}
WEAKENING_FIX = {
    "path": "tests/test_report.py",
    "old": '    assert inventory.available("apple") == 5\n',
    "new": "    pass\n",
}


@pytest.fixture
def env():
    cfg = Config("", "", "", "", 20, "inherit-sandbox", 60, "local", "mock")
    store = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Sandbox(cfg, store), store, cfg


# --- source gathering -------------------------------------------------------------
def test_node_source_and_imports():
    assert "reserve" in node_source(DEMO, POLLUTER)
    assert imported_repo_files(DEMO, ["tests/test_report.py"]) == ["shop/inventory.py"]
    prompt = build_prompt(DEMO, VICTIM, [POLLUTER], "AssertionError")
    assert "STOCK = " in prompt and "test_opening_stock_levels" in prompt


# --- patch application ---------------------------------------------------------------
def test_apply_edits_never_touches_original():
    before = (DEMO / "tests/test_inventory.py").read_text()
    out = apply_edits(DEMO, [Edit(**GOOD_FIX)])
    assert "finally" in out["tests/test_inventory.py"]
    assert (DEMO / "tests/test_inventory.py").read_text() == before


@pytest.mark.parametrize("edit", [
    {"path": "../evil.py", "old": "", "new": "x"},
    {"path": "tests/test_inventory.py", "old": "not in file", "new": "x"},
    {"path": "tests/notes.txt", "old": "", "new": "x"},
    {"path": "tests/test_inventory.py", "old": "", "new": "overwrite"},
])
def test_apply_edits_rejects_bad_edits(edit):
    with pytest.raises(PatchError):
        apply_edits(DEMO, [Edit(**edit)])


def test_count_asserts_counts_raises_blocks():
    assert count_asserts("import pytest\ndef t():\n    assert 1\n    with pytest.raises(E):\n        f()\n") == 2


# --- verification against the demo repo ------------------------------------------------
def test_good_fix_is_verified(env):
    sb, store, _ = env
    r = verify_repair(sb, store, DEMO, VICTIM, [POLLUTER], [Edit(**GOOD_FIX)], runs=6,
                      known_unstable={VICTIM, OTHER_FLAKY})
    assert r.status == "verified", r.reason
    assert r.min_order_passed and r.victim_failures == 0 and r.runs == 6
    assert "remain unverified" in r.reason


def test_weakening_fix_is_rejected_without_running(env):
    sb, store, _ = env
    r = verify_repair(sb, store, DEMO, VICTIM, [POLLUTER], [Edit(**WEAKENING_FIX)], runs=6)
    assert r.status == "rejected" and r.evidence_ids == []


def test_ineffective_fix_is_not_verified(env):
    sb, store, _ = env
    harmless = {"path": "tests/test_inventory.py", "old": "import pytest\n", "new": "import pytest  # noop\n"}
    r = verify_repair(sb, store, DEMO, VICTIM, [POLLUTER], [Edit(**harmless)], runs=4)
    assert r.status == "not_verified" and r.min_order_passed is False


# --- diagnosis with a mock reasoner -------------------------------------------------------
def test_diagnose_uses_fresh_repro_and_structured_output(env):
    sb, store, cfg = env
    prompts = []

    def reasoner(role, task, system, user):
        prompts.append(user)
        return json.dumps({
            "cause": "shared_mutable_state",
            "explanation": "test_reserve_all_apples empties STOCK['apple'] and never restores it.",
            "confidence": "high",
            "edits": [GOOD_FIX],
        })

    llm = LLMClient(cfg, store, mock_handler=reasoner)
    c = Classification(VICTIM, "order_dependent", polluters=[POLLUTER], evidence_ids=["E-0001"])
    d = diagnose(sb, llm, store, DEMO, c)
    assert d.error == "" and d.diagnosis.cause == "shared_mutable_state"
    assert "AssertionError" in prompts[0] or "assert" in prompts[0]
    assert store.findings("diagnosis")[0]["status"] == "shared_mutable_state"
    assert store.llm_usage()[0]["role"] == "reasoner"
