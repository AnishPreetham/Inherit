"""Run untrusted repository code in isolation and record each run as evidence.

Backends:
  * "docker": container with no network, resource limits and a non-root user (use this).
  * "local":  plain subprocess in a temp copy of the repo. NOT isolated; development only.

Third-party dependencies are installed once per analysis by `install_dependencies`, the only
step that gets network access. It accepts prebuilt wheels only, so no package build scripts
run, and writes into a separate directory that later (offline) runs mount read-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .evidence import EvidenceStore

MAX_OUTPUT = 20_000
IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".venv", "venv", ".pytest_cache", "node_modules")
PROBE_PREFIX = "INHERIT_PROBE "
PROBE_LOCAL = Path(__file__).resolve().parent.parent / "sandbox" / "probe.py"
PROBE_IN_IMAGE = "/opt/inherit/probe.py"
INSTALL_TIMEOUT = 600
# keep the sandbox's own test tooling at its installed versions even if a repo pins others
TOOLING = ("pytest", "pytest-randomly", "pluggy", "iniconfig", "packaging")


@dataclass
class RunResult:
    evidence_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False


class SandboxError(RuntimeError):
    pass


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n...[truncated]"


def _execute(
    cmd: list[str], timeout: int, env: dict | None = None, cwd: Path | None = None,
) -> tuple[int, str, str, bool]:
    """Run cmd; return (exit_code, stdout, stderr, timed_out). A timeout gives exit code -1."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace", env=env, cwd=cwd)
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        def text(b):
            return b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")
        return -1, text(exc.stdout), text(exc.stderr) + f"\n[timeout after {timeout}s]", True


def _installed_pins(names: tuple[str, ...]) -> list[str]:
    from importlib import metadata

    pins = []
    for name in names:
        try:
            pins.append(f"{name}=={metadata.version(name)}")
        except metadata.PackageNotFoundError:
            pass
    return pins


