from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence, TextIO

from .alpha_backtest_service import AlphaBacktestService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest a local alpha top-N portfolio")
    parser.add_argument("--market", default="cn", choices=["cn", "us", "hk"])
    parser.add_argument(
        "--universe",
        default="all",
        choices=["all", "stock", "etf", "watchlist"],
    )
    parser.add_argument("--symbols", help="Comma-separated explicit symbols")
    parser.add_argument("--factor", default="momentum_20d")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--holding-period", type=int, default=1)
    parser.add_argument("--cost-bps", type=float)
    parser.add_argument("--include-details", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


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
    service: Optional[AlphaBacktestService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    backtest_service = service or AlphaBacktestService()
    try:
        payload = backtest_service.backtest(
            market=args.market,
            universe=args.universe,
            symbols=args.symbols,
            factor=args.factor,
            start=args.start,
            end=args.end,
            top_n=args.top_n,
            holding_period=args.holding_period,
            cost_bps=args.cost_bps,
            include_details=args.include_details,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit({"status": "failed", "source": "alpha_backtest", "error": str(exc)}, False, writer)
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "alpha_backtest",
                "error": f"alpha_backtest 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
