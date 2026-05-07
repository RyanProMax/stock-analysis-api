from __future__ import annotations

from io import StringIO
import json

import pytest

from src.services.trading_daily_summary_cli import main as trading_daily_summary_main
from src.services.trading_run_once_cli import main as trading_run_once_main


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


def _run_once(ledger_db, *, price: float) -> dict:
    writer = StringIO()
    snapshots_json = json.dumps(
        [
            {
                "code": "HK.00700",
                "name": "Tencent",
                "price": price,
                "as_of": "2026-05-07T15:59:00+08:00",
                "source": "fixture",
            }
        ],
        ensure_ascii=False,
    )
    exit_code = trading_run_once_main(
        [
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
            str(ledger_db),
        ],
        writer=writer,
    )
    assert exit_code == 0
    return _strict_json_loads(writer.getvalue())


def _run_summary(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = trading_daily_summary_main(list(args), writer=writer)
    return exit_code, _strict_json_loads(writer.getvalue())


def test_trading_daily_summary_cli_summarizes_real_ledger_runs_orders_and_market(tmp_path):
    ledger_db = tmp_path / "trading_ledger.sqlite"
    first_run = _run_once(ledger_db, price=101)
    second_run = _run_once(ledger_db, price=105)

    exit_code, payload = _run_summary(
        "--ledger-db",
        str(ledger_db),
        "--date",
        "2026-05-07",
        "--timezone",
        "Asia/Shanghai",
    )

    assert first_run["orders"][0]["result"]["status"] == "dry_run_submitted"
    assert second_run["orders"] == []
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "trading_daily_summary"
    assert payload["date"] == "2026-05-07"
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["summary"] == {
        "runs_total": 2,
        "orders_total": 1,
        "risk_decisions_total": 2,
        "accepted_risk_decisions": 1,
        "rejected_risk_decisions": 1,
        "codes": ["HK.00700"],
        "strategy_versions": ["threshold-v1"],
    }
    assert payload["risk_reason_counts"] == {
        "accepted": 1,
        "duplicate_idempotency_key": 1,
    }
    assert payload["market"][0]["code"] == "HK.00700"
    assert payload["market"][0]["first_price"] == 101
    assert payload["market"][0]["latest_price"] == 105
    assert payload["market"][0]["change_ratio"] == pytest.approx((105 - 101) / 101)
    assert payload["orders"][0]["code"] == "HK.00700"
    assert payload["orders"][0]["broker_result"]["status"] == "dry_run_submitted"