class Sandbox:
    def __init__(self, cfg: Config, store: EvidenceStore) -> None:
        self.cfg = cfg
        self.store = store
        self.deps_dir: Path | None = None  # set by install_dependencies
        if cfg.sandbox_backend == "local":
            warnings.warn(
                "SANDBOX_BACKEND=local runs repository code WITHOUT isolation. "
                "Use only on code you trust, and never for the final demo.",
                stacklevel=2,
            )
        elif cfg.sandbox_backend == "docker":
            if shutil.which("docker") is None:
                raise SandboxError("docker not found. Install Docker or set SANDBOX_BACKEND=local for development.")
        else:
            raise SandboxError(f"unknown sandbox backend: {cfg.sandbox_backend}")

    # ------------------------------------------------------------------
    def run(
        self,
        repo: str | Path,
        argv: list[str],
        kind: str,
        timeout: int | None = None,
        seed: int | None = None,
        test_order: list[str] | None = None,
        meta: dict | None = None,
        extra_files: dict[str, str] | None = None,
    ) -> RunResult:
        """Run argv against a fresh copy of repo. `python` as argv[0] means the sandbox interpreter.

        `extra_files` maps repo-relative paths to contents written into the copy (never the original).
        """
        timeout = timeout or self.cfg.sandbox_timeout
        repo = Path(repo).resolve()
        if not repo.is_dir():
            raise SandboxError(f"repo path is not a directory: {repo}")
        with tempfile.TemporaryDirectory(prefix="inherit-") as tmp:
            work = Path(tmp) / "work"
            shutil.copytree(repo, work, ignore=IGNORE)
            for rel, content in (extra_files or {}).items():
                target = work / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            cmd = self._build_command(work, argv)
            start = time.monotonic()
            local = self.cfg.sandbox_backend == "local"
            code, out, err, timed_out = _execute(cmd, timeout, self._local_env(work), work if local else None)
            duration = time.monotonic() - start
        out, err = _clip(out), _clip(err)
        eid = self.store.record_execution(
            kind=kind,
            command=" ".join(argv),
            exit_code=code,
            stdout=out,
            stderr=err,
            duration=duration,
            seed=seed,
            test_order=test_order,
            meta={**(meta or {}), "backend": self.cfg.sandbox_backend, "timed_out": timed_out},
        )
        return RunResult(eid, code, out, err, duration, timed_out)

    def _local_env(self, work: Path) -> dict | None:
        """Environment for the local backend: repo root, src/ layout and installed deps on the path."""
        if self.cfg.sandbox_backend != "local":
            return None
        paths = [str(work), str(work / "src")] + ([str(self.deps_dir)] if self.deps_dir else [])
        return {**os.environ, "PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}

    def _build_command(self, work: Path, argv: list[str]) -> list[str]:
        if self.cfg.sandbox_backend == "local":
            return [sys.executable if a == "python" and i == 0 else a for i, a in enumerate(argv)]
        pythonpath = "/work:/work/src" + (":/deps" if self.deps_dir else "")
        deps_mount = ["-v", f"{self.deps_dir}:/deps:ro"] if self.deps_dir else []
        return [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", "512m", "--cpus", "1", "--pids-limit", "256",
            "-v", f"{work}:/work",
            *deps_mount,
            "-e", f"PYTHONPATH={pythonpath}",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-w", "/work",
            self.cfg.sandbox_image,
            *argv,
        ]

    # ------------------------------------------------------------------
    def install_dependencies(self, requirements: list[str]) -> RunResult:
        """Install third-party requirements into a dependency directory, with network, wheels only.

        On success later runs see the packages (read-only). Results are cached by requirement
        list, so re-analyzing the same project skips the download.
        """
        spec = "\n".join(requirements) + "\n"
        key = hashlib.sha256(f"{self.cfg.sandbox_backend}\n{spec}".encode()).hexdigest()[:16]
        cache = Path(tempfile.gettempdir()) / "inherit-deps" / key
        done_marker = cache / ".inherit-complete"
        if done_marker.is_file():
            self.deps_dir = cache / "site"
            eid = self.store.record_execution(
                "install_dependencies", "reuse cached dependencies", 0,
                stdout=f"reused {len(requirements)} requirement(s) installed earlier",
                meta={"requirements": requirements, "cached": True, "backend": self.cfg.sandbox_backend},
            )
            return RunResult(eid, 0, "cached", "", 0.0)

        shutil.rmtree(cache, ignore_errors=True)
        (cache / "req").mkdir(parents=True)
        (cache / "site").mkdir()
        (cache / "req" / "requirements.txt").write_text(spec, encoding="utf-8")
        if self.cfg.sandbox_backend == "docker":
            os.chmod(cache / "site", 0o777)  # the sandbox writes as a non-root user
            pip = ("python -m pip freeze | grep -iE '^(" + "|".join(TOOLING) + ")==' > /tmp/c.txt; "
                   "python -m pip install --no-cache-dir --disable-pip-version-check --only-binary=:all: "
                   "--target /deps -c /tmp/c.txt -r /req/requirements.txt")
            cmd = [
                "docker", "run", "--rm",
                "--network", "bridge",  # the one sandbox step with network access
                "--memory", "1g", "--cpus", "2", "--pids-limit", "512",
                "-v", f"{cache / 'req'}:/req:ro",
                "-v", f"{cache / 'site'}:/deps",
                self.cfg.sandbox_image, "sh", "-c", pip,
            ]
        else:
            constraints = cache / "req" / "constraints.txt"
            constraints.write_text("\n".join(_installed_pins(TOOLING)) + "\n", encoding="utf-8")
            cmd = [
                sys.executable, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
                "--only-binary=:all:", "--target", str(cache / "site"),
                "-c", str(constraints), "-r", str(cache / "req" / "requirements.txt"),
            ]
        start = time.monotonic()
        code, out, err, timed_out = _execute(cmd, INSTALL_TIMEOUT)
        duration = time.monotonic() - start
        if code == 0:
            done_marker.write_text("ok", encoding="utf-8")
            self.deps_dir = cache / "site"
        eid = self.store.record_execution(
            "install_dependencies", "pip install --only-binary=:all: " + " ".join(requirements), code,
            stdout=_clip(out), stderr=_clip(err), duration=duration,
            meta={"requirements": requirements, "cached": False, "backend": self.cfg.sandbox_backend,
                  "timed_out": timed_out},
        )
        return RunResult(eid, code, out, err, duration, timed_out)

    # ------------------------------------------------------------------
    def probe(
        self,
        repo: str | Path,
        module: str,
        function: str,
        args: list | None = None,
        kwargs: dict | None = None,
        kind: str = "probe",
    ) -> tuple[str, dict | None]:
        """Call one function in the sandbox. Returns (evidence_id, parsed result or None)."""
        probe_path = PROBE_IN_IMAGE if self.cfg.sandbox_backend == "docker" else str(PROBE_LOCAL)
        argv = ["python", probe_path, module, function, json.dumps(args or []), json.dumps(kwargs or {})]
        res = self.run(repo, argv, kind=kind, meta={"module": module, "function": function})
        parsed = None
        for line in res.stdout.splitlines():
            if line.startswith(PROBE_PREFIX):
                parsed = json.loads(line[len(PROBE_PREFIX):])
        return res.evidence_id, parsed

    def probe_batch(
        self,
        repo: str | Path,
        module: str,
        function: str,
        cases: list[dict],
        kind: str = "probe_batch",
    ) -> tuple[str, list[dict], bool]:
        """Call one function once per case in a single process.

        Returns (evidence_id, results indexed like cases, timed_out). Missing results
        (e.g. after a timeout or crash) come back as None.
        """
        probe_path = PROBE_IN_IMAGE if self.cfg.sandbox_backend == "docker" else str(PROBE_LOCAL)
        argv = ["python", probe_path, module, function, "--batch", json.dumps(cases)]
        res = self.run(repo, argv, kind=kind, meta={"module": module, "function": function, "cases": len(cases)})
        results: list[dict | None] = [None] * len(cases)
        for line in res.stdout.splitlines():
            if line.startswith(PROBE_PREFIX):
                item = json.loads(line[len(PROBE_PREFIX):])
                if 0 <= item.get("index", -1) < len(cases):
                    results[item["index"]] = item
        return res.evidence_id, results, res.timed_out
