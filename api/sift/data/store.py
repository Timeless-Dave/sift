"""SQLite storage for runs, calibration samples, trained models, API keys and instant scans."""

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
    note TEXT,
    owner TEXT NOT NULL DEFAULT '',
    run_id TEXT
);
CREATE TABLE IF NOT EXISTS models (
    assay_id TEXT NOT NULL,
    device TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    metrics TEXT NOT NULL,
    PRIMARY KEY (assay_id, device, owner)
);
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash TEXT PRIMARY KEY,
    prefix TEXT NOT NULL,
    owner TEXT NOT NULL,
    created REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    calls INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    food TEXT NOT NULL,
    device TEXT,
    owner TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL,
    label TEXT,
    target TEXT,
    value REAL,
    barcode TEXT,
    created REAL NOT NULL,
    features TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS runs_assay ON runs (assay_id, created);
CREATE INDEX IF NOT EXISTS scans_food ON scans (food, created);
CREATE INDEX IF NOT EXISTS scans_library ON scans (food, device, owner);
CREATE INDEX IF NOT EXISTS samples_scope ON calibration_samples (assay_id, device, owner);
CREATE UNIQUE INDEX IF NOT EXISTS samples_run ON calibration_samples (run_id) WHERE run_id IS NOT NULL;
"""

# Calibration samples and models belong to an owner: the API key prefix that made them, or ''
# for the public pool. One owner's calibration is never applied to another owner's runs.
PUBLIC = ""


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self._conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(api_keys)")}
            if cols and "key_hash" not in cols:  # v0.1 stored plaintext keys; drop them
                c.execute("DROP TABLE api_keys")
            _migrate_owner(c)
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

    def run_owner(self, run_id: str) -> str | None:
        """The key prefix a run was made with, or None for a public run."""
        with self._conn() as c:
            row = c.execute("SELECT api_key FROM runs WHERE id=?", (run_id,)).fetchone()
        return row["api_key"] if row else None

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

    def validation_runs(self, assay_id: str, viewer: str | None = None) -> list[dict]:
        """Validation runs made by `viewer` (a key prefix), or public ones when viewer is None."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM runs WHERE assay_id=? AND truth IS NOT NULL AND status='ok' AND api_key IS ?",
                (assay_id, viewer),
            ).fetchall()
        return [_run_row(r) for r in rows]

    # Calibration ----------------------------------------------------------
    def add_sample(self, assay_id: str, device: str, known_value: float, features: Any, note: str = "",
                   owner: str = PUBLIC, run_id: str | None = None) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute(
                "INSERT INTO calibration_samples (id, assay_id, device, created, known_value, features, note, owner,"
                " run_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, assay_id, device, time.time(), known_value, json.dumps(features), note, owner, run_id),
            )
        return sid

    def is_calibration_run(self, run_id: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM calibration_samples WHERE run_id=?", (run_id,)).fetchone() is not None

    def samples(self, assay_id: str, device: str, owner: str = PUBLIC) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM calibration_samples WHERE assay_id=? AND device=? AND owner=? ORDER BY created",
                (assay_id, device, owner),
            ).fetchall()
        return [{**dict(r), "features": json.loads(r["features"])} for r in rows]

    def count_samples(self, assay_id: str, device: str, owner: str = PUBLIC) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM calibration_samples WHERE assay_id=? AND device=? AND owner=?",
                (assay_id, device, owner),
            ).fetchone()
        return int(row["n"])

    def save_model(self, assay_id: str, device: str, kind: str, payload: dict, metrics: dict,
                   owner: str = PUBLIC) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO models (assay_id, device, owner, created, kind, payload, metrics)"
                " VALUES (?,?,?,?,?,?,?)",
                (assay_id, device, owner, time.time(), kind, json.dumps(payload), json.dumps(metrics)),
            )

    def get_model(self, assay_id: str, device: str, owner: str = PUBLIC) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM models WHERE assay_id=? AND device=? AND owner=?",
                            (assay_id, device, owner)).fetchone()
        if not row:
            return None
        return {**dict(row), "payload": json.loads(row["payload"]), "metrics": json.loads(row["metrics"])}

    def list_models(self, assay_id: str, owner: str = PUBLIC) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT assay_id, device, created, kind, metrics FROM models WHERE assay_id=? AND owner=?",
                             (assay_id, owner)).fetchall()
        return [{**dict(r), "metrics": json.loads(r["metrics"])} for r in rows]

    # Instant scans --------------------------------------------------------
    def save_scan(self, scan_id: str, food: str, device: str | None, owner: str, mode: str, label: str | None,
                  target: str | None, value: float | None, barcode: str | None, features: Any,
                  result: dict) -> str:
        """Store a scan. Rejected scans are kept for audit but never join the reference library."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO scans (id, food, device, owner, mode, label, target, value, barcode, created,"
                " features, result) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (scan_id, food, device, owner, mode, label, target, value, barcode, time.time(),
                 json.dumps(features), json.dumps(result)),
            )
        return scan_id

    def get_scan(self, scan_id: str, viewer: str | None = None) -> dict | None:
        """A key's scans are visible only to that key; public scans to everyone."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not row:
            return None
        if row["owner"] != PUBLIC and row["owner"] != viewer:
            return None
        return _scan_row(row)

    def list_scans(self, food: str | None = None, limit: int = 50, viewer: str | None = None) -> list[dict]:
        q = "SELECT * FROM scans WHERE (owner=? OR owner=?)"
        args: tuple = (PUBLIC, viewer)
        if food:
            q += " AND food=?"
            args += (food,)
        q += " ORDER BY created DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(q, (*args, limit)).fetchall()
        return [_scan_row(r) for r in rows]

    def reference_scans(self, food: str, device: str, owner: str = PUBLIC) -> list[dict]:
        """Usable reference library for one food, phone label and owner: reference-mode scans
        that passed the quality checks, oldest first."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM scans WHERE food=? AND device=? AND owner=? AND mode='reference' ORDER BY created",
                (food, device, owner),
            ).fetchall()
        out = []
        for r in rows:
            d = _scan_row(r)
            if isinstance(d.get("result"), dict) and d["result"].get("status") == "rejected":
                continue
            out.append(d)
        return out

    def reference_counts(self, food: str, owner: str = PUBLIC) -> dict:
        """Library size for one food and owner, overall and per phone label, for the foods catalog."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM scans WHERE food=? AND owner=? AND mode='reference'",
                             (food, owner)).fetchall()
        counts: dict = {"references": 0, "genuine": 0, "by_device": {}, "by_target": {}}
        for r in rows:
            d = _scan_row(r)
            if isinstance(d.get("result"), dict) and d["result"].get("status") == "rejected":
                continue
            counts["references"] += 1
            if d.get("label") == "genuine":
                counts["genuine"] += 1
            dev = counts["by_device"].setdefault(d.get("device") or "unknown", {"references": 0, "genuine": 0})
            dev["references"] += 1
            if d.get("label") == "genuine":
                dev["genuine"] += 1
            if d.get("target"):
                tgt = counts["by_target"].setdefault(d["target"], {})
                tgt[d.get("label") or "unknown"] = tgt.get(d.get("label") or "unknown", 0) + 1
        return counts

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


def _migrate_owner(c: sqlite3.Connection) -> None:
    """v0.2 databases kept one calibration pool per device label. Existing rows become public."""
    sample_cols = {r[1] for r in c.execute("PRAGMA table_info(calibration_samples)")}
    if sample_cols and "owner" not in sample_cols:
        c.execute("ALTER TABLE calibration_samples ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        c.execute("ALTER TABLE calibration_samples ADD COLUMN run_id TEXT")
    model_cols = {r[1] for r in c.execute("PRAGMA table_info(models)")}
    if model_cols and "owner" not in model_cols:  # the primary key changes, so rebuild the table
        c.execute("ALTER TABLE models RENAME TO models_v02")
        c.executescript(SCHEMA)
        c.execute("INSERT INTO models (assay_id, device, owner, created, kind, payload, metrics)"
                  " SELECT assay_id, device, '', created, kind, payload, metrics FROM models_v02")
        c.execute("DROP TABLE models_v02")


def _run_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("result", "features", "report"):
        if d.get(k):
            d[k] = json.loads(d[k])
    d.pop("api_key", None)
    return d


def _scan_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("features", "result"):
        if d.get(k):
            d[k] = json.loads(d[k])
    return d
