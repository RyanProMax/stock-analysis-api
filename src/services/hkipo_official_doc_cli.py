from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from typing import Any, Optional, Sequence, TextIO
from zoneinfo import ZoneInfo

from .hkipo_official_doc_service import HkIpoOfficialDocService

DEFAULT_TIMEZONE = "Asia/Shanghai"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and parse readonly HK IPO official docs"
    )
    parser.add_argument("--date", help="Report date in YYYY-MM-DD")
    parser.add_argument("--ipos-json", required=True, help="Path to IPO pool JSON")
    parser.add_argument("--include-closed", action="store_true")
    parser.add_argument(
        "--cache-dir", help="Shared cache directory for downloaded documents"
    )
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
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


def _report_date(raw_date: str | None, timezone_name: str) -> str:
    if raw_date:
        return raw_date
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def _load_ipos(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(
            "--ipos-json must contain a JSON list or an object with data[]"
        )
    return [dict(item) for item in rows if isinstance(item, dict)]


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    writer: Optional[TextIO] = None,
    service: HkIpoOfficialDocService | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        report_date = _report_date(args.date, args.timezone)
        ipos = _load_ipos(args.ipos_json)
        scanner = service or HkIpoOfficialDocService()
        payload = scanner.scan(
            report_date=report_date,
            ipos=ipos,
            include_closed=bool(args.include_closed),
            cache_dir=args.cache_dir,
        )
        _emit(payload, args.pretty, writer)
        return 0 if payload.get("status") == "ok" else 1
    except Exception as exc:
        _emit(
            {
                "status": "error",
                "source": "hkipo_official_docs",
                "error": str(exc),
            },
            args.pretty,
            writer,
        )
        return 1
