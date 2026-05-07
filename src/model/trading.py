from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from typing import Any


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    return value


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalAction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class MarketSnapshot:
    code: str
    name: str = ""
    price: float | None = None
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: int | None = None
    turnover: float | None = None
    as_of: str | None = None
    source: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float = 0.0
    total_assets: float = 0.0
    currency: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class PositionSnapshot:
    code: str
    quantity: float = 0.0
    market_value: float = 0.0
    average_cost: float | None = None
    can_sell_quantity: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class StrategySignal:
    strategy_version_id: str
    code: str
    action: SignalAction
    quantity: int
    trigger_price: float | None
    rationale: str
    snapshot: MarketSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_version_id": self.strategy_version_id,
            "code": self.code,
            "action": self.action.value,
            "quantity": self.quantity,
            "trigger_price": self.trigger_price,
            "rationale": self.rationale,
            "snapshot": self.snapshot.to_dict(),
        }


@dataclass(frozen=True)
class OrderRequest:
    code: str
    side: OrderSide
    quantity: int
    price: float | None
    strategy_version_id: str
    idempotency_key: str
    reason: str
    order_type: str = "MARKET"
    trd_env: str = "SIMULATE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "strategy_version_id": self.strategy_version_id,
            "idempotency_key": self.idempotency_key,
            "reason": self.reason,
            "order_type": self.order_type,
            "trd_env": self.trd_env,
        }
