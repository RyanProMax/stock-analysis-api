from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Generator
import uuid


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return _utc_now_dt()
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_dt(value: datetime) -> str:
    return value.isoformat()


def _utc_now() -> str:
    return _format_dt(_utc_now_dt())


def _json_dumps(payload: Any) -> str:
    return json.dumps(
        payload if payload is not None else {},
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def _json_loads(value: str | None) -> Any:
    if not value:
        return {}
    return json.loads(value)


class SqliteTaskChainRepository:
    """Persistent task-chain store with per-task lease and append-only run logs."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        cache_root = os.environ.get("CACHE_DIR") or ".cache"
        self.db_path = Path(
            db_path
            or os.environ.get("TASK_CHAIN_DB_PATH")
            or (Path(cache_root) / "task_chain.sqlite")
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS task_chain_tasks (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    due_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    parent_task_id TEXT,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_chain_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS task_chain_summaries (
                    id TEXT PRIMARY KEY,
                    summary_type TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_chain_tasks_due
                    ON task_chain_tasks(status, due_at, priority);
                CREATE INDEX IF NOT EXISTS idx_task_chain_runs_task
                    ON task_chain_runs(task_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_task_chain_summaries_type
                    ON task_chain_summaries(summary_type, period_end);
            """)

    def create_task(
        self,
        *,
        task_type: str,
        due_at: str,
        payload: dict[str, Any] | None = None,
        parent_task_id: str | None = None,
        priority: int = 100,
        created_at: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_task_type = str(task_type or "").strip()
        if not normalized_task_type:
            raise ValueError("task_type must not be empty")
        task_id = task_id or str(uuid.uuid4())
        now = created_at or _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task_chain_tasks (
                    id, task_type, status, priority, due_at, payload_json,
                    parent_task_id, created_at, updated_at
                )
                VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    normalized_task_type,
                    int(priority),
                    due_at,
                    _json_dumps(payload or {}),
                    parent_task_id,
                    now,
                    now,
                ),
            )
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("created task cannot be loaded")
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_chain_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return self._task_from_row(row) if row is not None else None

    def list_tasks(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            sql = "SELECT * FROM task_chain_tasks WHERE status = ? ORDER BY due_at ASC, priority ASC"
            params: tuple[Any, ...] = (status,)
        else:
            sql = "SELECT * FROM task_chain_tasks ORDER BY due_at ASC, priority ASC"
            params = ()
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._task_from_row(row) for row in rows]

    def acquire_due_task(
        self,
        *,
        now: str,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> dict[str, Any] | None:
        owner = str(owner_id or "").strip() or str(uuid.uuid4())
        ttl = int(lease_ttl_seconds)
        if ttl <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        now_dt = _parse_dt(now)
        lease_expires_at = _format_dt(now_dt + timedelta(seconds=ttl))
        now_text = _format_dt(now_dt)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM task_chain_tasks
                WHERE due_at <= ?
                  AND (
                    status = 'pending'
                    OR (status = 'running' AND lease_expires_at <= ?)
                  )
                ORDER BY priority ASC, due_at ASC, created_at ASC
                LIMIT 1
                """,
                (now_text, now_text),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE task_chain_tasks
                SET status = 'running',
                    lease_owner = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (owner, lease_expires_at, now_text, row["id"]),
            )
            updated = conn.execute(
                "SELECT * FROM task_chain_tasks WHERE id = ?",
                (row["id"],),
            ).fetchone()
        return self._task_from_row(updated) if updated is not None else None

    def start_run(
        self,
        *,
        task: dict[str, Any],
        owner_id: str,
        started_at: str,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task_chain_runs (
                    id, task_id, task_type, owner_id, started_at, status, input_json
                )
                VALUES (?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    run_id,
                    task["id"],
                    task["task_type"],
                    owner_id,
                    started_at,
                    _json_dumps(task),
                ),
            )
        run = self.get_run(run_id)
        if run is None:
            raise RuntimeError("created run cannot be loaded")
        return run

    def finish_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE task_chain_runs
                SET finished_at = ?, status = ?, output_json = ?, error = ?
                WHERE id = ?
                """,
                (finished_at, status, _json_dumps(output or {}), error, run_id),
            )
        run = self.get_run(run_id)
        if run is None:
            raise RuntimeError("finished run cannot be loaded")
        return run

    def complete_task(
        self,
        *,
        task_id: str,
        status: str,
        updated_at: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE task_chain_tasks
                SET status = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    result_json = ?,
                    error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, _json_dumps(result or {}), error, updated_at, task_id),
            )
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("completed task cannot be loaded")
        return task

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_chain_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def list_runs_between(
        self, *, period_start: str, period_end: str
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_chain_runs
                WHERE started_at >= ? AND started_at <= ?
                ORDER BY started_at ASC
                """,
                (period_start, period_end),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def record_summary(
        self,
        *,
        summary_type: str,
        period_start: str,
        period_end: str,
        summary: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        summary_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task_chain_summaries (
                    id, summary_type, period_start, period_end, summary_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    summary_id,
                    summary_type,
                    period_start,
                    period_end,
                    _json_dumps(summary),
                    created_at,
                ),
            )
        return self.get_summary(summary_id) or {}

    def get_summary(self, summary_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_chain_summaries WHERE id = ?",
                (summary_id,),
            ).fetchone()
        return self._summary_from_row(row) if row is not None else None

    def list_summaries(
        self, *, summary_type: str | None = None
    ) -> list[dict[str, Any]]:
        if summary_type:
            sql = "SELECT * FROM task_chain_summaries WHERE summary_type = ? ORDER BY period_end ASC"
            params: tuple[Any, ...] = (summary_type,)
        else:
            sql = "SELECT * FROM task_chain_summaries ORDER BY period_end ASC"
            params = ()
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._summary_from_row(row) for row in rows]

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "task_type": row["task_type"],
            "status": row["status"],
            "priority": row["priority"],
            "due_at": row["due_at"],
            "payload": _json_loads(row["payload_json"]),
            "parent_task_id": row["parent_task_id"],
            "lease_owner": row["lease_owner"],
            "lease_expires_at": row["lease_expires_at"],
            "result": _json_loads(row["result_json"]),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "owner_id": row["owner_id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "input": _json_loads(row["input_json"]),
            "output": _json_loads(row["output_json"]),
            "error": row["error"],
        }

    @staticmethod
    def _summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "summary_type": row["summary_type"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "summary": _json_loads(row["summary_json"]),
            "created_at": row["created_at"],
        }
