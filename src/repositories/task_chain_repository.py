from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
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


AGENT_HANDOFF_FORBIDDEN_ACTIONS = [
    "live_trade",
    "unlock_trade",
    "approve_strategy",
    "activate_strategy",
]

AGENT_HANDOFF_ROLE_POLICIES: dict[str, dict[str, list[str]]] = {
    "kol_researcher": {
        "allowed_actions": ["semantic_review", "evidence_summary"],
        "forbidden_actions": AGENT_HANDOFF_FORBIDDEN_ACTIONS,
    },
    "news_researcher": {
        "allowed_actions": ["semantic_review", "evidence_summary"],
        "forbidden_actions": AGENT_HANDOFF_FORBIDDEN_ACTIONS,
    },
    "sector_reviewer": {
        "allowed_actions": ["semantic_review", "evidence_summary"],
        "forbidden_actions": AGENT_HANDOFF_FORBIDDEN_ACTIONS,
    },
    "daily_report_writer": {
        "allowed_actions": ["report_synthesis", "evidence_summary"],
        "forbidden_actions": AGENT_HANDOFF_FORBIDDEN_ACTIONS,
    },
    "strategy_researcher": {
        "allowed_actions": ["strategy_proposal_draft", "evidence_summary"],
        "forbidden_actions": AGENT_HANDOFF_FORBIDDEN_ACTIONS,
    },
    "strategy_backtester": {
        "allowed_actions": ["backtest", "failure_analysis"],
        "forbidden_actions": AGENT_HANDOFF_FORBIDDEN_ACTIONS,
    },
    "strategy_judge": {
        "allowed_actions": ["gate_verdict", "risk_review"],
        "forbidden_actions": AGENT_HANDOFF_FORBIDDEN_ACTIONS,
    },
}

AGENT_HANDOFF_ROLES = tuple(sorted(AGENT_HANDOFF_ROLE_POLICIES))

DEFAULT_AGENT_ROLE_BY_TASK_TYPE = {
    "kol_scan": "kol_researcher",
    "news_scan": "news_researcher",
    "sector_review": "sector_reviewer",
    "daily_report": "daily_report_writer",
    "strategy_analysis": "strategy_researcher",
    "strategy_iteration": "strategy_researcher",
}


