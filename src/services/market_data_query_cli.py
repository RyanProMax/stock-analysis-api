"""CLI adapter for stateless market-data queries."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from typing import Any, Sequence, TextIO

from .daily_market_pack_service import (
    DailyMarketPackService,
    SCHEMA_VERSION,
    SOURCE,
    daily_market_pack_service,
)


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--cutoff-at must include a timezone")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal stateless market-data query CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily_pack = subparsers.add_parser(
        "daily-pack",
        help="Collect the fixed CN/US daily report market pack",
    )
    daily_pack.add_argument("--cutoff-at", required=True, type=_parse_datetime)
    daily_pack.add_argument("--persistence", choices=["none"], default="none")
    daily_pack.add_argument("--pretty", action="store_true")
    return parser


def _write_payload(writer: TextIO, payload: dict[str, Any], *, pretty: bool) -> None:
    writer.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2 if pretty else None,
        )
    )
    writer.write("\n")
    writer.flush()


def main(
    argv: Sequence[str] | None = None,
    *,
    writer: TextIO = sys.stdout,
    service: DailyMarketPackService | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    selected_service = service or daily_market_pack_service
    try:
        payload = selected_service.collect(cutoff_at=args.cutoff_at)
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "source": SOURCE,
            "request": {
                "operation": "daily_market_pack",
                "cutoff_at": args.cutoff_at.isoformat(),
                "persistence": args.persistence,
            },
            "summary": {"requested": 0, "succeeded": 0, "failed": 1},
            "data": {"markets": [], "failures": []},
            "error": f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:500],
        }
        _write_payload(writer, payload, pretty=args.pretty)
        return 1

    _write_payload(writer, payload, pretty=args.pretty)
    return 0
