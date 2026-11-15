import json
import warnings
from pathlib import Path

import pytest

from inherit.config import Config
from inherit.evidence import EvidenceStore
from inherit.llm import LLMClient
from inherit.sandbox import Sandbox
from inherit.stages.characterize import characterize, discover_functions

DEMO = Path(__file__).resolve().parent.parent / "demo_repo"
KNOWN_FLAKY = "tests/test_report.py::test_opening_stock_levels"

CANNED = {
    "bulk_discount": [[1, 10.0], [10, 10.0], [11, 10.0], [20, 2.5]],
    "with_tax": [[100], [100, 0.1], [0]],
    "slugify": [["Hello, World!"], [""], ["  a  b "]],
    "truncate": [["abcdefghij", 8], ["hi", 10], ["abc", 1]],
    "available": [["apple"], ["durian"]],
    "reserve": [["pear", 99], ["pear", 1]],
    "currency": [[]],
    "format_price": [[3], [2.5]],
}


def mock_inputs(role, task, system, user):
    name = task.split(".")[-1]
    cases = [{"args": a, "kwargs": {}} for a in CANNED.get(name, [[]])]
    return json.dumps({"cases": cases})


@pytest.fixture(scope="module")
def result():
    cfg = Config("", "", "", "", 20, "inherit-sandbox", 60, "local", "mock")
    store = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sb = Sandbox(cfg, store)
    llm = LLMClient(cfg, store, mock_handler=mock_inputs)
    return characterize(sb, llm, store, DEMO, known_unstable={KNOWN_FLAKY}), store


def test_discovers_public_functions_only():
    names = {f.qualified for f in discover_functions(DEMO)}
    assert "shop.pricing.bulk_discount" in names and "shop.text.slugify" in names
    assert not any("tests" in n or n.endswith("OutOfStock") for n in names)


def test_pins_observed_behavior_including_the_boundary(result):
    res, _ = result
    pins = {(p.function.name, tuple(p.args)): p.outcome for p in res.pinned}
    # quantity == 10 gets no discount: the pinned behavior exposes the suspected off-by-one
    assert pins[("bulk_discount", (10, 10.0))]["repr"] == "100.0"
    assert pins[("bulk_discount", (11, 10.0))]["repr"] == "99.0"
    assert res.failed_functions == {}


def test_exceptions_are_pinned_and_flagged_for_review(result):
    res, store = result
    flagged = [p for p in res.pinned if p.flagged]
    assert any(p.function.name == "reserve" and p.outcome["exc_type"] == "OutOfStock" for p in flagged)
    assert store.findings("review_pinned_behavior")


def test_generated_tests_reproduce_on_unmodified_repo(result):
    res, store = result
    assert res.validation_passed is True
    assert store.get_execution(res.validation_evidence)["kind"] == "characterization_validation"
    assert "# REVIEW" in res.test_source and "evidence: E-" in res.test_source


def test_state_changing_calls_are_observed_fresh_and_isolated(result):
    res, _ = result
    reserves = [p for p in res.pinned if p.function.name == "reserve" and p.outcome["status"] == "returned"]
    assert reserves and all(p.mutated == ["STOCK"] for p in reserves)
    # each probe saw the post-import stock (pear=3), not stock left by an earlier case
    assert reserves[0].outcome["repr"] == "2"
    # pins recreate the recorded state, so the demo's own polluter cannot break them
    assert "monkeypatch.setattr(shop.inventory, 'STOCK', {'apple': 5, 'pear': 3})" in res.test_source
    assert res.gate_runs == 6 and res.dropped == []


def test_env_vars_read_are_recreated_so_env_leaks_cannot_break_pins(result):
    res, _ = result
    pins = [p for p in res.pinned if p.function.name in ("currency", "format_price")]
    assert pins and all(p.outcome["env_reads"] == {"SHOP_CURRENCY": None} for p in pins)
    assert "monkeypatch.delenv('SHOP_CURRENCY', raising=False)" in res.test_source
    # the demo's own test_euro_store_uses_eur leaks SHOP_CURRENCY=EUR; the gate kept these pins anyway
    assert not any(n.startswith("test_shop_settings") for n in res.dropped)


def test_gate_drops_generated_test_that_leaks_state(tmp_path):
    # `bump` mutates state through an object attribute, which module-global tracking cannot see
    (tmp_path / "conftest.py").write_text("")
    (tmp_path / "counter.py").write_text(
        "class _Box:\n    n = 0\nBOX = _Box\n\ndef bump():\n    BOX.n += 1\n    return BOX.n\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_counter.py").write_text(
        "import counter\n\ndef test_starts_at_zero():\n    assert counter.BOX.n == 0\n"
    )
    cfg = Config("", "", "", "", 20, "inherit-sandbox", 60, "local", "mock")
    store = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sb = Sandbox(cfg, store)
    llm = LLMClient(cfg, store, mock_handler=lambda *a: '{"cases": [{"args": []}]}')
    res = characterize(sb, llm, store, tmp_path)
    assert res.dropped == ["test_counter_bump_case_1"]
    assert "leaks state into existing test tests/test_counter.py::test_starts_at_zero" in \
        store.findings("generated_test_dropped")[0]["detail"]
    assert res.pinned == []


def test_nondeterministic_outputs_are_excluded(tmp_path):
    (tmp_path / "noise.py").write_text("import random\ndef roll(n):\n    return random.random() + n\n")
    cfg = Config("", "", "", "", 20, "inherit-sandbox", 60, "local", "mock")
    store = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sb = Sandbox(cfg, store)
    llm = LLMClient(cfg, store, mock_handler=lambda *a: '{"cases": [{"args": [1]}, {"args": [2]}]}')
    res = characterize(sb, llm, store, tmp_path)
    assert res.pinned == [] and res.nondeterministic == 2
