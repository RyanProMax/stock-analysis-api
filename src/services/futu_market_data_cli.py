from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
from typing import Any, Callable, Iterable, TextIO, TypeVar
import warnings

from ..data_provider.sources.futu import (
    FutuMarketDataProvider,
    FutuOpenDGateway,
    FutuOpenDTradeGateway,
    normalize_futu_code,
    to_jsonable,
)
from ..model.market import get_market_spec, normalize_market
from ..model.trading import MarketSnapshot

SOURCE = "futu_opend"
T = TypeVar("T")

HK_IPO_NAME_ALIASES: dict[str, dict[str, str]] = {
    "HK.02723": {
        "name_zh": "深演智能",
        "name_zh_hant": "深演智能",
    },
    "HK.06872": {
        "name_zh": "丹诺医药-B",
        "name_zh_hant": "丹諾醫藥-B",
    },
    "HK.00901": {
        "name_zh": "华曦达",
        "name_zh_hant": "華曦達",
    },
    "HK.03310": {
        "name_zh": "云英谷科技",
        "name_zh_hant": "雲英谷科技",
    },
    "HK.01511": {
        "name_zh": "驭势科技",
        "name_zh_hant": "馭勢科技",
    },
    "HK.07688": {
        "name_zh": "拓璞数控",
        "name_zh_hant": "拓璞數控",
    },
    "HK.01779": {
        "name_zh": "天辰生物-B",
        "name_zh_hant": "天辰生物-B",
    },
    "HK.02290": {
        "name_zh": "龙丰集团",
        "name_zh_hant": "龍豐集團",
    },
    "HK.01081": {
        "name_zh": "大金重工",
        "name_zh_hant": "大金重工",
    },
    "HK.02553": {
        "name_zh": "首钢朗泽",
        "name_zh_hant": "首鋼朗澤",
    },
}


def _write_payload(writer: TextIO, payload: dict[str, Any]) -> None:
    writer.write(json.dumps(to_jsonable(payload), ensure_ascii=False, allow_nan=False))
    writer.write("\n")


def _parse_codes(raw_codes: str | Iterable[str]) -> list[str]:
    if isinstance(raw_codes, str):
        candidates = raw_codes.split(",")
    else:
        candidates = list(raw_codes)
    return [str(code).strip() for code in candidates if str(code).strip()]


def _normalize_code_arg(raw_code: str) -> str:
    return str(raw_code or "").strip().upper()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _safe_int(value: Any) -> int | None:
    result = _safe_float(value)
    return int(result) if result is not None else None


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _enrich_hk_ipo_names(data: Any) -> Any:
    if not isinstance(data, list):
        return data
    enriched: list[Any] = []
    for item in data:
        if not isinstance(item, dict):
            enriched.append(item)
            continue
        row = dict(item)
        code = _normalize_code_arg(str(row.get("code") or ""))
        alias = HK_IPO_NAME_ALIASES.get(code)
        raw_name = _safe_str(row.get("name") or row.get("stock_name"))
        if raw_name:
            row.setdefault("name_en", raw_name)
            row.setdefault("english_name", raw_name)
        if alias:
            row.setdefault("name_zh", alias["name_zh"])
            row.setdefault("name_zh_hant", alias["name_zh_hant"])
            row.setdefault("display_name", alias["name_zh"])
            row.setdefault("name_source", "hkipo_alias_map")
        else:
            display_name = _safe_str(
                _first_present(
                    row, ("display_name", "name_zh", "cn_name", "stock_name", "name")
                )
            )
            if display_name:
                row.setdefault("display_name", display_name)
        enriched.append(row)
    return enriched


def _market_from_futu_code(code: str) -> str:
    prefix = normalize_futu_code(code).split(".", 1)[0]
    if prefix in {"SH", "SZ"}:
        return "cn"
    return normalize_market(prefix.lower())


