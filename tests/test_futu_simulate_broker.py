from __future__ import annotations

import json
from io import StringIO

from src.model.trading import OrderRequest, OrderSide
from src.services.futu_simulate_broker import FutuSimulateBroker
from src.services.trading_run_once_cli import main as trading_run_once_main


class FakeFutuTradeGateway:
    def __init__(self) -> None:
        self.submitted_orders = []

    def get_account(self, *, currency: str):
        return {
            "cash": "50000",
            "total_assets": "51000",
            "currency": currency,
        }

    def get_positions(self):
        return [
            {
                "code": "HK.00700",
                "qty": "100",
                "market_val": "41000",
                "cost_price": "390",
                "can_sell_qty": "80",
            }
        ]

    def place_order(self, order: OrderRequest):
        self.submitted_orders.append(order)
        return {
            "order_id": "SIM-1",
            "order_status": "submitted",
            "trd_env": "SIMULATE",
            "code": order.code,
        }


def test_futu_simulate_broker_maps_account_positions_and_orders():
    gateway = FakeFutuTradeGateway()
    broker = FutuSimulateBroker(gateway=gateway, currency="HKD")
    order = OrderRequest(
        code="HK.00700",
        side=OrderSide.BUY,
        quantity=10,
        price=101,
        strategy_version_id="threshold-v1",
        idempotency_key="idem-1",
        reason="fixture",
        trd_env="SIMULATE",
    )

    account = broker.get_account()
    positions = broker.get_positions()
    result = broker.submit_order(order)

    assert account.cash == 50000
    assert account.total_assets == 51000
    assert account.currency == "HKD"
    assert positions[0].code == "HK.00700"
    assert positions[0].quantity == 100
    assert positions[0].market_value == 41000
    assert positions[0].average_cost == 390
    assert positions[0].can_sell_quantity == 80
    assert gateway.submitted_orders == [order]
    assert result["status"] == "submitted"
    assert result["broker_mode"] == "futu_simulate"
    assert result["trd_env"] == "SIMULATE"


def test_trading_run_once_cli_blocks_futu_simulate_with_injected_snapshots(tmp_path):
    writer = StringIO()
    snapshots_json = json.dumps(
        [
            {
                "code": "HK.00700",
                "name": "Tencent",
                "price": 101,
                "as_of": "2026-05-07T10:00:00+08:00",
                "source": "fixture",
            }
        ],
        ensure_ascii=False,
    )

    exit_code = trading_run_once_main(
        [
            "--broker",
            "futu-simulate",
            "--codes",
            "HK.00700",
            "--snapshots-json",
            snapshots_json,
            "--strategy-version",
            "threshold-v1",
            "--buy-above",
            "HK.00700=100",
            "--quantity",
            "10",
            "--max-order-notional",
            "2000",
            "--ledger-db",
            str(tmp_path / "trading_ledger.sqlite"),
        ],
        writer=writer,
    )
    payload = json.loads(writer.getvalue())

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "--broker futu-simulate cannot use --snapshots-json" in payload["error"]
