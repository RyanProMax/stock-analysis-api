from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


class SqliteStrategyRegistry:
    """Append-audited registry for strategy proposals, approvals, and activation."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        cache_root = os.environ.get("CACHE_DIR") or ".cache"
        self.db_path = Path(
            db_path
            or os.environ.get("STRATEGY_REGISTRY_DB_PATH")
            or (Path(cache_root) / "strategy_registry.sqlite")
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
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS strategy_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    strategy_version TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_versions (
                    strategy_version TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    source_proposal_id TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    risk_limits_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approved_by TEXT,
                    retired_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_version TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    approval_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_activation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_version TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    previous_strategy_version TEXT,
                    activation_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_version_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_version TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alpha_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alpha_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evaluation_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_strategy_versions_status
                    ON strategy_versions(status);
                CREATE INDEX IF NOT EXISTS idx_strategy_approvals_version
                    ON strategy_approvals(strategy_version);
                CREATE INDEX IF NOT EXISTS idx_strategy_events_version
                    ON strategy_version_events(strategy_version);
                CREATE INDEX IF NOT EXISTS idx_alpha_candidates_candidate_id
                    ON alpha_candidates(candidate_id);
                CREATE INDEX IF NOT EXISTS idx_alpha_evaluations_evaluation_id
                    ON alpha_evaluations(evaluation_id);
            """)

    def save_candidate_strategy(self, *, proposal: dict[str, Any], version: dict[str, Any]) -> dict:
        now = _utc_now()
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO strategy_proposals (
                        proposal_id, strategy_version, generated_at, source,
                        payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal["proposal_id"],
                        proposal["strategy_version"],
                        proposal["generated_at"],
                        proposal["source"],
                        _json_dumps(proposal),
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO strategy_versions (
                        strategy_version, status, source_proposal_id, parameters_json,
                        risk_limits_json, created_at, approved_by, retired_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version["strategy_version"],
                        version["status"],
                        version["source_proposal_id"],
                        _json_dumps(version.get("parameters") or {}),
                        _json_dumps(version.get("risk_limits") or {}),
                        version["created_at"],
                        version.get("approved_by"),
                        version.get("retired_at"),
                        now,
                    ),
                )
                self._insert_event(
                    conn,
                    strategy_version=version["strategy_version"],
                    event_type="proposed",
                    from_status=None,
                    to_status="candidate",
                    payload={"proposal_id": proposal["proposal_id"]},
                    created_at=now,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"strategy proposal or version already exists: {exc}") from exc
        return self.get_strategy_version(version["strategy_version"])

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return self._proposal_from_row(row)

    def get_strategy_version(self, strategy_version: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_versions WHERE strategy_version = ?",
                (strategy_version,),
            ).fetchone()
        if row is None:
            raise KeyError(strategy_version)
        return self._version_from_row(row)

    def list_versions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_versions ORDER BY created_at ASC, strategy_version ASC"
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def list_active_versions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT * FROM strategy_versions
                WHERE status = 'active'
                ORDER BY updated_at DESC
                """).fetchall()
        return [self._version_from_row(row) for row in rows]

    def current_strategy(self) -> dict[str, Any] | None:
        active = self.list_active_versions()
        return active[0] if active else None

    def approve_strategy(self, *, strategy_version: str, approved_by: str) -> dict[str, Any]:
        normalized_approver = str(approved_by or "").strip()
        if not normalized_approver:
            raise ValueError("approved_by is required")
        current = self.get_strategy_version(strategy_version)
        now = _utc_now()
        approval_payload = {
            "strategy_version": strategy_version,
            "approved_by": normalized_approver,
            "approved_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO strategy_approvals (
                    strategy_version, approved_by, approved_at, approval_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    strategy_version,
                    normalized_approver,
                    now,
                    _json_dumps(approval_payload),
                ),
            )
            conn.execute(
                """
                UPDATE strategy_versions
                SET status = 'approved', approved_by = ?, updated_at = ?
                WHERE strategy_version = ?
                """,
                (normalized_approver, now, strategy_version),
            )
            self._insert_event(
                conn,
                strategy_version=strategy_version,
                event_type="approved",
                from_status=current["status"],
                to_status="approved",
                payload=approval_payload,
                created_at=now,
            )
        return self.get_strategy_version(strategy_version)

    def latest_approval(self, strategy_version: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM strategy_approvals
                WHERE strategy_version = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (strategy_version,),
            ).fetchone()
        if row is None:
            return None
        return self._approval_from_row(row)

    def activate_strategy(self, strategy_version: str) -> dict[str, Any]:
        target = self.get_strategy_version(strategy_version)
        approval = self.latest_approval(strategy_version)
        if approval is None:
            raise ValueError("approval record required before activation")

        now = _utc_now()
        previous_active = self.current_strategy()
        retired: list[dict[str, Any]] = []
        with self.connect() as conn:
            active_rows = conn.execute(
                """
                SELECT * FROM strategy_versions
                WHERE status = 'active' AND strategy_version != ?
                ORDER BY updated_at ASC
                """,
                (strategy_version,),
            ).fetchall()
            for row in active_rows:
                current = self._version_from_row(row)
                conn.execute(
                    """
                    UPDATE strategy_versions
                    SET status = 'retired', retired_at = ?, updated_at = ?
                    WHERE strategy_version = ?
                    """,
                    (now, now, current["strategy_version"]),
                )
                self._insert_event(
                    conn,
                    strategy_version=current["strategy_version"],
                    event_type="retired",
                    from_status=current["status"],
                    to_status="retired",
                    payload={"reason": "replaced_by_activation", "replaced_by": strategy_version},
                    created_at=now,
                )
                retired.append({**current, "status": "retired", "retired_at": now})

            conn.execute(
                """
                UPDATE strategy_versions
                SET status = 'active', approved_by = ?, retired_at = NULL, updated_at = ?
                WHERE strategy_version = ?
                """,
                (approval["approved_by"], now, strategy_version),
            )
            activation_payload = {
                "strategy_version": strategy_version,
                "approved_by": approval["approved_by"],
                "activated_at": now,
                "previous_strategy_version": (
                    previous_active.get("strategy_version") if previous_active else None
                ),
            }
            conn.execute(
                """
                INSERT INTO strategy_activation_history (
                    strategy_version, activated_at, approved_by,
                    previous_strategy_version, activation_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    strategy_version,
                    now,
                    approval["approved_by"],
                    activation_payload["previous_strategy_version"],
                    _json_dumps(activation_payload),
                ),
            )
            self._insert_event(
                conn,
                strategy_version=strategy_version,
                event_type="activated",
                from_status=target["status"],
                to_status="active",
                payload=activation_payload,
                created_at=now,
            )
        return {
            "current_strategy": self.current_strategy(),
            "retired_strategies": retired,
            "activation": self.list_activation_history()[-1],
        }

    def record_alpha_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            raise ValueError("candidate_id is required")
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alpha_candidates (candidate_id, payload_json, recorded_at)
                VALUES (?, ?, ?)
                """,
                (candidate_id, _json_dumps(candidate), now),
            )
        return {"candidate_id": candidate_id, "recorded_at": now, "payload": candidate}

    def record_alpha_evaluation(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        evaluation_id = str(evaluation.get("evaluation_id") or "").strip()
        if not evaluation_id:
            raise ValueError("evaluation_id is required")
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alpha_evaluations (evaluation_id, payload_json, recorded_at)
                VALUES (?, ?, ?)
                """,
                (evaluation_id, _json_dumps(evaluation), now),
            )
        return {"evaluation_id": evaluation_id, "recorded_at": now, "payload": evaluation}

    def list_activation_history(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_activation_history ORDER BY id ASC"
            ).fetchall()
        return [self._activation_from_row(row) for row in rows]

    def list_events(self, strategy_version: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = ""
        if strategy_version:
            where = "WHERE strategy_version = ?"
            params = (strategy_version,)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM strategy_version_events {where} ORDER BY id ASC",
                params,
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        *,
        strategy_version: str,
        event_type: str,
        from_status: str | None,
        to_status: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO strategy_version_events (
                strategy_version, event_type, from_status, to_status, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_version,
                event_type,
                from_status,
                to_status,
                _json_dumps(payload),
                created_at,
            ),
        )

    def _proposal_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "proposal_id": row["proposal_id"],
            "strategy_version": row["strategy_version"],
            "generated_at": row["generated_at"],
            "source": row["source"],
            "payload": _json_loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def _version_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "strategy_version": row["strategy_version"],
            "status": row["status"],
            "source_proposal_id": row["source_proposal_id"],
            "parameters": _json_loads(row["parameters_json"]) or {},
            "risk_limits": _json_loads(row["risk_limits_json"]) or {},
            "created_at": row["created_at"],
            "approved_by": row["approved_by"],
            "retired_at": row["retired_at"],
        }

    def _approval_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "strategy_version": row["strategy_version"],
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"],
            "payload": _json_loads(row["approval_json"]),
        }

    def _activation_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "strategy_version": row["strategy_version"],
            "activated_at": row["activated_at"],
            "approved_by": row["approved_by"],
            "previous_strategy_version": row["previous_strategy_version"],
            "payload": _json_loads(row["activation_json"]),
        }

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "strategy_version": row["strategy_version"],
            "event_type": row["event_type"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "payload": _json_loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
