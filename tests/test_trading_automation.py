from __future__ import annotations

from src.data_provider.sources.futu import FutuMarketDataProvider, normalize_futu_code
from src.model.trading import AccountSnapshot, MarketSnapshot, OrderSide, PositionSnapshot
from src.services.trading_automation_service import (
    FixedThresholdStrategy,
    InMemoryTradingLedger,
    MaxNotionalRiskPolicy,
    TradingAutomationService,
)


class FakeFutuGateway:
    def get_market_snapshots(self, codes: list[str]) -> list[dict]:
        assert codes == ["HK.00700"]
        return [
            {
                "code": "HK.00700",
                "name": "Tencent",
                "last_price": 101,
                "open_price": 99,
                "high_price": 102,
                "low_price": 98,
                "prev_close_price": 100,
                "volume": 12345,
                "turnover": 67890.5,
                "update_time": "2026-05-05 15:59:59",
            }
        ]


class FakeMarketDataProvider:
    source = "fake"

    def get_market_snapshots(self, codes: list[str]) -> list[MarketSnapshot]:
        return [
            MarketSnapshot(
                code="HK.00700",
                name="Tencent",
                price=101,
                as_of="2026-05-05T15:59:59+08:00",
                source=self.source,
            )
        ]


class FakeBroker:
    def __init__(self, cash: float = 100000) -> None:
        self.cash = cash
        self.submitted_orders = []

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(cash=self.cash, total_assets=self.cash, currency="HKD")

    def get_positions(self) -> list[PositionSnapshot]:
        return []

    def submit_order(self, order):
        self.submitted_orders.append(order)
        return {"order_id": f"SIM-{len(self.submitted_orders)}", "status": "submitted"}


def test_normalize_futu_code_requires_market_prefix():
    assert normalize_futu_code("hk.00700") == "HK.00700"
    assert normalize_futu_code("US.aapl") == "US.AAPL"


def test_futu_provider_normalizes_market_snapshot_contract():
    provider = FutuMarketDataProvider(gateway=FakeFutuGateway())

    snapshots = provider.get_market_snapshots(["hk.00700"])

    assert snapshots == [
        MarketSnapshot(
            code="HK.00700",
            name="Tencent",
            price=101.0,
            open_price=99.0,
            high=102.0,
            low=98.0,
            prev_close=100.0,
            volume=12345,
            turnover=67890.5,
            as_of="2026-05-05 15:59:59",
            source="futu_opend",
            raw=FakeFutuGateway().get_market_snapshots(["HK.00700"])[0],
        )
    ]


def test_run_once_submits_simulate_order_and_dedupes_repeated_poll():
    broker = FakeBroker()
    service = TradingAutomationService(
        market_data=FakeMarketDataProvider(),
        broker=broker,
        strategy=FixedThresholdStrategy(
            strategy_version_id="threshold-v1",
            buy_above={"HK.00700": 100},
            quantity=10,
        ),
        risk_policy=MaxNotionalRiskPolicy(max_order_notional=2000),
        ledger=InMemoryTradingLedger(),
    )

    first_result = service.run_once(["HK.00700"])
    second_result = service.run_once(["HK.00700"])

    assert first_result["status"] == "ok"
    assert first_result["orders"][0]["request"]["side"] == OrderSide.BUY.value
    assert first_result["orders"][0]["request"]["trd_env"] == "SIMULATE"
    assert len(broker.submitted_orders) == 1

    assert second_result["status"] == "ok"
    assert second_result["risk_decisions"][0]["status"] == "rejected"
    assert second_result["risk_decisions"][0]["reason"] == "duplicate_idempotency_key"
    assert len(broker.submitted_orders) == 1


def test_risk_gate_rejects_order_above_max_notional():
    broker = FakeBroker()
    service = TradingAutomationService(
        market_data=FakeMarketDataProvider(),
        broker=broker,
        strategy=FixedThresholdStrategy(
            strategy_version_id="threshold-v1",
            buy_above={"HK.00700": 100},
            quantity=100,
        ),
        risk_policy=MaxNotionalRiskPolicy(max_order_notional=2000),
        ledger=InMemoryTradingLedger(),
    )

    result = service.run_once(["HK.00700"])

    assert result["risk_decisions"][0]["status"] == "rejected"
    assert result["risk_decisions"][0]["reason"] == "order_notional_exceeds_limit"
    assert broker.submitted_orders == []
