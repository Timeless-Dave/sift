"""SQLite storage for runs, calibration samples, trained models and API keys."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    assay_id TEXT NOT NULL,
    created REAL NOT NULL,
    tier TEXT NOT NULL,
    device TEXT,
    instrument TEXT,
    status TEXT NOT NULL,
    result TEXT NOT NULL,
    features TEXT,
    report TEXT,
    truth REAL,
    api_key TEXT
);
CREATE TABLE IF NOT EXISTS calibration_samples (
    id TEXT PRIMARY KEY,
    assay_id TEXT NOT NULL,
    device TEXT NOT NULL,
    created REAL NOT NULL,
    known_value REAL NOT NULL,
    features TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS models (
    assay_id TEXT NOT NULL,
    device TEXT NOT NULL,
    created REAL NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    metrics TEXT NOT NULL,
    PRIMARY KEY (assay_id, device)
);
CREATE TABLE IF NOT EXISTS api_keys (
    key TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    created REAL NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # Runs -----------------------------------------------------------------
    def save_run(self, assay_id: str, tier: str, device: str | None, instrument: str,
                 status: str, result: dict, features: Any, api_key: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute(
                "INSERT INTO runs (id, assay_id, created, tier, device, instrument, status, result, features, api_key)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, assay_id, time.time(), tier, device, instrument, status,
                 json.dumps(result), json.dumps(features), api_key),
            )
        return run_id

    def set_report(self, run_id: str, report: dict) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET report=? WHERE id=?", (json.dumps(report), run_id))

    def set_truth(self, run_id: str, truth: float) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET truth=? WHERE id=?", (truth, run_id))

    def get_run(self, run_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return _run_row(row) if row else None

    def list_runs(self, assay_id: str | None = None, limit: int = 50) -> list[dict]:
        q = "SELECT * FROM runs"
        args: tuple = ()
        if assay_id:
            q += " WHERE assay_id=?"
            args = (assay_id,)
        q += " ORDER BY created DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(q, (*args, limit)).fetchall()
        return [_run_row(r) for r in rows]

    def validation_runs(self, assay_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM runs WHERE assay_id=? AND truth IS NOT NULL AND status='ok'", (assay_id,)
            ).fetchall()
        return [_run_row(r) for r in rows]

    # Calibration ----------------------------------------------------------
    def add_sample(self, assay_id: str, device: str, known_value: float, features: Any, note: str = "") -> str:
        sid = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute(
                "INSERT INTO calibration_samples VALUES (?,?,?,?,?,?,?)",
                (sid, assay_id, device, time.time(), known_value, json.dumps(features), note),
            )
        return sid

    def samples(self, assay_id: str, device: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM calibration_samples WHERE assay_id=? AND device=? ORDER BY created",
                (assay_id, device),
            ).fetchall()
        return [{**dict(r), "features": json.loads(r["features"])} for r in rows]

    def save_model(self, assay_id: str, device: str, kind: str, payload: dict, metrics: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO models VALUES (?,?,?,?,?,?)",
                (assay_id, device, time.time(), kind, json.dumps(payload), json.dumps(metrics)),
            )

    def get_model(self, assay_id: str, device: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM models WHERE assay_id=? AND device=?", (assay_id, device)).fetchone()
        if not row:
            return None
        return {**dict(row), "payload": json.loads(row["payload"]), "metrics": json.loads(row["metrics"])}

    def list_models(self, assay_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT assay_id, device, created, kind, metrics FROM models WHERE assay_id=?",
                             (assay_id,)).fetchall()
        return [{**dict(r), "metrics": json.loads(r["metrics"])} for r in rows]

    # API keys -------------------------------------------------------------
    def create_key(self, owner: str) -> str:
        key = "sift_" + secrets.token_urlsafe(24)
        with self._conn() as c:
            c.execute("INSERT INTO api_keys VALUES (?,?,?,0)", (key, owner, time.time()))
        return key

    def use_key(self, key: str) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE api_keys SET calls = calls + 1 WHERE key=?", (key,))
        return cur.rowcount == 1


def _run_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("result", "features", "report"):
        if d.get(k):
            d[k] = json.loads(d[k])
    d.pop("api_key", None)
    return d
