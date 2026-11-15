import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from inherit import server
from inherit.server import safe_extract


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_safe_extract_finds_single_root(tmp_path):
    root = safe_extract(make_zip({"proj/a.py": "x = 1", "proj/tests/test_a.py": ""}), tmp_path / "x")
    assert root.name == "proj" and (root / "a.py").is_file()


@pytest.mark.parametrize("name", ["../evil.py", "/abs.py", "a/../../evil.py"])
def test_safe_extract_rejects_traversal(tmp_path, name):
    with pytest.raises(HTTPException):
        safe_extract(make_zip({name: "x"}), tmp_path / "x")


def test_safe_extract_rejects_non_zip(tmp_path):
    with pytest.raises(HTTPException):
        safe_extract(b"not a zip", tmp_path / "x")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    monkeypatch.setenv("SANDBOX_BACKEND", "local")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("INHERIT_ALLOW_LOCAL_PATHS", raising=False)
    return TestClient(server.app)


def test_index_and_config(client):
    assert "Know what you can trust" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    c = client.get("/api/config").json()
    assert c["llm_backend"] == "mock" and c["allow_local_paths"] is False


def test_local_paths_disabled_by_default(client):
    r = client.post("/api/analyze", data={"source": "path", "path": "C:/"})
    assert r.status_code == 400
    assert client.get("/api/config").json()["busy"] is False  # lock released after rejection


def test_public_mode_allows_only_demo_and_caps_runs(client, monkeypatch):
    monkeypatch.setattr(server, "PUBLIC_MODE", True)
    monkeypatch.setattr(server, "MAX_RUNS_PER_HOUR", 1)
    monkeypatch.setattr(server, "_recent_starts", [time.time()])
    zip_bytes = make_zip({"a.py": "x = 1"})
    r = client.post("/api/analyze", data={"source": "zip"}, files={"upload": ("a.zip", zip_bytes)})
    assert r.status_code == 403
    assert client.post("/api/analyze", data={"source": "demo", "runs": 30}).status_code == 400
    assert client.post("/api/analyze", data={"source": "demo", "runs": 5}).status_code == 429
    assert client.get("/api/config").json()["busy"] is False


def test_runs_bounds(client):
    assert client.post("/api/analyze", data={"source": "demo", "runs": 1000}).status_code == 400


def test_file_route_blocks_traversal(client, tmp_path):
    job = server.Job("abc", "demo", tmp_path / "out")
    (tmp_path / "out").mkdir()
    (tmp_path / "secret.txt").write_text("no")
    server.JOBS["abc"] = job
    assert client.get("/jobs/abc/../secret.txt").status_code == 404
    assert client.get("/jobs/abc/%2e%2e/secret.txt").status_code == 404


def test_demo_analysis_end_to_end(client):
    r = client.post("/api/analyze", data={"source": "demo", "runs": 4})
    assert r.status_code == 200
    job = r.json()["job"]
    assert client.post("/api/analyze", data={"source": "demo"}).status_code == 409  # one at a time
    deadline = time.time() + 300
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job}").json()
        if status["status"] != "running":
            break
        time.sleep(1)
    assert status["status"] == "done", status
    stages = {e["stage"] for e in status["events"]}
    assert {"discover", "stability", "characterize", "docs", "done"} <= stages
    body = client.get(f"/api/jobs/{job}/events").text
    assert "event: end" in body
    assert "Inherit reliability report" in client.get(f"/jobs/{job}/report.html").text
    report = client.get(f"/api/jobs/{job}/report").json()
    assert report["repo"] == "demo_repo"  # no host path leaked
    assert len(report["stability"]["run_matrix"]) == 4
