from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence, TextIO

from .alpha_scan_service import AlphaScanService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan local market data for alpha candidates")
    parser.add_argument("--market", default="cn", choices=["cn", "us"])
    parser.add_argument(
        "--universe",
        default="all",
        choices=["all", "stock", "etf", "watchlist"],
    )
    parser.add_argument("--symbols", help="Comma-separated explicit symbols")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--as-of")
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
    service: Optional[AlphaScanService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    scan_service = service or AlphaScanService()
    try:
        payload = scan_service.scan(
            market=args.market,
            universe=args.universe,
            symbols=args.symbols,
            top=args.top,
            as_of=args.as_of,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit({"status": "failed", "source": "alpha_scan", "error": str(exc)}, False, writer)
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "alpha_scan",
                "error": f"alpha_scan 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
