from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence, TextIO

from .research_snapshot_service import ResearchSnapshotService, research_snapshot_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll Tushare-first research snapshot data for CN stocks."
    )
    parser.add_argument("--market", choices=["cn", "us"], default="cn")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    writer: Optional[TextIO] = None,
    service: Optional[ResearchSnapshotService] = None,
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

    snapshot_service = service or research_snapshot_service
    try:
        payload = snapshot_service.poll_snapshot(
            market=args.market,
            symbols=deduped_symbols,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    output = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        separators=(",", ": ") if args.pretty else (",", ":"),
    )
    target = writer or sys.stdout
    target.write(output)
    target.write("\n")
    return payload
