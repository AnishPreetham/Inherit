import warnings

import pytest
from pydantic import BaseModel

from inherit.config import Config
from inherit.evidence import EvidenceStore, parse_evidence_label
from inherit.llm import LLMClient, LLMError, extract_json
from inherit.sandbox import Sandbox


def make_cfg(**over) -> Config:
    base = dict(
        api_key="", base_url="", model_reasoner="", model_worker="",
        stability_runs=20, sandbox_image="inherit-sandbox", sandbox_timeout=20,
        sandbox_backend="local", llm_backend="mock",
    )
    base.update(over)
    return Config(**base)


# --- evidence store ---------------------------------------------------
def test_execution_roundtrip_and_ids():
    s = EvidenceStore()
    eid = s.record_execution("probe", "cmd", 0, stdout="hi", seed=7, test_order=["a", "b"])
    assert eid == "E-0001"
    row = s.get_execution(eid)
    assert row["stdout"] == "hi" and row["seed"] == 7
    assert s.execution_exists(eid) and not s.execution_exists("E-9999")
    assert not s.execution_exists("garbage")
    assert parse_evidence_label(eid) == 1


def test_claim_kind_is_constrained():
    s = EvidenceStore()
    s.add_claim("returns 2", "observed", "f", ["E-0001"])
    with pytest.raises(Exception):
        s.add_claim("x", "certain")


# --- llm client (mock) -------------------------------------------------
class Out(BaseModel):
    n: int


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"n": 1}\n```') == '{"n": 1}'
    assert extract_json('Sure! {"n": 2} hope that helps') == '{"n": 2}'


def test_complete_json_repairs_once_and_logs_usage():
    s = EvidenceStore()
    replies = iter(["not json", '{"n": 5}'])
    llm = LLMClient(make_cfg(), s, mock_handler=lambda *_: next(replies))
    assert llm.complete_json("worker", "sys", "user", Out, task="t").n == 5
    usage = s.llm_usage()
    assert usage[0]["calls"] == 2 and usage[0]["role"] == "worker"


def test_complete_json_fails_after_repair():
    s = EvidenceStore()
    llm = LLMClient(make_cfg(), s, mock_handler=lambda *_: "nope")
    with pytest.raises(LLMError):
        llm.complete_json("reasoner", "s", "u", Out, task="t")


def test_failed_calls_are_retried_and_logged():
    s = EvidenceStore()
    calls = {"n": 0}

    def flaky(*_):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    llm = LLMClient(make_cfg(), s, mock_handler=flaky, backoff=0)
    assert llm.complete("worker", "s", "u") == "ok"
    assert s.llm_usage()[0]["ok_calls"] == 1 and s.llm_usage()[0]["calls"] == 3


# --- sandbox (local backend) -------------------------------------------
@pytest.fixture
def tiny_repo(tmp_path):
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef boom():\n    raise ValueError('bad')\n"
    )
    return tmp_path


def test_sandbox_run_records_evidence(tiny_repo):
    s = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sb = Sandbox(make_cfg(), s)
    res = sb.run(tiny_repo, ["python", "-c", "print('hello')"], kind="smoke")
    assert res.exit_code == 0 and "hello" in res.stdout
    assert s.get_execution(res.evidence_id)["kind"] == "smoke"


def test_sandbox_timeout(tiny_repo):
    s = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sb = Sandbox(make_cfg(), s)
    res = sb.run(tiny_repo, ["python", "-c", "import time; time.sleep(5)"], kind="smoke", timeout=1)
    assert res.timed_out and res.exit_code == -1


def test_probe_returns_and_raises(tiny_repo):
    s = EvidenceStore()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sb = Sandbox(make_cfg(), s)
    eid, ok = sb.probe(tiny_repo, "calc", "add", [2, 3])
    assert ok["status"] == "returned" and ok["repr"] == "5"
    _, bad = sb.probe(tiny_repo, "calc", "boom")
    assert bad["status"] == "raised" and bad["exc_type"] == "ValueError"


def test_docker_backend_requires_docker(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    from inherit.sandbox import SandboxError

    with pytest.raises(SandboxError):
        Sandbox(make_cfg(sandbox_backend="docker"), EvidenceStore())
