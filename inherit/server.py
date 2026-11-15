"""Web UI: start an analysis, stream its progress, and view the outputs.

One analysis runs at a time, to keep sandbox load and model credits predictable.
Repositories come from the bundled demo or an uploaded zip. Arbitrary server paths are
accepted only when INHERIT_ALLOW_LOCAL_PATHS=1 (for local use, never a public deployment).

INHERIT_PUBLIC_MODE=1 is for hosts without Docker: only the bundled demos (our own, trusted
code) may be analyzed, uploads are refused, and runs per hour are capped to protect credits.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import Config
from .demos import SAMPLES_DIR, load_demos
from .pipeline import run_analysis

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.getenv("INHERIT_RUNS_DIR", ROOT / "runs"))
STATIC = Path(__file__).resolve().parent / "static"
DEMOS = load_demos()
DEFAULT_DEMO = "shop"
MAX_ZIP_BYTES = 10 * 1024 * 1024
MAX_UNZIPPED_BYTES = 30 * 1024 * 1024
MAX_FILES = 2000
PUBLIC_MODE = os.getenv("INHERIT_PUBLIC_MODE") == "1"
MAX_RUNS_PER_HOUR = int(os.getenv("INHERIT_MAX_RUNS_PER_HOUR", "6" if PUBLIC_MODE else "0"))  # 0 = no cap


@dataclass
class Job:
    id: str
    source: str
    out: Path
    events: list[dict] = field(default_factory=list)
    status: str = "running"  # running | done | error
    error: str = ""
    started: float = field(default_factory=time.time)

    def emit(self, stage: str, message: str) -> None:
        self.events.append({"stage": stage, "message": message, "t": round(time.time() - self.started, 1)})


app = FastAPI(title="Inherit")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
JOBS: dict[str, Job] = {}
_busy = threading.Lock()
_recent_starts: list[float] = []
# pre-computed reports, one per demo, so visitors can see results instantly
for _id in DEMOS:
    if (SAMPLES_DIR / _id / "report.json").is_file():
        JOBS[f"sample-{_id}"] = Job(f"sample-{_id}", "demo", SAMPLES_DIR / _id, status="done")
if f"sample-{DEFAULT_DEMO}" in JOBS:
    JOBS["sample"] = JOBS[f"sample-{DEFAULT_DEMO}"]


# --- repository intake -----------------------------------------------------------
def safe_extract(data: bytes, dest: Path) -> Path:
    """Extract a zip without path traversal or zip bombs; return the repo root inside it."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "not a valid zip file") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise HTTPException(400, f"zip has more than {MAX_FILES} files")
    if sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES:
        raise HTTPException(400, "zip is too large when extracted")
    dest.mkdir(parents=True)
    for info in infos:
        rel = PurePosixPath(info.filename.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts:
            raise HTTPException(400, f"unsafe path in zip: {info.filename}")
        target = dest.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
    entries = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else dest


def _prune(keep: int = 20) -> None:
    """Forget old finished jobs and delete their files, so a long-running host doesn't fill its disk."""
    finished = sorted((j for j in JOBS.values() if j.id != "sample" and j.status != "running"),
                      key=lambda j: j.started)
    for j in finished[:-keep] if len(finished) > keep else []:
        JOBS.pop(j.id, None)
        shutil.rmtree(j.out.parent, ignore_errors=True)


def _run(job: Job, repo: Path, cfg: Config, runs: int) -> None:
    try:
        run_analysis(repo, job.out, cfg, stability_runs=runs, progress=job.emit)
        job.status = "done"
    except Exception as exc:  # surface any failure to the UI instead of a silent hang
        job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        job.emit("error", job.error)
    finally:
        _busy.release()


# --- routes ------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def config() -> dict:
    cfg = Config.from_env()
    return {
        "llm_backend": cfg.llm_backend, "sandbox_backend": cfg.sandbox_backend,
        "reasoner": cfg.model_reasoner or "mock", "worker": cfg.model_worker or "mock",
        "allow_local_paths": os.getenv("INHERIT_ALLOW_LOCAL_PATHS") == "1",
        "busy": _busy.locked(),
        "sample": "sample" in JOBS,
        "public_mode": PUBLIC_MODE,
        "demos": [
            {"id": d["id"], "title": d["title"], "summary": d["summary"], "shows": d.get("shows", []),
             "needs_network": d.get("needs_network", False), "sample": f"sample-{d['id']}" in JOBS}
            for d in DEMOS.values()
        ],
        "default_demo": DEFAULT_DEMO,
    }


@app.get("/api/jobs/{job_id}/report")
def job_report(job_id: str) -> JSONResponse:
    path = _job(job_id).out / "report.json"
    if not path.is_file():
        raise HTTPException(404, "report not ready")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@app.post("/api/analyze")
async def analyze(
    source: str = Form("demo"),
    demo: str = Form(DEFAULT_DEMO),
    path: str = Form(""),
    runs: int = Form(20),
    upload: UploadFile | None = File(None),
) -> dict:
    if not 3 <= runs <= (20 if PUBLIC_MODE else 50):
        raise HTTPException(400, f"runs must be between 3 and {20 if PUBLIC_MODE else 50}")
    if PUBLIC_MODE and source != "demo":
        raise HTTPException(403, "this public site analyzes only the bundled demo projects; "
                                 "run Inherit yourself (see README) to analyze your own code")
    now = time.time()
    _recent_starts[:] = [t for t in _recent_starts if now - t < 3600]
    if MAX_RUNS_PER_HOUR and len(_recent_starts) >= MAX_RUNS_PER_HOUR:
        raise HTTPException(429, "hourly run limit reached for this demo; the sample report is available meanwhile")
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "an analysis is already running; try again when it finishes")
    try:
        _prune()
        job_id = uuid.uuid4().hex[:10]
        work = RUNS_DIR / job_id
        if source == "demo":
            if demo not in DEMOS:
                raise HTTPException(400, f"unknown demo: {demo}")
            repo = DEMOS[demo]["path"]
        elif source == "zip":
            if upload is None:
                raise HTTPException(400, "no zip uploaded")
            data = await upload.read(MAX_ZIP_BYTES + 1)
            if len(data) > MAX_ZIP_BYTES:
                raise HTTPException(400, "zip upload is larger than 10 MB")
            repo = safe_extract(data, work / "repo")
        elif source == "path" and os.getenv("INHERIT_ALLOW_LOCAL_PATHS") == "1":
            repo = Path(path).expanduser().resolve()
            if not repo.is_dir():
                raise HTTPException(400, "path is not a directory")
        else:
            raise HTTPException(400, "unknown or disabled source")
        job = Job(job_id, source if source != "path" else str(repo), work / "out")
        JOBS[job_id] = job
        _recent_starts.append(now)
        job.emit("setup", f"analyzing the '{DEMOS[demo]['title']}' demo" if source == "demo" else f"analyzing {source}")
        threading.Thread(target=_run, args=(job, repo, Config.from_env(), runs), daemon=True).start()
        return {"job": job_id}
    except BaseException:
        _busy.release()
        raise


def _job(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    j = _job(job_id)
    return {"job": j.id, "status": j.status, "error": j.error, "events": j.events}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = _job(job_id)

    async def stream():
        sent = 0
        while True:
            while sent < len(job.events):
                yield f"data: {json.dumps(job.events[sent])}\n\n"
                sent += 1
            if job.status != "running":
                yield f"event: end\ndata: {json.dumps({'status': job.status, 'error': job.error})}\n\n"
                return
            await asyncio.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/jobs/{job_id}/{file_path:path}")
def job_file(job_id: str, file_path: str) -> FileResponse:
    out = _job(job_id).out.resolve()
    target = (out / file_path).resolve()
    if out not in target.parents or not target.is_file():
        raise HTTPException(404, "not found")
    media = "text/html" if target.suffix == ".html" else "text/plain; charset=utf-8"
    if target.suffix == ".db":
        media = "application/octet-stream"
    return FileResponse(target, media_type=media)
