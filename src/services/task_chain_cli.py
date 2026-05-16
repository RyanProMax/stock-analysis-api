from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
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

    handoff = subparsers.add_parser("handoff", help="Manage agent handoff queue")
    handoff_subparsers = handoff.add_subparsers(dest="handoff_command", required=True)

    handoff_list = handoff_subparsers.add_parser("list", help="List handoffs")
    handoff_list.add_argument(
        "status",
        nargs="?",
        choices=["pending", "claimed", "completed", "failed"],
    )

    handoff_claim = handoff_subparsers.add_parser("claim", help="Claim a pending handoff")
    handoff_claim.add_argument("handoff_id")
    handoff_claim.add_argument("--claimed-by", required=True)
    handoff_claim.add_argument("--now")

    handoff_complete = handoff_subparsers.add_parser(
        "complete", help="Complete a handoff"
    )
    handoff_complete.add_argument("handoff_id")
    result_group = handoff_complete.add_mutually_exclusive_group(required=True)
    result_group.add_argument("--result-json")
    result_group.add_argument("--result-file")
    handoff_complete.add_argument("--now")

    handoff_fail = handoff_subparsers.add_parser("fail", help="Mark a handoff failed")
    handoff_fail.add_argument("handoff_id")
    handoff_fail.add_argument("--error", required=True)
    handoff_fail.add_argument("--now")
    return parser


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_payload(raw: str) -> dict[str, Any]:
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("--payload-json must be a JSON object")
    return payload


def _parse_result(args: argparse.Namespace) -> dict[str, Any]:
    if args.result_file:
        raw = Path(args.result_file).read_text(encoding="utf-8")
    else:
        raw = args.result_json or "{}"
    result = json.loads(raw or "{}")
    if not isinstance(result, dict):
        raise ValueError("handoff result must be a JSON object")
    return result


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
    repository = SqliteTaskChainRepository(args.task_db)
    service = TaskChainService(repository)

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

        if args.command == "handoff":
            if args.handoff_command == "list":
                _emit(
                    {
                        "status": "ok",
                        "source": "task_chain_handoff",
                        "handoffs": repository.list_agent_handoffs(status=args.status),
                    },
                    args.pretty,
                    writer,
                )
                return 0

            if args.handoff_command == "claim":
                handoff = repository.claim_agent_handoff(
                    handoff_id=args.handoff_id,
                    claimed_by=args.claimed_by,
                    claimed_at=args.now or _now_iso(),
                )
                if handoff is None:
                    raise ValueError("handoff is not pending or does not exist")
                _emit(
                    {
                        "status": "ok",
                        "source": "task_chain_handoff",
                        "handoff": handoff,
                    },
                    args.pretty,
                    writer,
                )
                return 0

            if args.handoff_command == "complete":
                handoff = repository.complete_agent_handoff(
                    handoff_id=args.handoff_id,
                    result=_parse_result(args),
                    completed_at=args.now or _now_iso(),
                )
                if handoff is None:
                    raise ValueError("handoff cannot be completed or does not exist")
                _emit(
                    {
                        "status": "ok",
                        "source": "task_chain_handoff",
                        "handoff": handoff,
                    },
                    args.pretty,
                    writer,
                )
                return 0

            if args.handoff_command == "fail":
                handoff = repository.fail_agent_handoff(
                    handoff_id=args.handoff_id,
                    error=args.error,
                    failed_at=args.now or _now_iso(),
                )
                if handoff is None:
                    raise ValueError("handoff cannot be failed or does not exist")
                _emit(
                    {
                        "status": "ok",
                        "source": "task_chain_handoff",
                        "handoff": handoff,
                    },
                    args.pretty,
                    writer,
                )
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
