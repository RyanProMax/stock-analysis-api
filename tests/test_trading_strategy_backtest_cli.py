from __future__ import annotations

from io import StringIO
import json

import pytest

from src.services.trading_strategy_backtest_cli import main as trading_strategy_backtest_main


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


def _run_backtest(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = trading_strategy_backtest_main(list(args), writer=writer)
    return exit_code, _strict_json_loads(writer.getvalue())


KLINE_JSON = json.dumps(
    [
        {"code": "HK.00700", "time_key": "2026-05-01", "close": 99},
        {"code": "HK.00700", "time_key": "2026-05-02", "close": 101},
        {"code": "HK.00700", "time_key": "2026-05-03", "close": 105},
    ],
    ensure_ascii=False,
)


def test_trading_strategy_backtest_cli_replays_threshold_strategy_from_kline_json():
    exit_code, payload = _run_backtest(
        "--codes",
        "HK.00700",
        "--kline-json",
        KLINE_JSON,
        "--strategy-version",
        "threshold-v1",
        "--buy-above",
        "HK.00700=100",
        "--quantity",
        "10",
        "--max-order-notional",
        "2000",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "trading_strategy_backtest"
    assert payload["summary"] == {
        "codes_total": 1,
        "bars_total": 3,
        "orders_total": 1,
        "accepted_orders": 1,
        "rejected_orders": 0,
        "average_return_ratio": pytest.approx((105 - 101) / 101),
        "total_unrealized_pnl": pytest.approx((105 - 101) * 10),
    }
    result = payload["results"][0]
    assert result["code"] == "HK.00700"
    assert result["entry_price"] == 101
    assert result["exit_price"] == 105
    assert result["return_ratio"] == pytest.approx((105 - 101) / 101)
    assert result["decision"]["status"] == "accepted"


def test_trading_strategy_backtest_cli_reports_risk_rejection():
    exit_code, payload = _run_backtest(
        "--codes",
        "HK.00700",
        "--kline-json",
        KLINE_JSON,
        "--strategy-version",
        "threshold-v1",
        "--buy-above",
        "HK.00700=100",
        "--quantity",
        "100",
        "--max-order-notional",
        "2000",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["summary"]["orders_total"] == 0
    assert payload["summary"]["rejected_orders"] == 1
    assert payload["results"][0]["decision"] == {
        "status": "rejected",
        "reason": "order_notional_exceeds_limit",
    }
