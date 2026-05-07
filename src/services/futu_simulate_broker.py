from __future__ import annotations

from typing import Any, Protocol

from ..data_provider.sources.futu import FutuOpenDTradeGateway
from ..model.trading import AccountSnapshot, OrderRequest, PositionSnapshot


class FutuTradeGateway(Protocol):
    def get_account(self, *, currency: str) -> dict[str, Any]: ...

    def get_positions(self) -> list[dict[str, Any]]: ...

    def place_order(self, order: OrderRequest) -> dict[str, Any]: ...


def _as_float(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _as_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


class FutuSimulateBroker:
    mode = "futu_simulate"

    def __init__(
        self,
        *,
        gateway: FutuTradeGateway | None = None,
        currency: str = "HKD",
        market: str = "HK",
    ) -> None:
        self.currency = currency
        self._gateway = gateway or FutuOpenDTradeGateway(market=market)

    def get_account(self) -> AccountSnapshot:
        row = self._gateway.get_account(currency=self.currency)
        currency = _as_text(row, "currency", "cash_currency") or self.currency
        cash = _as_float(row, "cash", "available_funds", "avl_withdrawal_cash", "power")
        total_assets = _as_float(row, "total_assets", "net_assets", "total_asset", default=cash)
        return AccountSnapshot(
            cash=cash,
            total_assets=total_assets,
            currency=currency,
            raw=row,
        )

    def get_positions(self) -> list[PositionSnapshot]:
        positions: list[PositionSnapshot] = []
        for row in self._gateway.get_positions():
            code = _as_text(row, "code", "stock_code")
            if not code:
                continue
            positions.append(
                PositionSnapshot(
                    code=code,
                    quantity=_as_float(row, "qty", "quantity"),
                    market_value=_as_float(row, "market_val", "market_value"),
                    average_cost=_as_float(row, "cost_price", "average_cost", default=0.0),
                    can_sell_quantity=_as_float(row, "can_sell_qty", "can_sell_quantity"),
                    raw=row,
                )
            )
        return positions

    def submit_order(self, order: OrderRequest) -> dict[str, Any]:
        result = self._gateway.place_order(order)
        return {
            "status": str(result.get("order_status") or result.get("status") or "submitted"),
            "order_id": result.get("order_id"),
            "broker_mode": self.mode,
            "trd_env": "SIMULATE",
            "raw": result,
        }
