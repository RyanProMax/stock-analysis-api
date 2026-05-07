from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from typing import Any, Optional, Sequence, TextIO
from zoneinfo import ZoneInfo

from ..repositories.trading_ledger_repository import SqliteTradingLedger
from .trading_ledger_analysis import build_daily_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize simulated trading ledger for one day")
    parser.add_argument("--ledger-db", help="SQLite trading ledger path")
    parser.add_argument("--date", help="Trading date in YYYY-MM-DD; defaults to today")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--pretty", action="store_true")
    return parser


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


def _target_date(raw_date: str | None, timezone_name: str):
    if raw_date:
        return datetime.fromisoformat(raw_date).date()
    return datetime.now(ZoneInfo(timezone_name)).date()


def main(argv: Optional[Sequence[str]] = None, *, writer: Optional[TextIO] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        target_date = _target_date(args.date, args.timezone)
        ledger = SqliteTradingLedger(args.ledger_db)
        payload = build_daily_summary(
            ledger,
            target_date=target_date,
            timezone_name=args.timezone,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit(
            {"status": "failed", "source": "trading_daily_summary", "error": str(exc)},
            False,
            writer,
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "trading_daily_summary",
                "error": f"盘后总结失败: {exc}",
            },
            False,
            writer,
        )
        return 1
