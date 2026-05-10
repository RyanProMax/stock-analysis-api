from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence, TextIO

from .alpha_daily_report_service import AlphaDailyReportService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a summary-only alpha daily report")
    parser.add_argument("--market", default="cn", choices=["cn", "us", "hk"])
    parser.add_argument(
        "--universe",
        default="all",
        choices=["all", "stock", "etf", "watchlist"],
    )
    parser.add_argument("--symbols", help="Comma-separated explicit symbols")
    parser.add_argument("--factor", default="momentum_20d")
    parser.add_argument("--date")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--forward-windows", default="1,5,20")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--quantiles", type=int, default=5)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--strategy-version")
    parser.add_argument("--include-details", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _parse_forward_windows(raw: str) -> list[int]:
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
    service: Optional[AlphaDailyReportService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    report_service = service or AlphaDailyReportService()
    try:
        payload = report_service.report(
            market=args.market,
            universe=args.universe,
            symbols=args.symbols,
            factor=args.factor,
            date=args.date,
            start=args.start,
            end=args.end,
            forward_windows=_parse_forward_windows(args.forward_windows),
            top=args.top,
            quantiles=args.quantiles,
            cost_bps=args.cost_bps,
            strategy_version=args.strategy_version,
            include_details=args.include_details,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit(
            {"status": "failed", "source": "alpha_daily_report", "error": str(exc)}, False, writer
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "alpha_daily_report",
                "error": f"alpha_daily_report 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
