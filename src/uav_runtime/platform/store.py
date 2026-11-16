"""Transactional tasks and resumable events. Ambiguous actions never replay."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contract import PlatformError, canonical, fingerprint


class TaskStore:
    def __init__(self, directory: str | Path):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._file = (directory / "owner.lock").open("a+b")
        self._file.seek(0, os.SEEK_END)
        if self._file.tell() == 0:
            self._file.write(b"0")
            self._file.flush()
        self._file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            raise PlatformError("store_already_owned", 409) from None
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.db = sqlite3.connect(directory / "tasks.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('store_id', ?)", (str(uuid4()),))
            self.db.execute("CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL)")
        self.store_id = self.db.execute("SELECT value FROM metadata WHERE key='store_id'").fetchone()[0]

    def close(self) -> None:
        self.db.close()
        self._file.close()

    def bind(self, node_id: str, mode: str) -> None:
        with self.lock, self.db:
            binding = canonical({"node_id": node_id, "execution_mode": mode})
            row = self.db.execute("SELECT value FROM metadata WHERE key='deployment'").fetchone()
            if row is not None and row[0] != binding:
                raise PlatformError("store_deployment_mismatch", 409)
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('deployment',?)", (binding,))

    def _event(self, kind: str, task: dict[str, Any], **data: Any) -> None:
        event = {"contract_version": "1.0", "store_id": self.store_id, "event_type": kind,
                 **{k: task.get(k) for k in ("node_id", "task_id", "task_version", "execution_id", "request_id", "trace_id")},
                 "timestamp": task.get("updated_at"), "data": data}
        encoded = canonical(event)
        if len(encoded.encode()) > 32768:
            event["data"] = {"payload_omitted": True, "sha256": fingerprint(data),
                             "reason": "event_payload_too_large", "original_bytes": len(canonical(data).encode())}
        self.db.execute("INSERT INTO events(body) VALUES (?)", (canonical(event),))

    def accept(self, body: dict[str, Any], now: str, mode: str) -> tuple[dict[str, Any], bool]:
        with self.lock, self.db:
            existing = self.db.execute("SELECT fingerprint,body FROM tasks WHERE task_id=? OR request_id=?", (body["task_id"], body["request_id"])).fetchall()
            if existing:
                if len(existing) != 1 or existing[0][0] != fingerprint(body):
                    raise PlatformError("idempotency_conflict", 409)
                return json.loads(existing[0][1]), False
            if self.active() is not None:
                raise PlatformError("node_busy", 409)
            task = {**body, "execution_id": str(uuid4()), "status": "accepted", "execution_mode": mode,
                    "created_at": now, "updated_at": now, "current_step": None, "step_outcomes": [],
                    "failure_reason": None, "cancel_requested": False}
            self.db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (body["task_id"], body["request_id"], fingerprint(body), "accepted", canonical(task)))
            self._event("task_accepted", task)
            self.changed.notify_all()
            return task, True

    def task(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT body FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise PlatformError("task_not_found", 404)
            return json.loads(row[0])

    def active(self) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM tasks WHERE status IN ('accepted','executing','recovery_required') LIMIT 1").fetchone()
            return json.loads(row[0]) if row else None

    def update(self, task_id: str, now: str, kind: str, *, data: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
        with self.lock, self.db:
            task = {**self.task(task_id), **fields, "updated_at": now}
            self.db.execute("UPDATE tasks SET status=?,body=? WHERE task_id=?", (task["status"], canonical(task), task_id))
            self._event(kind, task, **(data or {}))
            self.changed.notify_all()
            return task

    def recover(self, now: str) -> None:
        with self.lock:
            rows = self.db.execute("SELECT task_id FROM tasks WHERE status IN ('accepted','executing')").fetchall()
            for (tid,) in rows:
                self.update(tid, now, "task_recovery_required", status="recovery_required", failure_reason="process_restart_execution_uncertain")

    def events(self, after: int = 0, limit: int = 100) -> dict[str, Any]:
        if type(after) is not int or after < 0 or not 1 <= limit <= 100:
            raise PlatformError("invalid_event_cursor")
        with self.lock:
            checkpoint = self.db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            if after > checkpoint:
                raise PlatformError("event_cursor_ahead", 409)
            rows = self.db.execute("SELECT seq,body FROM events WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)).fetchall()
            events, size = [], 0
            for seq, body in rows:
                event = {**json.loads(body), "seq": seq}
                amount = len(canonical(event).encode())
                if events and size + amount > 49152:
                    break
                events.append(event)
                size += amount
            return {"contract_version": "1.0", "store_id": self.store_id, "events": events,
                    "next_seq": events[-1]["seq"] if events else after, "checkpoint_seq": checkpoint,
                    "history_gap": False, "has_more": bool(events and events[-1]["seq"] < checkpoint)}
