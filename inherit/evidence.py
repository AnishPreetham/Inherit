"""SQLite evidence store. Every fact the report states must trace back to a row here."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    command TEXT NOT NULL,
    seed INTEGER,
    test_order TEXT,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    duration REAL,
    meta TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    evidence_ids TEXT
);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('observed', 'inferred')),
    subject TEXT,
    evidence_ids TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    model TEXT,
    task TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency REAL,
    ok INTEGER NOT NULL,
    error TEXT
);
"""


def evidence_label(row_id: int) -> str:
    """Stable human-readable evidence ID, e.g. E-0007."""
    return f"E-{row_id:04d}"


def parse_evidence_label(label: str) -> int:
    if not label.startswith("E-") or not label[2:].isdigit():
        raise ValueError(f"bad evidence id: {label!r}")
    return int(label[2:])


class EvidenceStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # --- executions ---------------------------------------------------
    def record_execution(
        self,
        kind: str,
        command: str,
        exit_code: int | None,
        stdout: str = "",
        stderr: str = "",
        duration: float = 0.0,
        seed: int | None = None,
        test_order: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO executions (kind, command, seed, test_order, exit_code,"
                " stdout, stderr, duration, meta) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    kind,
                    command,
                    seed,
                    json.dumps(test_order) if test_order is not None else None,
                    exit_code,
                    stdout,
                    stderr,
                    duration,
                    json.dumps(meta) if meta else None,
                ),
            )
            self._conn.commit()
            return evidence_label(cur.lastrowid)

    def get_execution(self, label: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM executions WHERE id = ?", (parse_evidence_label(label),)
            ).fetchone()
        return dict(row) if row else None

    def executions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM executions ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def execution_meta(self, label: str) -> dict[str, Any]:
        row = self.get_execution(label)
        return json.loads(row["meta"]) if row and row["meta"] else {}

    def execution_exists(self, label: str) -> bool:
        try:
            return self.get_execution(label) is not None
        except ValueError:
            return False

    # --- findings and claims -----------------------------------------
    def add_finding(
        self,
        type_: str,
        subject: str,
        status: str,
        detail: str = "",
        evidence_ids: list[str] | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO findings (type, subject, status, detail, evidence_ids)"
                " VALUES (?,?,?,?,?)",
                (type_, subject, status, detail, json.dumps(evidence_ids or [])),
            )
            self._conn.commit()
            return cur.lastrowid

    def findings(self, type_: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM findings", ()
        if type_:
            sql, args = sql + " WHERE type = ?", (type_,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [dict(r) for r in rows]

    def add_claim(
        self,
        text: str,
        kind: str,
        subject: str = "",
        evidence_ids: list[str] | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO claims (text, kind, subject, evidence_ids) VALUES (?,?,?,?)",
                (text, kind, subject, json.dumps(evidence_ids or [])),
            )
            self._conn.commit()
            return cur.lastrowid

    def claims(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM claims ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # --- llm usage ----------------------------------------------------
    def record_llm_call(
        self,
        role: str,
        model: str,
        task: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency: float,
        ok: bool,
        error: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO llm_calls (role, model, task, prompt_tokens,"
                " completion_tokens, latency, ok, error) VALUES (?,?,?,?,?,?,?,?)",
                (role, model, task, prompt_tokens, completion_tokens, latency, int(ok), error),
            )
            self._conn.commit()

    def llm_usage(self) -> list[dict[str, Any]]:
        """Per-model aggregate used by the report's model-usage section."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, model, COUNT(*) AS calls, SUM(ok) AS ok_calls,"
                " SUM(prompt_tokens) AS prompt_tokens,"
                " SUM(completion_tokens) AS completion_tokens,"
                " AVG(latency) AS avg_latency FROM llm_calls GROUP BY role, model"
            ).fetchall()
        return [dict(r) for r in rows]
