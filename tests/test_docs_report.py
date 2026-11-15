import json
import warnings
from pathlib import Path

import pytest

from inherit.config import Config
from inherit.evidence import EvidenceStore
from inherit.mock import inputs_for
from inherit.pipeline import run_analysis
from inherit.stages.characterize import FunctionInfo
from inherit.stages.docs import Claim, validate_claims

DEMO = Path(__file__).resolve().parent.parent / "demo_repo"
FN = FunctionInfo("shop.pricing", "bulk_discount", "bulk_discount(quantity, unit_price)", "", False)


def test_validator_downgrades_bad_citations():
    s = EvidenceStore()
    mine = s.record_execution("probe_batch", "x", 0, meta={"module": "shop.pricing", "function": "bulk_discount"})
    other = s.record_execution("probe_batch", "x", 0, meta={"module": "shop.text", "function": "slugify"})
    claims = [
        Claim(text="ok", kind="observed", evidence_ids=[mine]),
        Claim(text="no cite", kind="observed"),
        Claim(text="ghost", kind="observed", evidence_ids=["E-9999"]),
        Claim(text="wrong fn", kind="observed", evidence_ids=[other]),
        Claim(text="rule", kind="inferred", evidence_ids=[mine]),
    ]
    checked, downgraded = validate_claims(s, FN, claims, allowed={mine})
    assert [c.kind for c in checked] == ["observed", "inferred", "inferred", "inferred", "inferred"]
    assert len(downgraded) == 3 and checked[4].evidence_ids == []


def test_mock_inputs_follow_param_hints():
    cases = inputs_for("bulk_discount(quantity, unit_price)")
    assert cases and all(isinstance(c["args"][0], int) for c in cases)
    assert inputs_for("f()") == [{"args": [], "kwargs": {}}]
    assert inputs_for("f(a, b=2)")[0]["args"] == [1]


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    out = tmp_path_factory.mktemp("report")
    cfg = Config("", "", "", "", 8, "inherit-sandbox", 60, "local", "mock")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = run_analysis(DEMO, out, cfg, stability_runs=8, repair_runs=4, progress=lambda *a: None)
    return result, out


def test_pipeline_writes_all_outputs(analysis):
    _, out = analysis
    for f in ["report.html", "report.json", "docs.md", "evidence.db", "tests/test_inherit_characterization.py"]:
        assert (out / f).is_file(), f


def test_report_keeps_dimensions_and_states_limits(analysis):
    _, out = analysis
    r = json.loads((out / "report.json").read_text())
    assert {"stability", "repairs", "behavior", "docs", "uncertainties", "model_usage", "evidence"} <= r.keys()
    assert "score" not in json.dumps(r).lower()
    assert r["stability"]["unstable"][0]["classification"] == "order_dependent"
    assert any("mock model" in u for u in r["uncertainties"])
    assert any("WITHOUT container isolation" in u for u in r["uncertainties"])
    # the mock gives no patch, so the repair must not be reported as verified
    assert r["repairs"][0]["status"] == "no_patch"
    ids = {e["id"] for e in r["evidence"]}
    assert set(r["stability"]["unstable"][0]["evidence_ids"]) <= ids


def test_docs_cite_real_evidence(analysis):
    _, out = analysis
    docs = (out / "docs.md").read_text(encoding="utf-8")
    r = json.loads((out / "report.json").read_text())
    ids = {e["id"] for e in r["evidence"]}
    import re
    cited = set(re.findall(r"\[(E-\d{4})\]", docs))
    assert cited and cited <= ids
    html = (out / "report.html").read_text(encoding="utf-8")
    assert all(f'id="{e}"' in html for e in cited)
