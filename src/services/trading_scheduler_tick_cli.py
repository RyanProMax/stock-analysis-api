from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import hashlib
from io import StringIO
import json
import sys
from typing import Any, Optional, Sequence, TextIO
from zoneinfo import ZoneInfo

from ..repositories.trading_ledger_repository import SqliteTradingLedger
from .trading_run_once_cli import main as trading_run_once_main

DEFAULT_SOURCE = "trading_scheduler_tick"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_ACTIVE_WINDOW = "09:30-12:00,13:00-16:00"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one scheduled simulated trading tick")
    parser.add_argument("--codes", required=True, help="Comma-separated Futu codes, e.g. HK.00700")
    parser.add_argument("--strategy-version", default="threshold-v1")
    parser.add_argument("--buy-above", required=True)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--max-order-notional", type=float, default=10_000)
    parser.add_argument("--ledger-db", help="SQLite trading ledger path")
    parser.add_argument("--snapshots-json")
    parser.add_argument("--account-cash", type=float, default=1_000_000)
    parser.add_argument("--currency", default="HKD")
    parser.add_argument("--lock-name", default="trading_run_once")
    parser.add_argument("--lock-ttl-seconds", type=int, default=900)
    parser.add_argument("--disable-lock", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--active-window", default=DEFAULT_ACTIVE_WINDOW)
    parser.add_argument("--state-key")
    parser.add_argument("--now", help="ISO datetime for deterministic tests")
    parser.add_argument("--force", action="store_true")
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


def _parse_now(raw_now: str | None, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    if not raw_now:
        return datetime.now(tz)
    parsed = datetime.fromisoformat(raw_now)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _parse_windows(raw_windows: str) -> list[tuple[time, time]]:
    windows: list[tuple[time, time]] = []
    for part in str(raw_windows or "").split(","):
        item = part.strip()
        if not item:
            continue
        if "-" not in item:
            raise ValueError("--active-window must use HH:MM-HH:MM entries")
        raw_start, raw_end = item.split("-", 1)
        start = time.fromisoformat(raw_start.strip())
        end = time.fromisoformat(raw_end.strip())
        if start >= end:
            raise ValueError("--active-window start must be earlier than end")
        windows.append((start, end))
    if not windows:
        raise ValueError("--active-window must include at least one window")
    return windows


def _is_inside_window(now: datetime, windows: list[tuple[time, time]]) -> bool:
    current = now.timetz().replace(tzinfo=None)
    return any(start <= current <= end for start, end in windows)


def _next_window_start(now: datetime, windows: list[tuple[time, time]]) -> datetime:
    current = now.timetz().replace(tzinfo=None)
    for start, _end in sorted(windows):
        if current < start:
            return now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    first_start = sorted(windows)[0][0]
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(
        hour=first_start.hour,
        minute=first_start.minute,
        second=0,
        microsecond=0,
    )


def _build_state_key(args: argparse.Namespace) -> str:
    if args.state_key:
        return str(args.state_key)
    payload = {
        "codes": args.codes,
        "strategy_version": args.strategy_version,
        "buy_above": args.buy_above,
        "quantity": args.quantity,
        "max_order_notional": args.max_order_notional,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"trading-scheduler:{digest}"


def _build_run_once_args(args: argparse.Namespace) -> list[str]:
    run_args = [
        "--codes",
        args.codes,
        "--strategy-version",
        args.strategy_version,
        "--buy-above",
        args.buy_above,
        "--quantity",
        str(args.quantity),
        "--max-order-notional",
        str(args.max_order_notional),
        "--account-cash",
        str(args.account_cash),
        "--currency",
        args.currency,
        "--lock-name",
        args.lock_name,
        "--lock-ttl-seconds",
        str(args.lock_ttl_seconds),
    ]
    if args.ledger_db:
        run_args.extend(["--ledger-db", args.ledger_db])
    if args.snapshots_json:
        run_args.extend(["--snapshots-json", args.snapshots_json])
    if args.disable_lock:
        run_args.append("--disable-lock")
    return run_args


def _status_from_run_once(exit_code: int, run_payload: dict[str, Any]) -> str:
    if exit_code != 0:
        return "failed"
    if run_payload.get("status") == "skipped":
        return "skipped"
    if run_payload.get("status") == "failed":
        return "failed"
    return "ok"


def main(argv: Optional[Sequence[str]] = None, *, writer: Optional[TextIO] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        now = _parse_now(args.now, args.timezone)
        windows = _parse_windows(args.active_window)
        ledger = SqliteTradingLedger(args.ledger_db)
        state_key = _build_state_key(args)
        last_tick = ledger.get_scheduler_tick(state_key)
        schedule = {
            "state_key": state_key,
            "timezone": args.timezone,
            "active_window": args.active_window,
            "interval_seconds": args.interval_seconds,
            "now": now.isoformat(),
            "force": bool(args.force),
        }

        if not args.force and not _is_inside_window(now, windows):
            _emit(
                {
                    "status": "skipped",
                    "source": DEFAULT_SOURCE,
                    "reason": "outside_active_window",
                    "schedule": {
                        **schedule,
                        "next_run_at": _next_window_start(now, windows).isoformat(),
                    },
                },
                args.pretty,
                writer,
            )
            return 0

        if last_tick and not args.force:
            last_started_at = datetime.fromisoformat(last_tick["last_started_at"]).astimezone(
                now.tzinfo
            )
            next_due_at = last_started_at + timedelta(seconds=int(args.interval_seconds))
            if now < next_due_at:
                _emit(
                    {
                        "status": "skipped",
                        "source": DEFAULT_SOURCE,
                        "reason": "not_due",
                        "schedule": {
                            **schedule,
                            "last_started_at": last_started_at.isoformat(),
                            "next_run_at": next_due_at.isoformat(),
                        },
                    },
                    args.pretty,
                    writer,
                )
                return 0

        started_at = now.isoformat()
        run_writer = StringIO()
        exit_code = trading_run_once_main(_build_run_once_args(args), writer=run_writer)
        run_payload = json.loads(run_writer.getvalue())
        finished_at = _parse_now(None, args.timezone).isoformat()
        status = _status_from_run_once(exit_code, run_payload)
        payload = {
            "status": status,
            "source": DEFAULT_SOURCE,
            "schedule": schedule,
            "run_once": run_payload,
        }
        if status != "skipped":
            ledger.record_scheduler_tick(
                state_key,
                due_at=now.isoformat(),
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                payload=payload,
            )
        _emit(payload, args.pretty, writer)
        return 0 if exit_code == 0 else exit_code
    except ValueError as exc:
        _emit({"status": "failed", "source": DEFAULT_SOURCE, "error": str(exc)}, False, writer)
        return 2
    except Exception as exc:
        _emit(
            {"status": "failed", "source": DEFAULT_SOURCE, "error": f"调度 tick 执行失败: {exc}"},
            False,
            writer,
        )
        return 1
