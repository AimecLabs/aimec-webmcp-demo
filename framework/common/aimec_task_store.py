"""Durable, owner-scoped capability jobs. Inputs and session bearers are not stored."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskConflict(ValueError):
    pass


class TaskLimit(ValueError):
    pass


class CapabilityTaskStore:
    def __init__(self, path, *, max_jobs=1000, max_sessions=1000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_jobs, self.max_sessions = max_jobs, max_sessions
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS capability_jobs (
                    job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    kind TEXT NOT NULL, capability_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    result_json TEXT, result_sha256 TEXT, error TEXT,
                    timeline_json TEXT NOT NULL,
                    UNIQUE(owner, request_key)
                );
                CREATE TABLE IF NOT EXISTS anonymous_sessions (
                    owner TEXT PRIMARY KEY, expires REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    def session(self, bearer=None):
        """Return a known owner or issue a bearer; only its hash is persisted."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM capability_jobs WHERE owner IN (SELECT owner FROM anonymous_sessions WHERE expires < ?)", (time.time(),))
            db.execute("DELETE FROM anonymous_sessions WHERE expires < ?", (time.time(),))
            if isinstance(bearer, str) and len(bearer) == 64:
                owner = hashlib.sha256(bearer.encode()).hexdigest()
                if db.execute("SELECT 1 FROM anonymous_sessions WHERE owner=?", (owner,)).fetchone():
                    return owner, None
            if db.execute("SELECT count(*) FROM anonymous_sessions").fetchone()[0] >= self.max_sessions:
                raise TaskLimit("session_capacity_reached")
            bearer = uuid4().hex + uuid4().hex
            owner = hashlib.sha256(bearer.encode()).hexdigest()
            db.execute("INSERT INTO anonymous_sessions VALUES (?, ?)", (owner, time.time() + 86400))
            return owner, bearer

    def begin(self, owner, kind, capability_id, operation_id, supplied, request_key):
        fingerprint = digest([kind, capability_id, operation_id, supplied])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM capability_jobs WHERE owner=? AND request_key=?", (owner, request_key)
            ).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise TaskConflict("idempotency_key_conflict")
                return self.public(previous), False
            if db.execute("SELECT count(*) FROM capability_jobs").fetchone()[0] >= self.max_jobs:
                raise TaskLimit("job_capacity_reached")
            active = db.execute(
                "SELECT count(*) FROM capability_jobs WHERE state IN ('queued','running')"
            ).fetchone()[0]
            if active >= 8:
                raise TaskLimit("execution_capacity_reached")
            job_id = "WEBMCP-" + uuid4().hex
            created = now()
            timeline = [{"stage": "queued", "status": "queued", "at": created}]
            db.execute(
                """INSERT INTO capability_jobs
                   (job_id,owner,request_key,fingerprint,kind,capability_id,operation_id,
                    state,created_at,updated_at,timeline_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, owner, request_key, fingerprint, kind, capability_id, operation_id,
                 "queued", created, created, canonical(timeline)),
            )
            row = db.execute("SELECT * FROM capability_jobs WHERE job_id=?", (job_id,)).fetchone()
            return self.public(row), True

    def transition(self, owner, job_id, state, *, result=None, error=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM capability_jobs WHERE owner=? AND job_id=?", (owner, job_id)).fetchone()
            if row is None:
                raise KeyError(job_id)
            permitted = {"queued": {"running", "interrupted", "failed"},
                         "running": {"completed", "failed", "interrupted"}}
            if state not in permitted.get(row["state"], set()):
                raise TaskConflict("invalid_task_transition")
            updated = now()
            timeline = json.loads(row["timeline_json"])
            timeline.append({"stage": state, "status": state, "at": updated})
            encoded = canonical(result) if state == "completed" else None
            result_hash = digest(result) if state == "completed" else None
            db.execute(
                """UPDATE capability_jobs SET state=?,updated_at=?,result_json=?,result_sha256=?,
                   error=?,timeline_json=? WHERE owner=? AND job_id=?""",
                (state, updated, encoded, result_hash, error, canonical(timeline), owner, job_id),
            )
        return self.get(owner, job_id)

    def get(self, owner, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM capability_jobs WHERE owner=? AND job_id=?", (owner, job_id)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self.public(row)

    def recover_interrupted(self):
        """Single-process startup: never replay work with an uncertain outcome."""
        with self.connect() as db:
            rows = db.execute("SELECT owner,job_id FROM capability_jobs WHERE state IN ('queued','running')").fetchall()
        for row in rows:
            self.transition(row["owner"], row["job_id"], "interrupted", error="restart_interrupted_execution")
        return len(rows)

    @staticmethod
    def public(row):
        result = json.loads(row["result_json"]) if row["result_json"] else None
        if result is not None and digest(result) != row["result_sha256"]:
            raise TaskConflict("stored_result_integrity_failed")
        artifact = [] if result is None else [{
            "uri": "urn:aimec:result:" + row["job_id"], "sha256": row["result_sha256"],
            "media_type": "application/json", "visibility": "session",
        }]
        return {
            "job_id": row["job_id"], "task_id": row["job_id"], "correlation_id": row["job_id"],
            "kind": row["kind"], "capability_id": row["capability_id"], "operation_id": row["operation_id"],
            "state": row["state"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "result": result, "artifacts": artifact, "timeline": json.loads(row["timeline_json"]),
            "error": row["error"],
        }
