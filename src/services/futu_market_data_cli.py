from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable, TextIO

from ..data_provider.sources.futu import (
    FutuMarketDataProvider,
    FutuOpenDGateway,
    to_jsonable,
)


SOURCE = "futu_opend"


def _write_payload(writer: TextIO, payload: dict[str, Any]) -> None:
    writer.write(json.dumps(to_jsonable(payload), ensure_ascii=False))
    writer.write("\n")


def _parse_codes(raw_codes: str | Iterable[str]) -> list[str]:
    if isinstance(raw_codes, str):
        candidates = raw_codes.split(",")
    else:
        candidates = list(raw_codes)
    return [str(code).strip() for code in candidates if str(code).strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal Futu/OpenD market data CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    global_state = subparsers.add_parser("global-state", help="Get OpenD global state")
    global_state.add_argument("--json", action="store_true", dest="output_json")

    ipo_list = subparsers.add_parser("ipo-list", help="Get IPO list")
    ipo_list.add_argument("--market", choices=["HK", "US", "SH", "SZ"], default="HK")
    ipo_list.add_argument("--json", action="store_true", dest="output_json")

    kline = subparsers.add_parser("kline", help="Get historical kline")
    kline.add_argument("--code", required=True)
    kline.add_argument(
        "--ktype",
        choices=["1m", "3m", "5m", "15m", "30m", "60m", "1d", "1w", "1M", "1Q", "1Y"],
        default="1d",
    )
    kline.add_argument("--num", type=int, default=1000)
    kline.add_argument("--start")
    kline.add_argument("--end")
    kline.add_argument("--max-page", type=int)
    kline.add_argument("--rehab", choices=["none", "forward", "backward"], default="forward")
    kline.add_argument("--session", choices=["NONE", "RTH", "ETH", "ALL"], default="NONE")
    kline.add_argument("--json", action="store_true", dest="output_json")

    snapshot = subparsers.add_parser("snapshot", help="Get market snapshots")
    snapshot.add_argument("--codes", required=True)
    snapshot.add_argument("--json", action="store_true", dest="output_json")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    writer: TextIO | None = None,
    gateway: Any | None = None,
) -> int:
    writer = writer or sys.stdout
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        gateway = gateway or FutuOpenDGateway()
        if args.command == "global-state":
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "data": gateway.get_global_state(),
                },
            )
            return 0

        if args.command == "ipo-list":
            market = str(args.market).strip().upper()
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "market": market,
                    "data": gateway.get_ipo_list(market),
                },
            )
            return 0

        if args.command == "kline":
            code = str(args.code).strip().upper()
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "code": code,
                    "ktype": args.ktype,
                    "data": gateway.request_history_kline(
                        code,
                        ktype=args.ktype,
                        start=args.start,
                        end=args.end,
                        max_count=args.num,
                        rehab=args.rehab,
                        session=args.session,
                        max_page=args.max_page,
                    ),
                },
            )
            return 0

        if args.command == "snapshot":
            codes = _parse_codes(args.codes)
            provider = FutuMarketDataProvider(gateway=gateway)
            snapshots = provider.get_market_snapshots(codes)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "request": {"codes": codes, "count": len(codes)},
                    "data": [snapshot.to_dict() for snapshot in snapshots],
                },
            )
            return 0

        _write_payload(
            writer,
            {
                "status": "failed",
                "source": SOURCE,
                "error": f"unsupported command: {args.command}",
            },
        )
        return 2
    except Exception as exc:
        _write_payload(
            writer,
            {
                "status": "failed",
                "source": SOURCE,
                "error": str(exc),
            },
        )
        return 1
