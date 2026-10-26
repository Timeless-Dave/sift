"""SQLite storage for runs, calibration samples, trained models and API keys."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

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
    key_hash TEXT PRIMARY KEY,
    prefix TEXT NOT NULL,
    owner TEXT NOT NULL,
    created REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    calls INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_assay ON runs (assay_id, created);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self._conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(api_keys)")}
            if cols and "key_hash" not in cols:  # v0.1 stored plaintext keys; drop them
                c.execute("DROP TABLE api_keys")
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # Runs -----------------------------------------------------------------
    def save_run(self, assay_id: str, tier: str, device: str | None, instrument: str,
                 status: str, result: dict, features: Any, api_key: str | None = None) -> str:
        """api_key is the key's prefix (for usage reports), never the key itself."""
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

    def get_run(self, run_id: str, viewer: str | None = None, internal: bool = False) -> dict | None:
        """Runs made with an API key are visible only to that key; public runs to everyone."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        if not internal and row["api_key"] is not None and row["api_key"] != viewer:
            return None
        return _run_row(row)

    def list_runs(self, assay_id: str | None = None, limit: int = 50, viewer: str | None = None) -> list[dict]:
        q = "SELECT * FROM runs WHERE (api_key IS NULL OR api_key = ?)"
        args: tuple = (viewer,)
        if assay_id:
            q += " AND assay_id=?"
            args += (assay_id,)
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
    def create_key(self, key_hash: str, prefix: str, owner: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO api_keys (key_hash, prefix, owner, created) VALUES (?,?,?,?)",
                      (key_hash, prefix, owner, time.time()))

    def use_key(self, key_hash: str) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE api_keys SET calls = calls + 1 WHERE key_hash=? AND revoked=0", (key_hash,))
        return cur.rowcount == 1

    def revoke_key(self, prefix: str) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE api_keys SET revoked=1 WHERE prefix=?", (prefix,))
        return cur.rowcount > 0


def _run_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("result", "features", "report"):
        if d.get(k):
            d[k] = json.loads(d[k])
    d.pop("api_key", None)
    return d
