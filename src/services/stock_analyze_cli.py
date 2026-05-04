from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional, Sequence, TextIO

from ..api.schemas import StandardResponse
from .stock_analyze_service import StockAnalyzeService, stock_analyze_service
from .symbol_catalog_service import symbol_catalog_service


CN_SYMBOL_PATTERN = re.compile(r"\d{6}")
US_SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the unified stock analyze workflow.")
    parser.add_argument("--market", choices=["cn", "us"], default="cn")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--mode", choices=["base", "full"], default="base")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _normalize_explicit_symbol(raw_symbol: str, market: str) -> str | None:
    symbol = str(raw_symbol or "").strip().upper()
    if not symbol:
        return None

    if market == "cn":
        if CN_SYMBOL_PATTERN.fullmatch(symbol):
            return symbol
        if symbol.startswith(("SH.", "SZ.", "BJ.")) or symbol.endswith((".SH", ".SZ", ".BJ")):
            digits = re.sub(r"\D", "", symbol)
            return digits if CN_SYMBOL_PATTERN.fullmatch(digits) else None
        return None

    if symbol.startswith("US."):
        symbol = symbol[3:]
    exchange_match = re.fullmatch(r"(NASDAQ|NYSE|AMEX):([A-Z][A-Z0-9.-]{0,9})", symbol)
    if exchange_match:
        symbol = exchange_match.group(2)
    return symbol if US_SYMBOL_PATTERN.fullmatch(symbol) else None


def _needs_identity_resolution(raw_symbol: str, market: str) -> bool:
    if _normalize_explicit_symbol(raw_symbol, market):
        return False
    return any("\u4e00" <= char <= "\u9fff" for char in str(raw_symbol or ""))


def _candidate_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("symbol") or "").strip().upper(),
        str(row.get("ts_code") or "").strip().upper(),
        str(row.get("name") or "").strip().upper(),
        str(row.get("cnspell") or "").strip().upper(),
    )


def _is_exact_identity_match(keyword: str, row: dict[str, Any]) -> bool:
    normalized_keyword = str(keyword or "").strip().upper()
    return normalized_keyword in _candidate_key(row)


def _candidate_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "ts_code": row.get("ts_code"),
        "name": row.get("name"),
        "market": row.get("market"),
        "exchange": row.get("exchange"),
    }


def _resolve_one_symbol(
    raw_symbol: str,
    *,
    market: str,
    catalog: Any,
) -> tuple[str | None, dict[str, Any] | None]:
    explicit_symbol = _normalize_explicit_symbol(raw_symbol, market)
    if explicit_symbol:
        return explicit_symbol, None
    if not _needs_identity_resolution(raw_symbol, market):
        return str(raw_symbol or "").strip().upper(), None

    matches = catalog.search_symbols(raw_symbol, market=market)
    candidates = [_candidate_payload(match) for match in matches[:10]]
    if not matches:
        return None, {
            "requested_symbol": raw_symbol,
            "code": "identity_not_found",
            "message": f"Unable to resolve a unique listed symbol for `{raw_symbol}`.",
            "candidates": [],
        }

    exact_matches = [match for match in matches if _is_exact_identity_match(raw_symbol, match)]
    selected: dict[str, Any] | None = None
    if len(exact_matches) == 1:
        selected = exact_matches[0]
    elif len(matches) == 1:
        selected = matches[0]

    if selected is None:
        return None, {
            "requested_symbol": raw_symbol,
            "code": "identity_conflict",
            "message": f"Multiple listed symbols can match `{raw_symbol}`; please provide an exact code.",
            "candidates": candidates,
        }

    resolved_symbol = str(selected.get("symbol") or "").strip().upper()
    if not resolved_symbol:
        return None, {
            "requested_symbol": raw_symbol,
            "code": "identity_not_found",
            "message": f"Resolved row for `{raw_symbol}` has no usable symbol.",
            "candidates": candidates,
        }
    return resolved_symbol, None


def _empty_identity() -> dict[str, Any]:
    return {
        "common": {"ts_code": None, "name": None, "list_date": None, "delist_date": None},
        "cn_specific": {
            "symbol": None,
            "exchange": None,
            "list_status": None,
            "area": None,
            "industry": None,
            "market": None,
        },
        "us_specific": {
            "ts_code": None,
            "name": None,
            "enname": None,
            "classify": None,
            "list_date": None,
            "delist_date": None,
        },
    }


def _identity_failed_item(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "requested_symbol": error["requested_symbol"],
        "status": "failed",
        "error": {
            "code": error["code"],
            "message": error["message"],
            "candidates": error["candidates"],
        },
        "info": _empty_identity(),
        "meta": {
            "modules": {
                "identity_resolution": {
                    "status": "failed",
                    "error": error["message"],
                    "attempted_sources": ["symbol_catalog"],
                }
            }
        },
    }


def _identity_failure_payload(
    *,
    market: str,
    raw_symbols: Sequence[str],
    start_date: str | None,
    end_date: str | None,
    mode: str,
    errors: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "failed",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "source": StockAnalyzeService.TOP_LEVEL_SOURCE,
        "market": market,
        "strategy": StockAnalyzeService.STRATEGY,
        "request": {
            "market": market,
            "symbols": list(raw_symbols),
            "start_date": start_date,
            "end_date": end_date,
            "mode": mode,
        },
        "items": [_identity_failed_item(error) for error in errors],
    }


def _resolve_cli_symbols(
    raw_symbols: Sequence[str],
    *,
    market: str,
    catalog: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    resolved_symbols: list[str] = []
    errors: list[dict[str, Any]] = []
    for raw_symbol in raw_symbols:
        resolved_symbol, error = _resolve_one_symbol(
            raw_symbol,
            market=market,
            catalog=catalog,
        )
        if error is not None:
            errors.append(error)
            continue
        if resolved_symbol and resolved_symbol not in resolved_symbols:
            resolved_symbols.append(resolved_symbol)
    return resolved_symbols, errors


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    writer: Optional[TextIO] = None,
    service: Optional[StockAnalyzeService] = None,
    symbol_catalog: Any = None,
) -> dict:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    raw_symbols = [text.strip() for text in str(args.symbols or "").split(",") if text.strip()]
    if not raw_symbols:
        raise SystemExit("`--symbols` must contain at least one valid symbol")

    deduped_raw_symbols: list[str] = []
    for symbol in raw_symbols:
        if symbol not in deduped_raw_symbols:
            deduped_raw_symbols.append(symbol)

    catalog = symbol_catalog or symbol_catalog_service
    deduped_symbols, identity_errors = _resolve_cli_symbols(
        deduped_raw_symbols,
        market=args.market,
        catalog=catalog,
    )
    if identity_errors:
        payload = _identity_failure_payload(
            market=args.market,
            raw_symbols=deduped_raw_symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            mode=args.mode,
            errors=identity_errors,
        )
    else:
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
