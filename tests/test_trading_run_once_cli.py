from __future__ import annotations

from io import StringIO
import json

from src.services.trading_run_once_cli import main as trading_run_once_cli_main


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


SNAPSHOTS_JSON = json.dumps(
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
SNAPSHOTS_JSON_WITH_NAN = """
[
  {
    "code": "HK.00700",
    "name": "Tencent",
    "price": 101,
    "stock_owner": NaN,
    "as_of": "2026-05-07T10:00:00+08:00",
    "source": "fixture"
  }
]
"""


def _run_cli(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = trading_run_once_cli_main(list(args), writer=writer)
    return exit_code, _strict_json_loads(writer.getvalue())


def test_trading_run_once_cli_outputs_pure_json_and_records_dry_run_order(tmp_path):
    exit_code, payload = _run_cli(
        "--codes",
        "HK.00700",
        "--snapshots-json",
        SNAPSHOTS_JSON,
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
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["strategy_version"] == "threshold-v1"
    assert payload["started_at"]
    assert payload["finished_at"]
    assert payload["broker_mode"] == "dry_run"
    assert payload["orders"][0]["result"]["status"] == "dry_run_submitted"
    assert payload["orders"][0]["request"]["trd_env"] == "SIMULATE"


def test_trading_run_once_cli_reuses_ledger_for_cross_process_dedupe(tmp_path):
    ledger_db = tmp_path / "trading_ledger.sqlite"
    first_exit_code, first_payload = _run_cli(
        "--codes",
        "HK.00700",
        "--snapshots-json",
        SNAPSHOTS_JSON,
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
    )
    second_exit_code, second_payload = _run_cli(
        "--codes",
        "HK.00700",
        "--snapshots-json",
        SNAPSHOTS_JSON,
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
    )

    assert first_exit_code == 0
    assert first_payload["orders"][0]["result"]["status"] == "dry_run_submitted"
    assert second_exit_code == 0
    assert second_payload["orders"] == []
    assert second_payload["risk_decisions"][0]["reason"] == "duplicate_idempotency_key"


def test_trading_run_once_cli_accepts_long_inline_snapshots_json(tmp_path):
    snapshots_json = json.dumps(
        [
            {
                "code": "HK.00700",
                "name": "Tencent" * 1000,
                "price": 101,
                "as_of": "2026-05-07T10:00:00+08:00",
                "source": "fixture",
            }
        ],
        ensure_ascii=False,
    )

    exit_code, payload = _run_cli(
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
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["orders"][0]["result"]["status"] == "dry_run_submitted"


def test_trading_run_once_cli_outputs_standard_json_when_raw_contains_nan(tmp_path):
    exit_code, payload = _run_cli(
        "--codes",
        "HK.00700",
        "--snapshots-json",
        SNAPSHOTS_JSON_WITH_NAN,
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
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["snapshots"][0]["raw"]["stock_owner"] is None


def test_trading_run_once_cli_rejects_invalid_buy_above(tmp_path):
    exit_code, payload = _run_cli(
        "--codes",
        "HK.00700",
        "--snapshots-json",
        SNAPSHOTS_JSON,
        "--buy-above",
        "HK.00700",
        "--ledger-db",
        str(tmp_path / "trading_ledger.sqlite"),
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "code=price" in payload["error"]
