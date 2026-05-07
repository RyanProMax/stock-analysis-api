from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Optional, Sequence, TextIO

from ..data_provider.sources.futu import FutuOpenDGateway


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest a fixed-threshold simulated strategy")
    parser.add_argument("--codes", required=True, help="Comma-separated Futu codes, e.g. HK.00700")
    parser.add_argument("--strategy-version", default="threshold-v1")
    parser.add_argument("--buy-above", required=True)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--max-order-notional", type=float, default=10_000)
    parser.add_argument("--kline-json", help="Inline JSON array or a file path")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--ktype", default="1d")
    parser.add_argument("--rehab", default="none")
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


def _parse_codes(raw: str) -> list[str]:
    return [part.strip().upper() for part in str(raw or "").split(",") if part.strip()]


def _parse_buy_above(raw: str) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for part in str(raw or "").split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError("--buy-above must use code=price entries")
        code, price = item.split("=", 1)
        code = code.strip().upper()
        if not code:
            raise ValueError("--buy-above contains empty code")
        thresholds[code] = float(price)
    if not thresholds:
        raise ValueError("--buy-above must include at least one code=price entry")
    return thresholds


def _load_kline_json(raw: str) -> list[dict[str, Any]]:
    content = raw
    if not raw.lstrip().startswith("["):
        raw_path = Path(raw).expanduser()
        if raw_path.is_file():
            content = raw_path.read_text(encoding="utf-8")
    decoded = json.loads(content)
    if not isinstance(decoded, list):
        raise ValueError("--kline-json must decode to a JSON array")
    return [dict(item) for item in decoded if isinstance(item, dict)]


def _fetch_futu_klines(args: argparse.Namespace, codes: list[str]) -> list[dict[str, Any]]:
    gateway = FutuOpenDGateway()
    rows: list[dict[str, Any]] = []
    for code in codes:
        for row in gateway.request_history_kline(
            code,
            ktype=args.ktype,
            start=args.start,
            end=args.end,
            rehab=args.rehab,
        ):
            row = dict(row)
            row.setdefault("code", code)
            rows.append(row)
    return rows


def _row_code(row: dict[str, Any]) -> str:
    return str(row.get("code") or row.get("stock_code") or "").strip().upper()


def _row_time(row: dict[str, Any]) -> str:
    return str(row.get("time_key") or row.get("date") or row.get("time") or "")


def _row_close(row: dict[str, Any]) -> float | None:
    value = row.get("close")
    if value is None:
        value = row.get("close_price")
    if value is None:
        value = row.get("last_price")
    if value in (None, ""):
        return None
    return float(value)


def _backtest_one_code(
    *,
    code: str,
    rows: list[dict[str, Any]],
    threshold: float | None,
    quantity: int,
    max_order_notional: float,
) -> dict[str, Any]:
    sorted_rows = sorted(rows, key=_row_time)
    if threshold is None:
        return {
            "code": code,
            "bars_total": len(sorted_rows),
            "decision": {"status": "skipped", "reason": "missing_threshold"},
        }
    entry_row = None
    entry_price = None
    for row in sorted_rows:
        close = _row_close(row)
        if close is not None and close >= threshold:
            entry_row = row
            entry_price = close
            break
    if entry_row is None or entry_price is None:
        return {
            "code": code,
            "bars_total": len(sorted_rows),
            "decision": {"status": "skipped", "reason": "no_signal"},
        }
    notional = entry_price * quantity
    if notional > max_order_notional:
        return {
            "code": code,
            "bars_total": len(sorted_rows),
            "entry_time": _row_time(entry_row),
            "entry_price": entry_price,
            "decision": {"status": "rejected", "reason": "order_notional_exceeds_limit"},
        }
    exit_row = sorted_rows[-1]
    exit_price = _row_close(exit_row)
    return_ratio = None
    unrealized_pnl = None
    if exit_price is not None and entry_price:
        return_ratio = (exit_price - entry_price) / entry_price
        unrealized_pnl = (exit_price - entry_price) * quantity
    return {
        "code": code,
        "bars_total": len(sorted_rows),
        "entry_time": _row_time(entry_row),
        "entry_price": entry_price,
        "exit_time": _row_time(exit_row),
        "exit_price": exit_price,
        "quantity": quantity,
        "return_ratio": return_ratio,
        "unrealized_pnl": unrealized_pnl,
        "decision": {"status": "accepted", "reason": "accepted"},
    }


def _build_backtest(
    *,
    codes: list[str],
    rows: list[dict[str, Any]],
    buy_above: dict[str, float],
    quantity: int,
    max_order_notional: float,
) -> list[dict[str, Any]]:
    rows_by_code: dict[str, list[dict[str, Any]]] = {code: [] for code in codes}
    for row in rows:
        code = _row_code(row)
        if code in rows_by_code:
            rows_by_code[code].append(row)
    return [
        _backtest_one_code(
            code=code,
            rows=rows_by_code.get(code) or [],
            threshold=buy_above.get(code),
            quantity=quantity,
            max_order_notional=max_order_notional,
        )
        for code in codes
    ]


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [item for item in results if item.get("decision", {}).get("status") == "accepted"]
    rejected = [item for item in results if item.get("decision", {}).get("status") == "rejected"]
    returns = [item["return_ratio"] for item in accepted if item.get("return_ratio") is not None]
    pnl_values = [
        item["unrealized_pnl"] for item in accepted if item.get("unrealized_pnl") is not None
    ]
    return {
        "codes_total": len(results),
        "bars_total": sum(int(item.get("bars_total") or 0) for item in results),
        "orders_total": len(accepted),
        "accepted_orders": len(accepted),
        "rejected_orders": len(rejected),
        "average_return_ratio": sum(returns) / len(returns) if returns else None,
        "total_unrealized_pnl": sum(pnl_values) if pnl_values else 0.0,
    }


def main(argv: Optional[Sequence[str]] = None, *, writer: Optional[TextIO] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        codes = _parse_codes(args.codes)
        if not codes:
            raise ValueError("--codes must include at least one code")
        buy_above = _parse_buy_above(args.buy_above)
        rows = (
            _load_kline_json(args.kline_json)
            if args.kline_json
            else _fetch_futu_klines(args, codes)
        )
        results = _build_backtest(
            codes=codes,
            rows=rows,
            buy_above=buy_above,
            quantity=args.quantity,
            max_order_notional=args.max_order_notional,
        )
        payload = {
            "status": "ok",
            "source": "trading_strategy_backtest",
            "strategy_version": args.strategy_version,
            "request": {
                "codes": codes,
                "buy_above": buy_above,
                "quantity": args.quantity,
                "max_order_notional": args.max_order_notional,
                "source": "static_kline" if args.kline_json else "futu_opend",
                "start": args.start,
                "end": args.end,
                "ktype": args.ktype,
                "rehab": args.rehab,
            },
            "summary": _summary(results),
            "results": results,
        }
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit(
            {"status": "failed", "source": "trading_strategy_backtest", "error": str(exc)},
            False,
            writer,
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "trading_strategy_backtest",
                "error": f"策略回测失败: {exc}",
            },
            False,
            writer,
        )
        return 1
