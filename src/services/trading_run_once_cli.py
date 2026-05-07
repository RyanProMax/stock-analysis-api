from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, TextIO
import warnings

from ..data_provider.sources.futu import FutuMarketDataProvider
from ..model.trading import AccountSnapshot, MarketSnapshot, OrderRequest, PositionSnapshot
from ..repositories.trading_ledger_repository import SqliteTradingLedger
from .trading_automation_service import (
    FixedThresholdStrategy,
    MaxNotionalRiskPolicy,
    TradingAutomationService,
)


class StaticMarketDataProvider:
    source = "static_snapshot"

    def __init__(self, snapshots: list[MarketSnapshot]) -> None:
        self._snapshots = snapshots

    def get_market_snapshots(self, codes: Iterable[str]) -> list[MarketSnapshot]:
        requested = {str(code).strip().upper() for code in codes if str(code).strip()}
        return [snapshot for snapshot in self._snapshots if snapshot.code.upper() in requested]


class DryRunBroker:
    mode = "dry_run"

    def __init__(self, *, cash: float = 1_000_000, currency: str = "HKD") -> None:
        self.cash = float(cash)
        self.currency = currency

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(cash=self.cash, total_assets=self.cash, currency=self.currency)

    def get_positions(self) -> list[PositionSnapshot]:
        return []

    def submit_order(self, order: OrderRequest) -> dict[str, Any]:
        return {
            "status": "dry_run_submitted",
            "order_id": f"DRYRUN-{order.idempotency_key[:12]}",
            "broker_mode": self.mode,
            "trd_env": order.trd_env,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one simulated trading automation cycle")
    parser.add_argument("--codes", required=True, help="Comma-separated Futu codes, e.g. HK.00700")
    parser.add_argument(
        "--strategy-version",
        default="threshold-v1",
        help="Strategy version id written into signals and idempotency keys",
    )
    parser.add_argument(
        "--buy-above",
        required=True,
        help="Comma-separated thresholds in code=price form, e.g. HK.00700=100",
    )
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--max-order-notional", type=float, default=10_000)
    parser.add_argument("--ledger-db", help="SQLite trading ledger path")
    parser.add_argument(
        "--snapshots-json",
        help="Inline JSON array of market snapshots for dry-run replay and tests",
    )
    parser.add_argument("--account-cash", type=float, default=1_000_000)
    parser.add_argument("--currency", default="HKD")
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
        try:
            thresholds[code] = float(price)
        except ValueError as exc:
            raise ValueError(f"--buy-above invalid price for {code}") from exc
    if not thresholds:
        raise ValueError("--buy-above must include at least one code=price entry")
    return thresholds


def _load_snapshots_json(raw: str) -> list[MarketSnapshot]:
    content = raw
    if not raw.lstrip().startswith("["):
        try:
            raw_path = Path(raw).expanduser()
            if raw_path.is_file():
                content = raw_path.read_text(encoding="utf-8")
        except OSError:
            pass

    decoded = json.loads(content)
    if not isinstance(decoded, list):
        raise ValueError("--snapshots-json must decode to a JSON array")

    snapshots: list[MarketSnapshot] = []
    for item in decoded:
        if not isinstance(item, dict):
            raise ValueError("--snapshots-json items must be objects")
        snapshots.append(
            MarketSnapshot(
                code=str(item.get("code") or "").strip().upper(),
                name=str(item.get("name") or ""),
                price=float(item["price"]) if item.get("price") is not None else None,
                open_price=(
                    float(item["open_price"]) if item.get("open_price") is not None else None
                ),
                high=float(item["high"]) if item.get("high") is not None else None,
                low=float(item["low"]) if item.get("low") is not None else None,
                prev_close=(
                    float(item["prev_close"]) if item.get("prev_close") is not None else None
                ),
                volume=int(item["volume"]) if item.get("volume") is not None else None,
                turnover=float(item["turnover"]) if item.get("turnover") is not None else None,
                as_of=str(item.get("as_of")) if item.get("as_of") is not None else None,
                source=str(item.get("source") or "snapshot_json"),
                raw=dict(item),
            )
        )
    return snapshots


def main(argv: Optional[Sequence[str]] = None, *, writer: Optional[TextIO] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        codes = _parse_codes(args.codes)
        if not codes:
            raise ValueError("--codes must include at least one code")
        buy_above = _parse_buy_above(args.buy_above)
        market_data = (
            StaticMarketDataProvider(_load_snapshots_json(args.snapshots_json))
            if args.snapshots_json
            else FutuMarketDataProvider()
        )
        broker = DryRunBroker(cash=args.account_cash, currency=args.currency)
        service = TradingAutomationService(
            market_data=market_data,
            broker=broker,
            strategy=FixedThresholdStrategy(
                strategy_version_id=args.strategy_version,
                buy_above=buy_above,
                quantity=args.quantity,
            ),
            risk_policy=MaxNotionalRiskPolicy(max_order_notional=args.max_order_notional),
            ledger=SqliteTradingLedger(args.ledger_db),
        )
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            payload = service.run_once(codes)
        payload = {
            **payload,
            "broker_mode": broker.mode,
        }
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit({"status": "failed", "error": str(exc)}, args.pretty, writer)
        return 2
    except Exception as exc:
        _emit(
            {"status": "failed", "error": f"trading_run_once 执行失败: {exc}"}, args.pretty, writer
        )
        return 1
