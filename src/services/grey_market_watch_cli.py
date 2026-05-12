from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional, Sequence, TextIO
from zoneinfo import ZoneInfo

from ..repositories.trading_ledger_repository import SqliteTradingLedger
from .grey_market_watch_service import GreyMarketWatchService, parse_providers

DEFAULT_SOURCE = "grey_market_watch_tick"
ONCE_SOURCE = "grey_market_watch_once"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_ACTIVE_WINDOW = "16:15-18:30"
DEFAULT_STATE_DB_NAME = "grey_market_watch.sqlite"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one readonly HK grey-market watch tick")
    parser.add_argument("--code", required=True, help="Futu HK code, e.g. HK.02618")
    parser.add_argument("--name", default="")
    parser.add_argument("--issue-price", type=float)
    parser.add_argument("--providers", default="futu,tiger,fosun")
    parser.add_argument("--order-book-depth", type=int, default=5)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one query without reading or writing scheduler tick state",
    )
    parser.add_argument("--state-db", help="SQLite state DB path for scheduler tick state")
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--active-window", default=DEFAULT_ACTIVE_WINDOW)
    parser.add_argument("--state-key")
    parser.add_argument("--now", help="ISO datetime for deterministic tests")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true", dest="output_json")
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


def _build_state_key(args: argparse.Namespace, providers: list[str]) -> str:
    if args.state_key:
        return str(args.state_key)
    payload = {
        "code": str(args.code).strip().upper(),
        "providers": providers,
        "issue_price": args.issue_price,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"grey-market-watch:{digest}"


def _schedule_payload(args: argparse.Namespace, state_key: str, now: datetime) -> dict[str, Any]:
    return {
        "mode": "once" if args.once else "tick",
        "state_key": state_key,
        "timezone": args.timezone,
        "active_window": args.active_window,
        "interval_seconds": args.interval_seconds,
        "now": now.isoformat(),
        "force": bool(args.force),
    }


def _state_db_path(raw_state_db: str | None) -> Path | str:
    if raw_state_db:
        return raw_state_db
    cache_root = Path(os.environ.get("CACHE_DIR") or ".cache")
    return cache_root / DEFAULT_STATE_DB_NAME


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    writer: Optional[TextIO] = None,
    service: GreyMarketWatchService | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        providers = parse_providers(args.providers)
        now = _parse_now(args.now, args.timezone)
        windows = _parse_windows(args.active_window)
        state_key = _build_state_key(args, providers)
        schedule = _schedule_payload(args, state_key, now)
        source = ONCE_SOURCE if args.once else DEFAULT_SOURCE

        if not args.force and not _is_inside_window(now, windows):
            _emit(
                {
                    "status": "skipped",
                    "source": source,
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

        if args.once:
            watch_service = service or GreyMarketWatchService(timezone_name=args.timezone)
            watch_payload = watch_service.query(
                code=args.code,
                name=args.name or None,
                issue_price=args.issue_price,
                providers=providers,
                order_book_depth=max(0, int(args.order_book_depth)),
            )
            payload = {
                "status": watch_payload.get("status", "failed"),
                "source": ONCE_SOURCE,
                "schedule": schedule,
                "watch": watch_payload,
            }
            _emit(payload, args.pretty, writer)
            return 0 if payload["status"] == "ok" else 1

        ledger = SqliteTradingLedger(_state_db_path(args.state_db))
        last_tick = ledger.get_scheduler_tick(state_key)

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
        watch_service = service or GreyMarketWatchService(timezone_name=args.timezone)
        watch_payload = watch_service.query(
            code=args.code,
            name=args.name or None,
            issue_price=args.issue_price,
            providers=providers,
            order_book_depth=max(0, int(args.order_book_depth)),
        )
        finished_at = _parse_now(None, args.timezone).isoformat()
        payload = {
            "status": watch_payload.get("status", "failed"),
            "source": DEFAULT_SOURCE,
            "schedule": schedule,
            "watch": watch_payload,
        }
        ledger.record_scheduler_tick(
            state_key,
            due_at=now.isoformat(),
            started_at=started_at,
            finished_at=finished_at,
            status=str(payload["status"]),
            payload=payload,
        )
        _emit(payload, args.pretty, writer)
        return 0 if payload["status"] == "ok" else 1
    except ValueError as exc:
        _emit({"status": "failed", "source": DEFAULT_SOURCE, "error": str(exc)}, False, writer)
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": DEFAULT_SOURCE,
                "error": f"灰市/暗盘调度 tick 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
