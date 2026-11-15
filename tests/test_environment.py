import json
import os
import warnings
from pathlib import Path

import pytest

from inherit.config import Config
from inherit.evidence import EvidenceStore
from inherit.pipeline import run_analysis
from inherit.sandbox import Sandbox
from inherit.stages.environment import EnvironmentInfo, gather_requirements, record_collection_problems

DEMO = Path(__file__).resolve().parent.parent / "demo_repo"


def local_cfg(runs=6):
    return Config("", "", "", "", runs, "inherit-sandbox", 60, "local", "mock")


def test_gather_requirements_reads_files_and_pyproject(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\nrequests>=2  # inline\n-e .\ngit+https://example.com/x.git\npytest==7.0\n\nattrs\n"
    )
    (tmp_path / "requirements-dev.txt").write_text("attrs\nhypothesis\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["click>=8"]\n'
        '[project.optional-dependencies]\ntest = ["freezegun"]\ndocs = ["sphinx"]\n'
    )
    info = gather_requirements(tmp_path)
    assert info.requirements == ["requests>=2", "attrs", "hypothesis", "click>=8", "freezegun"]
    assert len(info.skipped) == 2  # editable install and VCS URL; pytest is provided, not skipped
    assert info.sources == ["requirements.txt", "requirements-dev.txt", "pyproject.toml"]


def test_no_requirements_means_nothing_to_install():
    assert gather_requirements(DEMO).requirements == []


def test_collection_problems_are_recorded():
    store = EvidenceStore()
    info = EnvironmentInfo()
    out = ("ERROR collecting tests/test_api.py\nE   ModuleNotFoundError: No module named 'requests'\n"
           "ERROR collecting tests/test_np.py\nE   ModuleNotFoundError: No module named 'numpy.linalg'\n")
    record_collection_problems(store, info, out, "E-0001")
    assert info.missing_modules == ["numpy.linalg", "requests"]
    assert info.collection_errors == ["tests/test_api.py", "tests/test_np.py"]
    assert store.findings("environment")[0]["status"] == "missing_modules"


def test_missing_dependency_is_reported_not_called_flaky(tmp_path):
    (tmp_path / "conftest.py").write_text("")
    (tmp_path / "app.py").write_text("import definitely_not_installed_pkg\n\ndef f():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import f\n\ndef test_f():\n    assert f() == 1\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    out = tmp_path / "out"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run_analysis(tmp_path, out, local_cfg(3), stability_runs=3, repair_runs=3, progress=lambda *a: None)
    r = json.loads((out / "report.json").read_text())
    assert r["environment"]["missing_modules"] == ["definitely_not_installed_pkg"]
    assert any("could not import definitely_not_installed_pkg" in u for u in r["uncertainties"])
    assert r["stability"]["unstable"] == []


def test_investigation_cap_is_respected_and_reported(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = run_analysis(DEMO, tmp_path, local_cfg(12), stability_runs=12, repair_runs=3,
                           progress=lambda *a: None, max_investigations=1)
    r = json.loads((tmp_path / "report.json").read_text())
    assert len(res.stability.unstable) == 2  # the demo has two planted order-dependent tests
    assert r["investigations"] == {"limit": 1, "investigated": 1, "unstable": 2}
    assert any("not investigated (limit: 1" in u for u in r["uncertainties"])


def test_default_cap_investigates_every_demo_flake(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = run_analysis(DEMO, tmp_path, local_cfg(12), stability_runs=12, repair_runs=3, progress=lambda *a: None)
    polluters = {c.test: c.polluters for c in res.classifications}
    assert polluters == {
        "tests/test_report.py::test_opening_stock_levels": ["tests/test_inventory.py::test_reserve_all_apples"],
        "tests/test_settings.py::test_default_price_format": ["tests/test_settings.py::test_euro_store_uses_eur"],
    }


@pytest.mark.skipif(os.getenv("INHERIT_NETWORK_TESTS") != "1", reason="needs network access to PyPI")
def test_install_dependencies_from_wheels(tmp_path):
    store = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sb = Sandbox(local_cfg(), store)
    res = sb.install_dependencies(["six==1.16.0"])
    assert res.exit_code == 0 and sb.deps_dir is not None
    assert (sb.deps_dir / "six.py").is_file()
    again = sb.install_dependencies(["six==1.16.0"])
    assert again.stdout == "cached"
