from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from typing import Optional, Sequence, TextIO

from ..api.schemas import StandardResponse
from .stock_analyze_service import StockAnalyzeService, stock_analyze_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the unified stock analyze workflow.")
    parser.add_argument("--market", choices=["cn", "us"], default="cn")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--mode", choices=["base", "full"], default="base")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    writer: Optional[TextIO] = None,
    service: Optional[StockAnalyzeService] = None,
) -> dict:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    symbols = [text.strip().upper() for text in str(args.symbols or "").split(",") if text.strip()]
    deduped_symbols: list[str] = []
    for symbol in symbols:
        if symbol not in deduped_symbols:
            deduped_symbols.append(symbol)
    if not deduped_symbols:
        raise SystemExit("`--symbols` must contain at least one valid symbol")

    analyze_service = service or stock_analyze_service
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            payload = analyze_service.analyze(
                market=args.market,
                symbols=deduped_symbols,
                start_date=args.start_date,
                end_date=args.end_date,
                mode=args.mode,
            )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    response_payload = StandardResponse(status_code=200, data=payload, err_msg=None).model_dump()

    output = json.dumps(
        response_payload,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        separators=(",", ": ") if args.pretty else (",", ":"),
    )
    target = writer or sys.stdout
    target.write(output)
    target.write("\n")
    return response_payload
