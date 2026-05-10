from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .serialization import json_safe


@dataclass(frozen=True)
class MarketSpec:
    market: str
    exchange: str
    currency: str
    timezone: str
    regular_sessions: list[str]
    lot_size: int
    price_tick: float
    entry_fee_bps: float
    exit_fee_bps: float
    entry_slippage_bps: float
    exit_slippage_bps: float
    constraints: list[str] = field(default_factory=list)

    @property
    def round_trip_cost_bps(self) -> float:
        return round(
            self.entry_fee_bps
            + self.exit_fee_bps
            + self.entry_slippage_bps
            + self.exit_slippage_bps,
            8,
        )

    def to_cost_model(self) -> dict[str, Any]:
        return json_safe(
            {
                "type": "market_spec_bps",
                "market": self.market,
                "currency": self.currency,
                "round_trip_bps": self.round_trip_cost_bps,
                "components": {
                    "entry_fee_bps": self.entry_fee_bps,
                    "exit_fee_bps": self.exit_fee_bps,
                    "entry_slippage_bps": self.entry_slippage_bps,
                    "exit_slippage_bps": self.exit_slippage_bps,
                },
                "assumptions": {
                    "exchange": self.exchange,
                    "timezone": self.timezone,
                    "regular_sessions": self.regular_sessions,
                    "lot_size": self.lot_size,
                    "price_tick": self.price_tick,
                    "constraints": self.constraints,
                },
            }
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["round_trip_cost_bps"] = self.round_trip_cost_bps
        return json_safe(payload)


MARKET_SPECS: dict[str, MarketSpec] = {
    "cn": MarketSpec(
        market="cn",
        exchange="SSE/SZSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        regular_sessions=["09:30-11:30", "13:00-15:00"],
        lot_size=100,
        price_tick=0.01,
        entry_fee_bps=3.0,
        exit_fee_bps=8.0,
        entry_slippage_bps=5.0,
        exit_slippage_bps=5.0,
        constraints=["estimated_default_costs", "lot_size_applies_to_stock_orders"],
    ),
    "hk": MarketSpec(
        market="hk",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        regular_sessions=["09:30-12:00", "13:00-16:00"],
        lot_size=100,
        price_tick=0.01,
        entry_fee_bps=5.0,
        exit_fee_bps=15.0,
        entry_slippage_bps=5.0,
        exit_slippage_bps=5.0,
        constraints=["estimated_default_costs", "symbol_lot_size_can_vary"],
    ),
    "us": MarketSpec(
        market="us",
        exchange="NYSE/NASDAQ",
        currency="USD",
        timezone="America/New_York",
        regular_sessions=["09:30-16:00"],
        lot_size=1,
        price_tick=0.01,
        entry_fee_bps=0.5,
        exit_fee_bps=0.5,
        entry_slippage_bps=5.0,
        exit_slippage_bps=5.0,
        constraints=["estimated_default_costs", "regular_session_only"],
    ),
}


def normalize_market(value: str) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    if lowered.startswith("hk.") or lowered in {"hk", "hkg", "hkex", "港股"}:
        return "hk"
    if lowered.startswith("us.") or lowered in {"us", "usa", "nyse", "nasdaq", "美股"}:
        return "us"
    if lowered in {"cn", "a", "ashare", "a股", "沪深", "sse", "szse"}:
        return "cn"
    return lowered


def get_market_spec(value: str) -> MarketSpec:
    market = normalize_market(value)
    spec = MARKET_SPECS.get(market)
    if spec is None:
        raise ValueError(f"unsupported market: {value}")
    return spec
