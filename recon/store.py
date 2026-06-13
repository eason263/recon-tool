"""SQLite persistence layer for reconciliation runs and breaks."""
from __future__ import annotations
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .recondiff import ReconResult


def _db_path() -> Path:
    p = Path(os.environ.get("RECON_DB", Path.home() / ".recon" / "recon.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name    TEXT NOT NULL,
                source      TEXT NOT NULL,
                target      TEXT NOT NULL,
                ran_at      TEXT NOT NULL,
                status      TEXT NOT NULL,
                total_a     INTEGER,
                total_b     INTEGER,
                matched     INTEGER,
                mismatches  INTEGER,
                only_in_a   INTEGER,
                only_in_b   INTEGER
            );
            CREATE TABLE IF NOT EXISTS breaks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      INTEGER NOT NULL REFERENCES runs(id),
                break_type  TEXT NOT NULL,
                key_json    TEXT,
                column      TEXT,
                a_value     TEXT,
                b_value     TEXT,
                status      TEXT NOT NULL DEFAULT 'open',
                assigned_to TEXT,
                note        TEXT,
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                api_key       TEXT UNIQUE NOT NULL
            );
        """)


@dataclass
class RunSummary:
    id: int
    job_name: str
    source: str
    target: str
    ran_at: str
    status: str
    total_a: int
    total_b: int
    matched: int
    mismatches: int
    only_in_a: int
    only_in_b: int


@dataclass
class BreakRecord:
    id: int
    run_id: int
    break_type: str
    key_json: str
    column: str | None
    a_value: str | None
    b_value: str | None
    status: str
    assigned_to: str | None
    note: str | None
    resolved_at: str | None

    @property
    def key_display(self) -> str:
        try:
            return " / ".join(json.loads(self.key_json))
        except Exception:
            return self.key_json or ""


def save_run(result: ReconResult, job_name: str) -> int:
    """Persist a ReconResult and its breaks; return the new run_id."""
    init_db()
    status = "MATCH" if result.reconciled else "DIFF"
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO runs
               (job_name, source, target, ran_at, status,
                total_a, total_b, matched, mismatches, only_in_a, only_in_b)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_name, result.a_name, result.b_name,
                datetime.now().isoformat(timespec="seconds"),
                status,
                result.total_a, result.total_b, result.matched,
                len(result.mismatches), len(result.only_in_a), len(result.only_in_b),
            ),
        )
        run_id = cur.lastrowid
        for m in result.mismatches:
            conn.execute(
                """INSERT INTO breaks (run_id, break_type, key_json, column, a_value, b_value)
                   VALUES (?, 'field_mismatch', ?, ?, ?, ?)""",
                (run_id, json.dumps(list(m.key)), m.column, m.a_value, m.b_value),
            )
        for key in result.only_in_a:
            conn.execute(
                "INSERT INTO breaks (run_id, break_type, key_json) VALUES (?, 'only_in_a', ?)",
                (run_id, json.dumps(list(key))),
            )
        for key in result.only_in_b:
            conn.execute(
                "INSERT INTO breaks (run_id, break_type, key_json) VALUES (?, 'only_in_b', ?)",
                (run_id, json.dumps(list(key))),
            )
    return run_id


def list_runs(limit: int = 100, job_name: str | None = None) -> list[RunSummary]:
    init_db()
    with _connect() as conn:
        if job_name:
            rows = conn.execute(
                "SELECT * FROM runs WHERE job_name = ? ORDER BY id DESC LIMIT ?",
                (job_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [RunSummary(**dict(r)) for r in rows]


def get_run(run_id: int) -> tuple[RunSummary, list[BreakRecord]]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        breaks = conn.execute(
            "SELECT * FROM breaks WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return RunSummary(**dict(row)), [BreakRecord(**dict(b)) for b in breaks]


def update_break(
    break_id: int,
    status: str,
    assigned_to: str | None = None,
    note: str | None = None,
) -> None:
    init_db()
    resolved_at = datetime.now().isoformat(timespec="seconds") if status != "open" else None
    with _connect() as conn:
        conn.execute(
            """UPDATE breaks
               SET status = ?, assigned_to = ?, note = ?, resolved_at = ?
               WHERE id = ?""",
            (status, assigned_to, note, resolved_at, break_id),
        )
