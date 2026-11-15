import json
import os
import warnings

import pytest

from inherit.config import Config
from inherit.demos import SAMPLES_DIR, check_report, load_demos
from inherit.evidence import EvidenceStore
from inherit.pipeline import run_analysis
from inherit.sandbox import Sandbox
from inherit.stages.discover import discover_tests

DEMOS = load_demos()


def local_sandbox():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Sandbox(Config("", "", "", "", 6, "inherit-sandbox", 60, "local", "mock"), EvidenceStore())


def test_seven_demos_with_complete_metadata():
    assert len(DEMOS) == 7
    for d in DEMOS.values():
        assert d["title"] and d["summary"] and d["shows"] and "expect" in d, d["id"]


@pytest.mark.parametrize("demo_id", sorted(DEMOS))
def test_demo_collects_tests(demo_id):
    ids, _, _ = discover_tests(local_sandbox(), DEMOS[demo_id]["path"])
    assert ids, f"{demo_id} has no collectable tests"


@pytest.mark.parametrize("demo_id", sorted(DEMOS))
def test_bundled_sample_matches_what_the_demo_promises(demo_id):
    path = SAMPLES_DIR / demo_id / "report.json"
    if not path.is_file():
        pytest.skip("sample not generated")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert check_report(report, DEMOS[demo_id]["expect"]) == []


def test_check_report_flags_mismatches():
    report = {
        "stability": {"unstable": [{"test": "t::v", "classification": "order_dependent", "polluters": ["t::x"]}],
                      "always_failing": []},
        "environment": {"install_status": "installed", "missing_modules": []},
    }
    assert check_report(report, {"order_dependent": {"t::v": ["t::x"]}}) == []
    assert check_report(report, {"order_dependent": {"t::v": ["t::y"]}})
    assert check_report(report, {"install_status": "failed"})
    assert check_report(report, {"missing_modules": ["Crypto"]})


@pytest.mark.skipif(os.getenv("INHERIT_DEMO_TESTS") != "1", reason="slow: runs every demo end to end")
@pytest.mark.parametrize("demo_id", sorted(DEMOS))
def test_demo_behaves_as_designed(demo_id, tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run_analysis(DEMOS[demo_id]["path"], tmp_path, Config("", "", "", "", 12, "inherit-sandbox", 60, "local", "mock"),
                     stability_runs=12, repair_runs=3, progress=lambda *a: None)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert check_report(report, DEMOS[demo_id]["expect"]) == []
