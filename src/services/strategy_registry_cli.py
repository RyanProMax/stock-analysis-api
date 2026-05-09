from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence, TextIO

from ..repositories.strategy_registry_repository import SqliteStrategyRegistry
from .strategy_registry_service import StrategyRegistryService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage governed strategy proposals")
    parser.add_argument("--registry-db", help="SQLite strategy registry path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose", help="Store a candidate strategy proposal")
    propose.add_argument("--proposal-json", required=True)
    propose.add_argument("--pretty", action="store_true")

    approve = subparsers.add_parser("approve", help="Record human approval")
    approve.add_argument("--strategy-version", required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--pretty", action="store_true")

    activate = subparsers.add_parser("activate", help="Activate an approved strategy")
    activate.add_argument("--strategy-version", required=True)
    activate.add_argument("--pretty", action="store_true")

    current = subparsers.add_parser("current", help="Show current active strategy")
    current.add_argument("--pretty", action="store_true")

    list_versions = subparsers.add_parser("list", help="List registered strategy versions")
    list_versions.add_argument("--pretty", action="store_true")

    record_verdict = subparsers.add_parser(
        "record-verdict", help="Append an independent judge verdict"
    )
    record_verdict.add_argument("--verdict-json", required=True)
    record_verdict.add_argument("--pretty", action="store_true")
    return parser


def _load_json(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")
    return payload


def _emit(payload: dict, pretty: bool, writer: Optional[TextIO]) -> None:
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
    argv: Optional[Sequence[str]] = None,
    *,
    writer: Optional[TextIO] = None,
    service: Optional[StrategyRegistryService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    registry_service = service or StrategyRegistryService(
        registry=SqliteStrategyRegistry(args.registry_db)
    )
    pretty = bool(getattr(args, "pretty", False))
    try:
        if args.command == "propose":
            payload = registry_service.propose(_load_json(args.proposal_json))
        elif args.command == "approve":
            payload = registry_service.approve(
                strategy_version=args.strategy_version,
                approved_by=args.approved_by,
            )
        elif args.command == "activate":
            payload = registry_service.activate(strategy_version=args.strategy_version)
        elif args.command == "current":
            payload = registry_service.current()
        elif args.command == "list":
            payload = registry_service.list_versions()
        elif args.command == "record-verdict":
            payload = registry_service.record_judge_verdict(_load_json(args.verdict_json))
        else:
            raise ValueError(f"unsupported command: {args.command}")
        _emit(payload, pretty, writer)
        return 0
    except (KeyError, ValueError) as exc:
        _emit({"status": "failed", "source": "strategy_registry", "error": str(exc)}, False, writer)
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "strategy_registry",
                "error": f"strategy_registry 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
