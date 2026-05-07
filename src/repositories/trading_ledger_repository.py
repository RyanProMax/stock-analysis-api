from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

from ..model.trading import OrderRequest


@dataclass(frozen=True)
class TradingRunLock:
    lock_name: str
    owner_id: str
    expires_at: str


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _format_dt(value: datetime) -> str:
    return value.isoformat()


def _utc_now() -> str:
    return _format_dt(_utc_now_dt())


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


class SqliteTradingLedger:
    """Persistent audit ledger for simulated trading runs and idempotency keys."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        cache_root = os.environ.get("CACHE_DIR") or ".cache"
        self.db_path = Path(
            db_path
            or os.environ.get("TRADING_LEDGER_DB_PATH")
            or (Path(cache_root) / "trading_ledger.sqlite")
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
                CREATE TABLE IF NOT EXISTS trading_runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT
                );

                CREATE TABLE IF NOT EXISTS trading_risk_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    signal_json TEXT NOT NULL,
                    request_json TEXT,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trading_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    code TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL,
                    strategy_version_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    broker_result_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trading_locks (
                    lock_name TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trading_scheduler_ticks (
                    state_key TEXT PRIMARY KEY,
                    last_due_at TEXT NOT NULL,
                    last_started_at TEXT NOT NULL,
                    last_finished_at TEXT NOT NULL,
                    last_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trading_risk_decisions_run
                    ON trading_risk_decisions(run_id);
                CREATE INDEX IF NOT EXISTS idx_trading_orders_run
                    ON trading_orders(run_id);
                """)

    def try_acquire_lock(
        self,
        lock_name: str,
        *,
        ttl_seconds: int,
        owner_id: str | None = None,
    ) -> TradingRunLock | None:
        normalized_lock_name = str(lock_name or "").strip()
        if not normalized_lock_name:
            raise ValueError("lock_name must not be empty")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")

        owner = owner_id or str(uuid.uuid4())
        now = _utc_now_dt()
        acquired_at = _format_dt(now)
        expires_at = _format_dt(now + timedelta(seconds=int(ttl_seconds)))
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trading_locks (lock_name, owner_id, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(lock_name) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                WHERE trading_locks.expires_at <= ?
                """,
                (normalized_lock_name, owner, acquired_at, expires_at, acquired_at),
            )
        if cursor.rowcount != 1:
            return None
        return TradingRunLock(
            lock_name=normalized_lock_name,
            owner_id=owner,
            expires_at=expires_at,
        )

    def release_lock(self, lock: TradingRunLock) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM trading_locks
                WHERE lock_name = ? AND owner_id = ?
                """,
                (lock.lock_name, lock.owner_id),
            )

    def get_scheduler_tick(self, state_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM trading_scheduler_ticks WHERE state_key = ?",
                (state_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "state_key": row["state_key"],
            "last_due_at": row["last_due_at"],
            "last_started_at": row["last_started_at"],
            "last_finished_at": row["last_finished_at"],
            "last_status": row["last_status"],
            "payload": _json_loads(row["payload_json"]),
        }

    def record_scheduler_tick(
        self,
        state_key: str,
        *,
        due_at: str,
        started_at: str,
        finished_at: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trading_scheduler_ticks (
                    state_key, last_due_at, last_started_at, last_finished_at,
                    last_status, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    last_due_at = excluded.last_due_at,
                    last_started_at = excluded.last_started_at,
                    last_finished_at = excluded.last_finished_at,
                    last_status = excluded.last_status,
                    payload_json = excluded.payload_json
                """,
                (
                    state_key,
                    due_at,
                    started_at,
                    finished_at,
                    status,
                    _json_dumps(payload),
                ),
            )

    def start_run(self, request: dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trading_runs (id, started_at, status, request_json)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, _utc_now(), "running", _json_dumps(request)),
            )
        return run_id

    def finish_run(self, run_id: str, result: dict[str, Any], *, status: str = "ok") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE trading_runs
                SET finished_at = ?, status = ?, result_json = ?
                WHERE id = ?
                """,
                (_utc_now(), status, _json_dumps(result), run_id),
            )

    def has_order(self, idempotency_key: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM trading_orders WHERE idempotency_key = ? LIMIT 1",
                (idempotency_key,),
            ).fetchone()
        return row is not None

    def record_risk_decision(self, run_id: str, decision: Any) -> None:
        request = decision.request.to_dict() if decision.request is not None else None
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trading_risk_decisions (
                    run_id, status, reason, signal_json, request_json, decision_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    decision.status,
                    decision.reason,
                    _json_dumps(decision.signal.to_dict()),
                    _json_dumps(request) if request is not None else None,
                    _json_dumps(decision.to_dict()),
                    _utc_now(),
                ),
            )

    def record_order(
        self,
        order: OrderRequest,
        *,
        run_id: str | None = None,
        broker_result: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO trading_orders (
                    run_id, idempotency_key, code, side, quantity, price,
                    strategy_version_id, request_json, broker_result_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    order.idempotency_key,
                    order.code,
                    order.side.value,
                    order.quantity,
                    order.price,
                    order.strategy_version_id,
                    _json_dumps(order.to_dict()),
                    _json_dumps(broker_result) if broker_result is not None else None,
                    _utc_now(),
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM trading_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._run_from_row(row)

    def list_runs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM trading_runs ORDER BY started_at ASC").fetchall()
        return [self._run_from_row(row) for row in rows]

    def _run_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "request": _json_loads(row["request_json"]),
            "result": _json_loads(row["result_json"]),
        }

    def list_risk_decisions(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trading_risk_decisions
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "status": row["status"],
                "reason": row["reason"],
                "signal": _json_loads(row["signal_json"]),
                "request": _json_loads(row["request_json"]),
                "decision": _json_loads(row["decision_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_orders(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM trading_orders ORDER BY id ASC").fetchall()
        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "idempotency_key": row["idempotency_key"],
                "code": row["code"],
                "side": row["side"],
                "quantity": row["quantity"],
                "price": row["price"],
                "strategy_version_id": row["strategy_version_id"],
                "request": _json_loads(row["request_json"]),
                "broker_result": _json_loads(row["broker_result_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
