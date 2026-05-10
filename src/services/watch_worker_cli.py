from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence, TextIO

from ..repositories.strategy_registry_repository import SqliteStrategyRegistry
from ..repositories.trading_ledger_repository import SqliteTradingLedger
from .watch_worker_service import (
    DEFAULT_ACTIVE_WINDOW,
    DEFAULT_TIMEZONE,
    WatchWorkerService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one alpha watch worker tick")
    parser.add_argument("--registry-db", help="SQLite strategy registry path")
    parser.add_argument("--state-db", help="SQLite worker state path")
    parser.add_argument("--state-key", default="alpha-watch-worker")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--active-window", default=DEFAULT_ACTIVE_WINDOW)
    parser.add_argument("--now")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--market", choices=["cn", "us", "hk"])
    parser.add_argument("--universe", choices=["all", "stock", "etf", "watchlist"])
    parser.add_argument("--symbols")
    parser.add_argument("--factor")
    parser.add_argument("--date")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--forward-windows")
    parser.add_argument("--top", type=int)
    parser.add_argument("--include-details", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _parse_forward_windows(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    windows: list[int] = []
    for part in str(raw or "").split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        window = int(cleaned)
        if window <= 0:
            raise ValueError("forward window must be positive")
        windows.append(window)
    if not windows:
        raise ValueError("forward_windows must not be empty")
    return windows


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
    service: Optional[WatchWorkerService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    worker = service or WatchWorkerService(
        strategy_registry=SqliteStrategyRegistry(args.registry_db),
        state_repository=SqliteTradingLedger(args.state_db),
    )
    try:
        payload = worker.tick(
            state_key=args.state_key,
            interval_seconds=args.interval_seconds,
            timezone_name=args.timezone,
            active_window=args.active_window,
            now=args.now,
            force=args.force,
            market=args.market,
            universe=args.universe,
            symbols=args.symbols,
            factor=args.factor,
            date=args.date,
            start=args.start,
            end=args.end,
            forward_windows=_parse_forward_windows(args.forward_windows),
            top=args.top,
            include_details=args.include_details,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit({"status": "failed", "source": "watch_worker_tick", "error": str(exc)}, False, writer)
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "watch_worker_tick",
                "error": f"watch_worker_tick 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
