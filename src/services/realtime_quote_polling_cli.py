from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from typing import Optional, Sequence, TextIO

from .realtime_quote_polling_service import (
    RealtimeQuotePollingService,
    realtime_quote_polling_service,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量查询股票 / ETF 最新日内行情")
    parser.add_argument(
        "--symbols",
        required=True,
        help="逗号分隔的证券代码，例如 600000,510300,159915",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="格式化输出 JSON，便于人工阅读",
    )
    parser.add_argument(
        "--fast-realtime",
        action="store_true",
        help="使用低延迟实时行情路径，跳过 Tushare Pro 元数据和 quotation 查询。",
    )
    return parser


def _emit(payload: dict, pretty: bool, writer: Optional[TextIO]) -> None:
    output = json.dumps(
        payload,
        ensure_ascii=False,
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
    service: Optional[RealtimeQuotePollingService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    polling_service = service or realtime_quote_polling_service
    requested_symbols = polling_service.parse_symbols(args.symbols)
    if not requested_symbols:
        payload = {
            "status": "failed",
            "error": "--symbols 不能为空",
            "request": {"symbols": [], "count": 0},
        }
        _emit(payload, args.pretty, writer)
        return 2

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            payload = polling_service.poll(
                requested_symbols,
                fast_realtime=args.fast_realtime,
            )
        _emit(payload, args.pretty, writer)
        return 0
    except RuntimeError as exc:
        payload = {
            "status": "failed",
            "error": str(exc),
            "request": {
                "symbols": requested_symbols,
                "count": len(requested_symbols),
            },
        }
        _emit(payload, args.pretty, writer)
        return 3
    except Exception as exc:
        payload = {
            "status": "failed",
            "error": f"poll_realtime_quotes 执行失败: {exc}",
            "request": {
                "symbols": requested_symbols,
                "count": len(requested_symbols),
            },
        }
        _emit(payload, args.pretty, writer)
        return 1