def _symbol_rule_from_snapshot(snapshot: MarketSnapshot) -> dict[str, Any]:
    market = _market_from_futu_code(snapshot.code)
    spec = get_market_spec(market)
    raw = snapshot.raw or {}

    raw_lot_size = _safe_int(_first_present(raw, ("lot_size", "lot", "round_lot")))
    raw_price_tick = _safe_float(
        _first_present(raw, ("price_spread", "price_tick", "tick_size", "spread"))
    )
    lot_size = raw_lot_size if raw_lot_size is not None else spec.lot_size
    price_tick = raw_price_tick if raw_price_tick is not None else spec.price_tick

    return {
        "code": snapshot.code,
        "name": snapshot.name,
        "market": market,
        "source": snapshot.source,
        "as_of": snapshot.as_of,
        "lot_size": lot_size,
        "lot_size_source": (
            "futu_snapshot" if raw_lot_size is not None else "market_spec_default"
        ),
        "price_tick": price_tick,
        "price_tick_source": (
            "futu_snapshot" if raw_price_tick is not None else "market_spec_default"
        ),
        "market_spec": {
            "currency": spec.currency,
            "timezone": spec.timezone,
            "exchange": spec.exchange,
            "regular_sessions": spec.regular_sessions,
            "default_lot_size": spec.lot_size,
            "default_price_tick": spec.price_tick,
            "round_trip_cost_bps": spec.round_trip_cost_bps,
            "constraints": spec.constraints,
        },
        "raw_fields": to_jsonable(
            {
                "lot_size": raw.get("lot_size"),
                "price_spread": raw.get("price_spread"),
                "stock_type": raw.get("stock_type"),
                "stock_child_type": raw.get("stock_child_type"),
                "listing_date": raw.get("listing_date"),
            }
        ),
    }


def _call_suppressing_stdout(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return func(*args, **kwargs)


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
    kline.add_argument(
        "--rehab", choices=["none", "forward", "backward"], default="forward"
    )
    kline.add_argument(
        "--session", choices=["NONE", "RTH", "ETH", "ALL"], default="NONE"
    )
    kline.add_argument("--json", action="store_true", dest="output_json")

    snapshot = subparsers.add_parser("snapshot", help="Get market snapshots")
    snapshot.add_argument("--codes", required=True)
    snapshot.add_argument("--json", action="store_true", dest="output_json")

    symbol_rules = subparsers.add_parser(
        "symbol-rules",
        help="Get readonly symbol lot size and tick rules from Futu snapshot",
    )
    symbol_rules.add_argument("--codes", required=True)
    symbol_rules.add_argument("--json", action="store_true", dest="output_json")

    order_book = subparsers.add_parser("order-book", help="Get readonly order book")
    order_book.add_argument("--code", required=True)
    order_book.add_argument("--num", type=int, default=10)
    order_book.add_argument("--json", action="store_true", dest="output_json")

    ticker = subparsers.add_parser("ticker", help="Get readonly realtime ticker")
    ticker.add_argument("--code", required=True)
    ticker.add_argument("--num", type=int, default=500)
    ticker.add_argument("--json", action="store_true", dest="output_json")

    rt_data = subparsers.add_parser("rt-data", help="Get readonly intraday data")
    rt_data.add_argument("--code", required=True)
    rt_data.add_argument("--json", action="store_true", dest="output_json")

    option_expirations = subparsers.add_parser(
        "option-expirations",
        help="Get readonly option expiration dates",
    )
    option_expirations.add_argument("--code", required=True)
    option_expirations.add_argument(
        "--index-option-type",
        choices=["NORMAL", "SMALL", "NONE"],
        default="NORMAL",
    )
    option_expirations.add_argument("--json", action="store_true", dest="output_json")

    option_chain = subparsers.add_parser(
        "option-chain", help="Get readonly option chain"
    )
    option_chain.add_argument("--code", required=True)
    option_chain.add_argument("--start")
    option_chain.add_argument("--end")
    option_chain.add_argument(
        "--index-option-type",
        choices=["NORMAL", "SMALL", "NONE"],
        default="NORMAL",
    )
    option_chain.add_argument(
        "--option-type", choices=["ALL", "CALL", "PUT"], default="ALL"
    )
    option_chain.add_argument(
        "--option-cond-type",
        choices=["ALL", "WITHIN", "OUTSIDE"],
        default="ALL",
    )
    option_chain.add_argument("--json", action="store_true", dest="output_json")

    account = subparsers.add_parser(
        "account", help="Get readonly simulated account summary"
    )
    _add_trade_args(account)
    account.add_argument("--currency", default="HKD")
    account.add_argument("--json", action="store_true", dest="output_json")

    positions = subparsers.add_parser(
        "positions", help="Get readonly simulated positions"
    )
    _add_trade_args(positions)
    positions.add_argument("--code", default="")
    positions.add_argument("--json", action="store_true", dest="output_json")

    orders = subparsers.add_parser("orders", help="Get readonly simulated orders")
    _add_trade_args(orders)
    _add_trade_query_args(orders)

    deals = subparsers.add_parser("deals", help="Get readonly simulated deals")
    _add_trade_args(deals)
    _add_trade_query_args(deals)

    cash_flow = subparsers.add_parser(
        "cash-flow", help="Get readonly simulated cash flow"
    )
    _add_trade_args(cash_flow)
    cash_flow.add_argument("--clearing-date", default="")
    cash_flow.add_argument("--direction", default="N/A")
    cash_flow.add_argument("--json", action="store_true", dest="output_json")
    return parser


def _add_trade_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--market", choices=["HK", "US", "CN", "SG", "AU", "JP"], default="HK"
    )
    parser.add_argument("--acc-id", type=int, default=0)
    parser.add_argument("--acc-index", type=int, default=0)