def _agent_handoff_hash(payload: dict[str, Any]) -> str:
    encoded = _json_dumps(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _normalize_agent_role(role: str | None, task_type: str) -> str:
    normalized = str(role or DEFAULT_AGENT_ROLE_BY_TASK_TYPE.get(task_type, "")).strip()
    if normalized not in AGENT_HANDOFF_ROLE_POLICIES:
        raise ValueError(f"unsupported agent handoff role: {normalized}")
    return normalized


def _agent_role_policy(role: str) -> tuple[list[str], list[str]]:
    policy = AGENT_HANDOFF_ROLE_POLICIES[role]
    return list(policy["allowed_actions"]), list(policy["forbidden_actions"])


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


def _is_legacy_agent_handoff(row: sqlite3.Row) -> bool:
    return str(_row_value(row, "idempotency_key") or "").startswith("legacy:")


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

                CREATE TABLE IF NOT EXISTS task_chain_agent_handoffs (
                    id TEXT PRIMARY KEY,
                    source_task_id TEXT,
                    source_run_id TEXT,
                    task_type TEXT NOT NULL,
                    role TEXT,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    market TEXT,
                    symbols_json TEXT,
                    as_of TEXT,
                    input_payload_json TEXT,
                    input_hash TEXT,
                    idempotency_key TEXT,
                    allowed_actions_json TEXT,
                    forbidden_actions_json TEXT,
                    prompt_json TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    claimed_by TEXT,
                    claimed_at TEXT,
                    lease_expires_at TEXT
                );

                CREATE TABLE IF NOT EXISTS task_chain_agent_handoff_events (
                    id TEXT PRIMARY KEY,
                    handoff_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    owner_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_chain_agent_handoff_outputs (
                    id TEXT PRIMARY KEY,
                    handoff_id TEXT NOT NULL,
                    agent_role TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_chain_tasks_due
                    ON task_chain_tasks(status, due_at, priority);
                CREATE INDEX IF NOT EXISTS idx_task_chain_runs_task
                    ON task_chain_runs(task_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_task_chain_summaries_type
                    ON task_chain_summaries(summary_type, period_end);
                CREATE INDEX IF NOT EXISTS idx_task_chain_agent_handoffs_status
                    ON task_chain_agent_handoffs(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_task_chain_agent_handoff_events_handoff
                    ON task_chain_agent_handoff_events(handoff_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_task_chain_agent_handoff_outputs_handoff
                    ON task_chain_agent_handoff_outputs(handoff_id, created_at);
            """)
            self._ensure_agent_handoff_columns(conn)
            conn.executescript("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_chain_agent_handoffs_idempotency
                    ON task_chain_agent_handoffs(idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_task_chain_agent_handoffs_claim
                    ON task_chain_agent_handoffs(role, status, created_at);
            """)

    @staticmethod
    def _ensure_agent_handoff_columns(conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(task_chain_agent_handoffs)").fetchall()
        }
        columns = {
            "role": "TEXT",
            "priority": "INTEGER NOT NULL DEFAULT 100",
            "market": "TEXT",
            "symbols_json": "TEXT",
            "as_of": "TEXT",
            "input_payload_json": "TEXT",
            "input_hash": "TEXT",
            "idempotency_key": "TEXT",
            "allowed_actions_json": "TEXT",
            "forbidden_actions_json": "TEXT",
            "lease_expires_at": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE task_chain_agent_handoffs ADD COLUMN {name} {definition}"
                )
        for row in conn.execute("""
            SELECT * FROM task_chain_agent_handoffs
            WHERE role IS NULL
               OR input_payload_json IS NULL
               OR input_hash IS NULL
               OR idempotency_key IS NULL
               OR allowed_actions_json IS NULL
               OR forbidden_actions_json IS NULL
            """).fetchall():
            task_type = row["task_type"]
            role = row["role"] or DEFAULT_AGENT_ROLE_BY_TASK_TYPE.get(
                task_type, "strategy_researcher"
            )
            allowed_actions, forbidden_actions = _agent_role_policy(role)
            prompt_json = _json_loads(row["prompt_json"])
            input_payload = _json_loads(row["input_payload_json"])
            if not input_payload:
                input_payload = {
                    "source_task_id": row["source_task_id"],
                    "source_run_id": row["source_run_id"],
                    "source_task_type": task_type,
                    "role": role,
                    "prompt_text": row["prompt_text"],
                    "prompt_json": prompt_json,
                }
            input_hash = row["input_hash"] or _agent_handoff_hash(input_payload)
            conn.execute(
                """
                UPDATE task_chain_agent_handoffs
                SET role = COALESCE(role, ?),
                    input_payload_json = COALESCE(input_payload_json, ?),
                    input_hash = COALESCE(input_hash, ?),
                    idempotency_key = COALESCE(idempotency_key, ?),
                    allowed_actions_json = COALESCE(allowed_actions_json, ?),
                    forbidden_actions_json = COALESCE(forbidden_actions_json, ?)
                WHERE id = ?
                """,
                (
                    role,
                    _json_dumps(input_payload),
                    input_hash,
                    f"legacy:{row['id']}",
                    _json_dumps(allowed_actions),
                    _json_dumps(forbidden_actions),
                    row["id"],
                ),
            )

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
            sql = (
                "SELECT * FROM task_chain_tasks WHERE status = ? ORDER BY due_at ASC, priority ASC"
            )
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

    def supersede_pending_tasks(
        self,
        *,
        task_types: list[str],
        due_before: str,
        updated_at: str,
        reason: str,
    ) -> int:
        normalized_types = [
            str(task_type).strip() for task_type in task_types if str(task_type).strip()
        ]
        if not normalized_types:
            return 0
        placeholders = ", ".join("?" for _ in normalized_types)
        result = {
            "status": "superseded",
            "reason": str(reason or "superseded"),
            "superseded_at": updated_at,
        }
        with self.connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE task_chain_tasks
                SET status = 'completed',
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    result_json = ?,
                    error = NULL,
                    updated_at = ?
                WHERE status = 'pending'
                  AND task_type IN ({placeholders})
                  AND due_at <= ?
                """,
                (
                    _json_dumps(result),
                    updated_at,
                    *normalized_types,
                    due_before,
                ),
            )
        return int(cursor.rowcount or 0)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM task_chain_runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_from_row(row) if row is not None else None

    def list_runs_between(self, *, period_start: str, period_end: str) -> list[dict[str, Any]]:
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

    def list_summaries(self, *, summary_type: str | None = None) -> list[dict[str, Any]]:
        if summary_type:
            sql = (
                "SELECT * FROM task_chain_summaries WHERE summary_type = ? ORDER BY period_end ASC"
            )
            params: tuple[Any, ...] = (summary_type,)
        else:
            sql = "SELECT * FROM task_chain_summaries ORDER BY period_end ASC"
            params = ()
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._summary_from_row(row) for row in rows]

    def create_agent_handoff(
        self,
        *,
        source_task_id: str | None,
        source_run_id: str | None,
        task_type: str,
        prompt_text: str,
        prompt_json: dict[str, Any] | None = None,
        created_at: str | None = None,
        handoff_id: str | None = None,
        role: str | None = None,
        input_payload: dict[str, Any] | None = None,
        market: str | None = None,
        symbols: list[str] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        handoff, _ = self.enqueue_agent_handoff(
            source_task_id=source_task_id,
            source_run_id=source_run_id,
            task_type=task_type,
            role=role,
            input_payload=input_payload,
            prompt_text=prompt_text,
            prompt_json=prompt_json,
            created_at=created_at,
            handoff_id=handoff_id,
            market=market,
            symbols=symbols,
            as_of=as_of,
        )
        return handoff

    def enqueue_agent_handoff(
        self,
        *,
        source_task_id: str | None,
        source_run_id: str | None,
        task_type: str,
        role: str | None,
        input_payload: dict[str, Any] | None,
        prompt_text: str | None = None,
        prompt_json: dict[str, Any] | None = None,
        created_at: str | None = None,
        handoff_id: str | None = None,
        idempotency_key: str | None = None,
        priority: int = 100,
        market: str | None = None,
        symbols: list[str] | None = None,
        as_of: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        normalized_task_type = str(task_type or "").strip()
        if not normalized_task_type:
            raise ValueError("task_type must not be empty")
        normalized_role = _normalize_agent_role(role, normalized_task_type)
        payload = dict(input_payload or {})
        normalized_prompt_text = str(
            prompt_text if prompt_text is not None else payload.get("prompt_text") or ""
        )
        normalized_prompt_json = (
            prompt_json
            if prompt_json is not None
            else payload.get("prompt_json") if isinstance(payload.get("prompt_json"), dict) else {}
        )
        payload.setdefault("source_task_id", source_task_id)
        payload.setdefault("source_run_id", source_run_id)
        payload.setdefault("source_task_type", normalized_task_type)
        payload.setdefault("role", normalized_role)
        payload.setdefault("prompt_text", normalized_prompt_text)
        payload.setdefault("prompt_json", normalized_prompt_json)
        if market is None and payload.get("market") is not None:
            market = str(payload.get("market"))
        if symbols is None and isinstance(payload.get("symbols"), list):
            symbols = [str(symbol) for symbol in payload["symbols"]]
        if as_of is None and payload.get("as_of") is not None:
            as_of = str(payload.get("as_of"))
        input_hash = _agent_handoff_hash(payload)
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if not normalized_idempotency_key:
            if source_run_id:
                normalized_idempotency_key = f"task_run:{source_run_id}:{normalized_role}"
            elif source_task_id:
                normalized_idempotency_key = f"task:{source_task_id}:{normalized_role}:{input_hash}"
            else:
                normalized_idempotency_key = f"adhoc:{normalized_role}:{input_hash}"
        allowed_actions, forbidden_actions = _agent_role_policy(normalized_role)
        handoff_id = handoff_id or str(uuid.uuid4())
        now = created_at or _utc_now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE idempotency_key = ?",
                (normalized_idempotency_key,),
            ).fetchone()
            if existing is not None:
                return self._agent_handoff_from_row(existing), True
            conn.execute(
                """
                INSERT INTO task_chain_agent_handoffs (
                    id, source_task_id, source_run_id, task_type, role, status,
                    priority, market, symbols_json, as_of, input_payload_json,
                    input_hash, idempotency_key, allowed_actions_json,
                    forbidden_actions_json, prompt_json, prompt_text,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handoff_id,
                    source_task_id,
                    source_run_id,
                    normalized_task_type,
                    normalized_role,
                    int(priority),
                    market,
                    _json_dumps(symbols or []),
                    as_of,
                    _json_dumps(payload),
                    input_hash,
                    normalized_idempotency_key,
                    _json_dumps(allowed_actions),
                    _json_dumps(forbidden_actions),
                    _json_dumps(normalized_prompt_json),
                    normalized_prompt_text,
                    now,
                    now,
                ),
            )
            self._record_agent_handoff_event(
                conn,
                handoff_id=handoff_id,
                event_type="enqueued",
                owner_id=None,
                payload={
                    "idempotency_key": normalized_idempotency_key,
                    "input_hash": input_hash,
                    "role": normalized_role,
                },
                created_at=now,
            )
            row = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (handoff_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("created agent handoff cannot be loaded")
        return self._agent_handoff_from_row(row), False

    def get_agent_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (handoff_id,),
            ).fetchone()
        return self._agent_handoff_from_row(row) if row is not None else None

    def list_agent_handoffs(
        self, *, status: str | None = None, role: str | None = None
    ) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if role:
            where.append("role = ?")
            params.append(role)
        sql = "SELECT * FROM task_chain_agent_handoffs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at ASC"
        with self.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._agent_handoff_from_row(row) for row in rows]

    def claim_agent_handoff(
        self,
        *,
        handoff_id: str,
        claimed_by: str,
        claimed_at: str | None = None,
        lease_ttl_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        claimant = str(claimed_by or "").strip()
        if not claimant:
            raise ValueError("claimed_by must not be empty")
        now_dt = _parse_dt(claimed_at)
        now = _format_dt(now_dt)
        lease_expires_at = (
            _format_dt(now_dt + timedelta(seconds=int(lease_ttl_seconds)))
            if lease_ttl_seconds
            else None
        )
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ? AND status = 'pending'",
                (handoff_id,),
            ).fetchone()
            if row is None:
                return None
            cursor = conn.execute(
                """
                UPDATE task_chain_agent_handoffs
                SET status = 'claimed',
                    claimed_by = ?,
                    claimed_at = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (claimant, now, lease_expires_at, now, handoff_id),
            )
            if cursor.rowcount != 1:
                return None
            self._record_agent_handoff_event(
                conn,
                handoff_id=handoff_id,
                event_type="claimed",
                owner_id=claimant,
                payload={"lease_expires_at": lease_expires_at},
                created_at=now,
            )
            row = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (handoff_id,),
            ).fetchone()
        return self._agent_handoff_from_row(row) if row is not None else None

    def claim_next_agent_handoff(
        self,
        *,
        role: str,
        owner_id: str,
        lease_ttl_seconds: int,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_role = _normalize_agent_role(role, "")
        owner = str(owner_id or "").strip()
        if not owner:
            raise ValueError("owner_id must not be empty")
        ttl = int(lease_ttl_seconds)
        if ttl <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        now_dt = _parse_dt(now)
        now_text = _format_dt(now_dt)
        lease_expires_at = _format_dt(now_dt + timedelta(seconds=ttl))
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM task_chain_agent_handoffs
                WHERE role = ?
                  AND (
                    status = 'pending'
                    OR (status = 'claimed' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                  )
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """,
                (normalized_role, now_text),
            ).fetchone()
            if row is None:
                return None
            event_type = "reclaimed" if row["status"] == "claimed" else "claimed"
            conn.execute(
                """
                UPDATE task_chain_agent_handoffs
                SET status = 'claimed',
                    claimed_by = ?,
                    claimed_at = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (owner, now_text, lease_expires_at, now_text, row["id"]),
            )
            self._record_agent_handoff_event(
                conn,
                handoff_id=row["id"],
                event_type=event_type,
                owner_id=owner,
                payload={
                    "lease_ttl_seconds": ttl,
                    "lease_expires_at": lease_expires_at,
                    "previous_owner": row["claimed_by"],
                },
                created_at=now_text,
            )
            updated = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (row["id"],),
            ).fetchone()
        return self._agent_handoff_from_row(updated) if updated is not None else None

    def complete_agent_handoff(
        self,
        *,
        handoff_id: str,
        result: dict[str, Any] | None = None,
        completed_at: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        now = _format_dt(_parse_dt(completed_at))
        output = result or {}
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (handoff_id,),
            ).fetchone()
            if row is None:
                return None
            if owner_id:
                self._validate_handoff_lease(row, owner_id=owner_id, now=now)
                self._validate_agent_handoff_output(row, output)
                output_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO task_chain_agent_handoff_outputs (
                        id, handoff_id, agent_role, agent_id, model, input_hash,
                        output_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        output_id,
                        handoff_id,
                        output["agent_role"],
                        output["agent_id"],
                        output["model"],
                        output["input_hash"],
                        _json_dumps(output),
                        now,
                    ),
                )
            elif not _is_legacy_agent_handoff(row):
                raise ValueError("owner_id is required for handoff completion")
            elif row["status"] not in ("pending", "claimed"):
                return None
            cursor = conn.execute(
                """
                UPDATE task_chain_agent_handoffs
                SET status = 'completed',
                    result_json = ?,
                    error = NULL,
                    updated_at = ?
                WHERE id = ? AND status IN ('pending', 'claimed')
                """,
                (_json_dumps(output), now, handoff_id),
            )
            if cursor.rowcount != 1:
                return None
            self._record_agent_handoff_event(
                conn,
                handoff_id=handoff_id,
                event_type="completed",
                owner_id=owner_id,
                payload={"agent_id": output.get("agent_id"), "model": output.get("model")},
                created_at=now,
            )
            updated = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (handoff_id,),
            ).fetchone()
        return self._agent_handoff_from_row(updated) if updated is not None else None

    def fail_agent_handoff(
        self,
        *,
        handoff_id: str,
        error: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        retryable: bool | None = None,
        failed_at: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        now = _format_dt(_parse_dt(failed_at))
        normalized_error_type = str(error_type or "").strip()
        normalized_error_message = str(error_message or error or "").strip()
        normalized_error = (
            f"{normalized_error_type}: {normalized_error_message}"
            if normalized_error_type
            else normalized_error_message
        )
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (handoff_id,),
            ).fetchone()
            if row is None:
                return None
            if owner_id:
                self._validate_handoff_lease(row, owner_id=owner_id, now=now)
            elif not _is_legacy_agent_handoff(row):
                raise ValueError("owner_id is required for handoff failure")
            elif row["status"] not in ("pending", "claimed"):
                return None
            cursor = conn.execute(
                """
                UPDATE task_chain_agent_handoffs
                SET status = 'failed',
                    error = ?,
                    updated_at = ?
                WHERE id = ? AND status IN ('pending', 'claimed')
                """,
                (normalized_error, now, handoff_id),
            )
            if cursor.rowcount != 1:
                return None
            self._record_agent_handoff_event(
                conn,
                handoff_id=handoff_id,
                event_type="failed",
                owner_id=owner_id,
                payload={
                    "error_type": normalized_error_type,
                    "error_message": normalized_error_message,
                    "retryable": bool(retryable),
                },
                created_at=now,
            )
            updated = conn.execute(
                "SELECT * FROM task_chain_agent_handoffs WHERE id = ?",
                (handoff_id,),
            ).fetchone()
        return self._agent_handoff_from_row(updated) if updated is not None else None

    def list_agent_handoff_events(self, handoff_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_chain_agent_handoff_events
                WHERE handoff_id = ?
                ORDER BY created_at ASC
                """,
                (handoff_id,),
            ).fetchall()
        return [self._agent_handoff_event_from_row(row) for row in rows]

    def list_agent_handoff_outputs(self, handoff_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_chain_agent_handoff_outputs
                WHERE handoff_id = ?
                ORDER BY created_at ASC
                """,
                (handoff_id,),
            ).fetchall()
        return [self._agent_handoff_output_from_row(row) for row in rows]

    def replay_agent_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        handoff = self.get_agent_handoff(handoff_id)
        if handoff is None:
            return None
        return {
            "handoff": handoff,
            "events": self.list_agent_handoff_events(handoff_id),
            "outputs": self.list_agent_handoff_outputs(handoff_id),
        }

    @staticmethod
    def _record_agent_handoff_event(
        conn: sqlite3.Connection,
        *,
        handoff_id: str,
        event_type: str,
        owner_id: str | None,
        payload: dict[str, Any] | None,
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO task_chain_agent_handoff_events (
                id, handoff_id, event_type, owner_id, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                handoff_id,
                event_type,
                owner_id,
                _json_dumps(payload or {}),
                created_at,
            ),
        )

    @staticmethod
    def _validate_handoff_lease(row: sqlite3.Row, *, owner_id: str, now: str) -> None:
        owner = str(owner_id or "").strip()
        if not owner:
            raise ValueError("owner_id must not be empty")
        if row["status"] != "claimed":
            raise ValueError("handoff is not claimed")
        if row["claimed_by"] != owner:
            raise ValueError("handoff is claimed by a different owner")
        lease_expires_at = _row_value(row, "lease_expires_at")
        if not lease_expires_at:
            raise ValueError("handoff lease is missing")
        if _parse_dt(lease_expires_at) <= _parse_dt(now):
            raise ValueError("handoff lease expired")

    @staticmethod
    def _validate_agent_handoff_output(row: sqlite3.Row, output: dict[str, Any]) -> None:
        required = [
            "handoff_id",
            "agent_role",
            "agent_id",
            "model",
            "input_hash",
            "status",
            "evidence_refs",
            "summary",
            "findings",
            "confidence",
            "limitations",
            "proposed_next_actions",
            "forbidden_actions_attempted",
        ]
        missing = [field for field in required if field not in output]
        if missing:
            raise ValueError(f"handoff output missing fields: {', '.join(missing)}")
        if output["handoff_id"] != row["id"]:
            raise ValueError("handoff_id does not match handoff")
        if output["agent_role"] != _row_value(row, "role"):
            raise ValueError("agent_role does not match handoff role")
        if output["input_hash"] != _row_value(row, "input_hash"):
            raise ValueError("input_hash does not match handoff input_hash")
        if output["status"] != "completed":
            raise ValueError("handoff output status must be completed")
        if output["forbidden_actions_attempted"] is not False:
            raise ValueError("forbidden_actions_attempted must be false")
        if not isinstance(output["evidence_refs"], list):
            raise ValueError("evidence_refs must be a list")
        if not isinstance(output["findings"], list):
            raise ValueError("findings must be a list")
        if not isinstance(output["limitations"], list):
            raise ValueError("limitations must be a list")
        if not isinstance(output["proposed_next_actions"], list):
            raise ValueError("proposed_next_actions must be a list")
        if not isinstance(output["summary"], str) or not output["summary"].strip():
            raise ValueError("summary must be a non-empty string")
        allowed_actions = set(_json_loads(_row_value(row, "allowed_actions_json")))
        forbidden_actions = set(_json_loads(_row_value(row, "forbidden_actions_json")))
        for action in output["proposed_next_actions"]:
            action_text = (
                str(action.get("action") or action.get("type") or action.get("name") or action)
                if isinstance(action, dict)
                else str(action)
            )
            normalized_action = action_text.strip()
            if any(forbidden in normalized_action for forbidden in forbidden_actions):
                raise ValueError(f"forbidden proposed action: {action_text}")
            if normalized_action not in allowed_actions:
                raise ValueError(f"proposed action not allowed: {action_text}")

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

    @staticmethod
    def _agent_handoff_from_row(row: sqlite3.Row) -> dict[str, Any]:
        task_type = row["task_type"]
        role = _row_value(row, "role") or DEFAULT_AGENT_ROLE_BY_TASK_TYPE.get(
            task_type, "strategy_researcher"
        )
        prompt_json = _json_loads(row["prompt_json"])
        prompt_text = row["prompt_text"]
        input_payload = _json_loads(_row_value(row, "input_payload_json"))
        if not input_payload:
            input_payload = {
                "source_task_id": row["source_task_id"],
                "source_run_id": row["source_run_id"],
                "source_task_type": task_type,
                "role": role,
                "prompt_text": prompt_text,
                "prompt_json": prompt_json,
            }
        input_hash = _row_value(row, "input_hash") or _agent_handoff_hash(input_payload)
        allowed_actions = _json_loads(_row_value(row, "allowed_actions_json"))
        forbidden_actions = _json_loads(_row_value(row, "forbidden_actions_json"))
        if not allowed_actions or not forbidden_actions:
            allowed_actions, forbidden_actions = _agent_role_policy(role)
        return {
            "id": row["id"],
            "handoff_id": row["id"],
            "source_task_id": row["source_task_id"],
            "source_run_id": row["source_run_id"],
            "task_type": task_type,
            "role": role,
            "status": row["status"],
            "priority": _row_value(row, "priority", 100),
            "market": _row_value(row, "market"),
            "symbols": _json_loads(_row_value(row, "symbols_json")),
            "as_of": _row_value(row, "as_of"),
            "input_payload": input_payload,
            "input_hash": input_hash,
            "idempotency_key": _row_value(row, "idempotency_key"),
            "allowed_actions": allowed_actions,
            "forbidden_actions": forbidden_actions,
            "prompt_json": prompt_json,
            "prompt_text": prompt_text,
            "result_json": _json_loads(row["result_json"]),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "claimed_by": row["claimed_by"],
            "claimed_at": row["claimed_at"],
            "lease_expires_at": _row_value(row, "lease_expires_at"),
        }

    @staticmethod
    def _agent_handoff_event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "handoff_id": row["handoff_id"],
            "event_type": row["event_type"],
            "owner_id": row["owner_id"],
            "payload": _json_loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _agent_handoff_output_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "handoff_id": row["handoff_id"],
            "agent_role": row["agent_role"],
            "agent_id": row["agent_id"],
            "model": row["model"],
            "input_hash": row["input_hash"],
            "output": _json_loads(row["output_json"]),
            "created_at": row["created_at"],
        }
