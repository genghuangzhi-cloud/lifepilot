from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID

from .schemas import Plan, Task


class SQLiteStore:
    """Small SQLite repository for the single-user competition MVP."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured_path = path if path is not None else os.environ.get("LIFEPILOT_DB_PATH")
        self.path = Path(configured_path) if configured_path else Path(__file__).resolve().parents[1] / "data" / "lifepilot.db"
        self._memory_connection: sqlite3.Connection | None = None
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._memory_connection = sqlite3.connect(":memory:")
        self._init_schema()

    @contextmanager
    def _db(self):
        if self._memory_connection is not None:
            self._memory_connection.row_factory = sqlite3.Row
            try:
                yield self._memory_connection
                self._memory_connection.commit()
            except Exception:
                self._memory_connection.rollback()
                raise
            return
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_task(self, task: Task) -> Task:
        payload = json.dumps(task.model_dump(mode="json"), ensure_ascii=False)
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO tasks (id, payload, updated_at) VALUES (?, ?, ?)", (str(task.id), payload, task.updated_at.isoformat()))
        return task

    def save_tasks(self, tasks: Iterable[Task]) -> None:
        for task in tasks:
            self.save_task(task)

    def get_task(self, task_id: UUID) -> Task | None:
        with self._db() as db:
            row = db.execute("SELECT payload FROM tasks WHERE id = ?", (str(task_id),)).fetchone()
        return Task.model_validate(json.loads(row["payload"])) if row else None

    def list_tasks(self) -> list[Task]:
        with self._db() as db:
            rows = db.execute("SELECT payload FROM tasks ORDER BY updated_at DESC").fetchall()
        return [Task.model_validate(json.loads(row["payload"])) for row in rows]

    def save_plan(self, plan: Plan) -> Plan:
        payload = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO plans (id, version, payload, created_at) VALUES (?, ?, ?, ?)", (str(plan.id), plan.version, payload, plan.generated_at.isoformat()))
        return plan

    def get_plan(self, plan_id: UUID) -> Plan | None:
        with self._db() as db:
            row = db.execute("SELECT payload FROM plans WHERE id = ?", (str(plan_id),)).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload"])
        # Plans written before task_ids/windows were introduced remain readable;
        # event routes can return a clear 409 for these legacy snapshots.
        payload.setdefault("task_ids", [])
        payload.setdefault("windows", [])
        return Plan.model_validate(payload)

    def save_event(self, plan_id: UUID, task_id: UUID, event_type: str, payload: dict) -> None:
        with self._db() as db:
            db.execute("INSERT INTO events (plan_id, task_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)", (str(plan_id), str(task_id), event_type, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
