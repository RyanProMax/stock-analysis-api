from __future__ import annotations

import pytest

from src.data_provider.sources.futu import FutuMarketDataProvider, normalize_futu_code
from src.model.trading import AccountSnapshot, MarketSnapshot, OrderSide, PositionSnapshot
from src.repositories.trading_ledger_repository import SqliteTradingLedger
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


class FailingMarketDataProvider:
    source = "failing"

    def get_market_snapshots(self, codes: list[str]) -> list[MarketSnapshot]:
        del codes
        raise RuntimeError("market unavailable")


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
    assert first_result["strategy_version"] == "threshold-v1"
    assert first_result["started_at"]
    assert first_result["finished_at"]
    assert first_result["orders"][0]["request"]["side"] == OrderSide.BUY.value
    assert first_result["orders"][0]["request"]["trd_env"] == "SIMULATE"
    assert len(broker.submitted_orders) == 1

    assert second_result["status"] == "ok"
    assert second_result["risk_decisions"][0]["status"] == "rejected"
    assert second_result["risk_decisions"][0]["reason"] == "duplicate_idempotency_key"
    assert len(broker.submitted_orders) == 1


def test_sqlite_ledger_dedupes_order_across_service_instances(tmp_path):
    db_path = tmp_path / "trading_ledger.sqlite"
    first_broker = FakeBroker()
    first_service = TradingAutomationService(
        market_data=FakeMarketDataProvider(),
        broker=first_broker,
        strategy=FixedThresholdStrategy(
            strategy_version_id="threshold-v1",
            buy_above={"HK.00700": 100},
            quantity=10,
        ),
        risk_policy=MaxNotionalRiskPolicy(max_order_notional=2000),
        ledger=SqliteTradingLedger(db_path),
    )

    first_result = first_service.run_once(["HK.00700"])

    second_broker = FakeBroker()
    second_service = TradingAutomationService(
        market_data=FakeMarketDataProvider(),
        broker=second_broker,
        strategy=FixedThresholdStrategy(
            strategy_version_id="threshold-v1",
            buy_above={"HK.00700": 100},
            quantity=10,
        ),
        risk_policy=MaxNotionalRiskPolicy(max_order_notional=2000),
        ledger=SqliteTradingLedger(db_path),
    )

    second_result = second_service.run_once(["HK.00700"])

    assert first_result["run_id"]
    assert first_result["orders"][0]["request"]["side"] == OrderSide.BUY.value
    assert len(first_broker.submitted_orders) == 1
    assert second_result["orders"] == []
    assert second_result["risk_decisions"][0]["status"] == "rejected"
    assert second_result["risk_decisions"][0]["reason"] == "duplicate_idempotency_key"
    assert second_broker.submitted_orders == []


def test_sqlite_ledger_records_run_risk_and_order_audit(tmp_path):
    ledger = SqliteTradingLedger(tmp_path / "trading_ledger.sqlite")
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
        ledger=ledger,
    )

    result = service.run_once(["HK.00700"])
    run = ledger.get_run(result["run_id"])
    risk_decisions = ledger.list_risk_decisions(result["run_id"])
    orders = ledger.list_orders()

    assert run["status"] == "ok"
    assert run["request"]["codes"] == ["HK.00700"]
    assert run["result"]["orders"][0]["result"]["status"] == "submitted"
    assert risk_decisions[0]["status"] == "accepted"
    assert risk_decisions[0]["reason"] == "accepted"
    assert orders[0]["idempotency_key"] == result["orders"][0]["request"]["idempotency_key"]
    assert orders[0]["broker_result"]["order_id"] == "SIM-1"


def test_sqlite_ledger_marks_run_failed_when_run_once_raises(tmp_path):
    ledger = SqliteTradingLedger(tmp_path / "trading_ledger.sqlite")
    service = TradingAutomationService(
        market_data=FailingMarketDataProvider(),
        broker=FakeBroker(),
        strategy=FixedThresholdStrategy(
            strategy_version_id="threshold-v1",
            buy_above={"HK.00700": 100},
            quantity=10,
        ),
        risk_policy=MaxNotionalRiskPolicy(max_order_notional=2000),
        ledger=ledger,
    )

    with pytest.raises(RuntimeError, match="market unavailable"):
        service.run_once(["HK.00700"])

    runs = ledger.list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["result"]["error"] == "market unavailable"
    assert runs[0]["result"]["strategy_version"] == "threshold-v1"


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
