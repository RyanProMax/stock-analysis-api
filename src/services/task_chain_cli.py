from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from typing import Any, Optional, Sequence, TextIO
import uuid

from ..repositories.task_chain_repository import SqliteTaskChainRepository
from .task_chain_service import TASK_TYPES, TaskChainService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run persisted alpha task-chain ticks")
    parser.add_argument("--task-db", help="SQLite task-chain DB path")
    parser.add_argument("--pretty", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser(
        "bootstrap", help="Create an initial pending task"
    )
    bootstrap.add_argument("--task-type", required=True, choices=sorted(TASK_TYPES))
    bootstrap.add_argument("--due-at")
    bootstrap.add_argument("--payload-json", default="{}")
    bootstrap.add_argument("--parent-task-id")

    tick = subparsers.add_parser("tick", help="Run one due task with a lease")
    tick.add_argument("--now")
    tick.add_argument("--owner-id")
    tick.add_argument("--lease-ttl-seconds", type=int, default=900)
    return parser


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_payload(raw: str) -> dict[str, Any]:
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("--payload-json must be a JSON object")
    return payload


def _emit(payload: dict[str, Any], pretty: bool, writer: Optional[TextIO]) -> None:
    output = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=2 if pretty else None,
        separators=(",", ": ") if pretty else (",", ":"),
    )
    target = writer or sys.stdout
    target.write(output)
    target.write("\n")


def main(
    argv: Optional[Sequence[str]] = None, *, writer: Optional[TextIO] = None
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    service = TaskChainService(SqliteTaskChainRepository(args.task_db))

    try:
        if args.command == "bootstrap":
            payload = service.bootstrap(
                task_type=args.task_type,
                due_at=args.due_at or _now_iso(),
                payload=_parse_payload(args.payload_json),
                parent_task_id=args.parent_task_id,
            )
            _emit(payload, args.pretty, writer)
            return 0

        payload = service.tick(
            now=args.now or _now_iso(),
            owner_id=args.owner_id or f"task-chain-{uuid.uuid4()}",
            lease_ttl_seconds=args.lease_ttl_seconds,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit(
            {"status": "failed", "source": "task_chain", "error": str(exc)},
            False,
            writer,
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "task_chain",
                "error": f"task_chain 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