def _add_trade_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--code", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--json", action="store_true", dest="output_json")


def _build_trade_gateway(args: argparse.Namespace) -> FutuOpenDTradeGateway:
    return FutuOpenDTradeGateway(
        market=args.market,
        acc_id=args.acc_id,
        acc_index=args.acc_index,
    )


def main(
    argv: list[str] | None = None,
    *,
    writer: TextIO | None = None,
    gateway: Any | None = None,
    trade_gateway: Any | None = None,
) -> int:
    writer = writer or sys.stdout
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        gateway = gateway or FutuOpenDGateway()
        if args.command == "global-state":
            data = _call_suppressing_stdout(gateway.get_global_state)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "data": data,
                },
            )
            return 0

        if args.command == "ipo-list":
            market = str(args.market).strip().upper()
            data = _call_suppressing_stdout(gateway.get_ipo_list, market)
            if market == "HK":
                data = _enrich_hk_ipo_names(data)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "market": market,
                    "data": data,
                },
            )
            return 0

        if args.command == "kline":
            code = str(args.code).strip().upper()
            data = _call_suppressing_stdout(
                gateway.request_history_kline,
                code,
                ktype=args.ktype,
                start=args.start,
                end=args.end,
                max_count=args.num,
                rehab=args.rehab,
                session=args.session,
                max_page=args.max_page,
            )
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "code": code,
                    "ktype": args.ktype,
                    "data": data,
                },
            )
            return 0

        if args.command == "snapshot":
            codes = _parse_codes(args.codes)
            provider = FutuMarketDataProvider(gateway=gateway)
            snapshots = _call_suppressing_stdout(provider.get_market_snapshots, codes)
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

        if args.command == "symbol-rules":
            codes = [normalize_futu_code(code) for code in _parse_codes(args.codes)]
            provider = FutuMarketDataProvider(gateway=gateway)
            snapshots = _call_suppressing_stdout(provider.get_market_snapshots, codes)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "request": {"codes": codes, "count": len(codes)},
                    "data": [
                        _symbol_rule_from_snapshot(snapshot) for snapshot in snapshots
                    ],
                },
            )
            return 0

        if args.command == "order-book":
            code = _normalize_code_arg(args.code)
            data = _call_suppressing_stdout(gateway.get_order_book, code, num=args.num)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "request": {"code": code, "num": args.num},
                    "data": data,
                },
            )
            return 0

        if args.command == "ticker":
            code = _normalize_code_arg(args.code)
            data = _call_suppressing_stdout(gateway.get_rt_ticker, code, num=args.num)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "request": {"code": code, "num": args.num},
                    "data": data,
                },
            )
            return 0

        if args.command == "rt-data":
            code = _normalize_code_arg(args.code)
            data = _call_suppressing_stdout(gateway.get_rt_data, code)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "request": {"code": code},
                    "data": data,
                },
            )
            return 0

        if args.command == "option-expirations":
            code = _normalize_code_arg(args.code)
            data = _call_suppressing_stdout(
                gateway.get_option_expiration_date,
                code,
                index_option_type=args.index_option_type,
            )
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "request": {
                        "code": code,
                        "index_option_type": args.index_option_type,
                    },
                    "data": data,
                },
            )
            return 0

        if args.command == "option-chain":
            code = _normalize_code_arg(args.code)
            data = _call_suppressing_stdout(
                gateway.get_option_chain,
                code,
                index_option_type=args.index_option_type,
                start=args.start,
                end=args.end,
                option_type=args.option_type,
                option_cond_type=args.option_cond_type,
            )
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "request": {
                        "code": code,
                        "index_option_type": args.index_option_type,
                        "start": args.start,
                        "end": args.end,
                        "option_type": args.option_type,
                        "option_cond_type": args.option_cond_type,
                    },
                    "data": data,
                },
            )
            return 0

        if args.command == "account":
            trade_gateway = trade_gateway or _build_trade_gateway(args)
            data = _call_suppressing_stdout(
                trade_gateway.get_account, currency=args.currency
            )
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "environment": "SIMULATE",
                    "market": args.market,
                    "request": {"currency": args.currency},
                    "data": data,
                },
            )
            return 0

        if args.command == "positions":
            trade_gateway = trade_gateway or _build_trade_gateway(args)
            code = _normalize_code_arg(args.code) if args.code else ""
            data = _call_suppressing_stdout(trade_gateway.get_positions, code=code)
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "environment": "SIMULATE",
                    "market": args.market,
                    "request": {"code": code},
                    "data": data,
                },
            )
            return 0

        if args.command == "orders":
            trade_gateway = trade_gateway or _build_trade_gateway(args)
            code = _normalize_code_arg(args.code) if args.code else ""
            data = _call_suppressing_stdout(
                trade_gateway.get_orders,
                code=code,
                start=args.start,
                end=args.end,
                history=args.history,
            )
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "environment": "SIMULATE",
                    "market": args.market,
                    "request": {
                        "code": code,
                        "start": args.start,
                        "end": args.end,
                        "history": args.history,
                    },
                    "data": data,
                },
            )
            return 0

        if args.command == "deals":
            trade_gateway = trade_gateway or _build_trade_gateway(args)
            code = _normalize_code_arg(args.code) if args.code else ""
            data = _call_suppressing_stdout(
                trade_gateway.get_deals,
                code=code,
                start=args.start,
                end=args.end,
                history=args.history,
            )
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "environment": "SIMULATE",
                    "market": args.market,
                    "request": {
                        "code": code,
                        "start": args.start,
                        "end": args.end,
                        "history": args.history,
                    },
                    "data": data,
                },
            )
            return 0

        if args.command == "cash-flow":
            trade_gateway = trade_gateway or _build_trade_gateway(args)
            data = _call_suppressing_stdout(
                trade_gateway.get_cash_flow,
                clearing_date=args.clearing_date,
                direction=args.direction,
            )
            _write_payload(
                writer,
                {
                    "status": "ok",
                    "source": SOURCE,
                    "environment": "SIMULATE",
                    "market": args.market,
                    "request": {
                        "clearing_date": args.clearing_date,
                        "direction": args.direction,
                    },
                    "data": data,
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
