from __future__ import annotations

from io import StringIO
import json

from src.repositories.trading_ledger_repository import SqliteTradingLedger
from src.services.trading_scheduler_tick_cli import main as trading_scheduler_tick_main

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


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


def _run_scheduler(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = trading_scheduler_tick_main(list(args), writer=writer)
    return exit_code, _strict_json_loads(writer.getvalue())


def _base_args(ledger_db: str) -> list[str]:
    return [
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
        ledger_db,
        "--state-key",
        "test-strategy",
        "--interval-seconds",
        "300",
        "--active-window",
        "09:30-12:00,13:00-16:00",
    ]


def test_scheduler_tick_runs_once_then_skips_until_interval_elapsed(tmp_path):
    ledger_db = str(tmp_path / "trading_ledger.sqlite")

    first_exit_code, first_payload = _run_scheduler(
        *_base_args(ledger_db),
        "--now",
        "2026-05-07T10:00:00+08:00",
    )
    second_exit_code, second_payload = _run_scheduler(
        *_base_args(ledger_db),
        "--now",
        "2026-05-07T10:02:00+08:00",
    )

    ledger = SqliteTradingLedger(ledger_db)
    runs = ledger.list_runs()

    assert first_exit_code == 0
    assert first_payload["status"] == "ok"
    assert first_payload["run_once"]["orders"][0]["result"]["status"] == "dry_run_submitted"
    assert second_exit_code == 0
    assert second_payload["status"] == "skipped"
    assert second_payload["reason"] == "not_due"
    assert second_payload["schedule"]["next_run_at"] == "2026-05-07T10:05:00+08:00"
    assert len(runs) == 1


def test_scheduler_tick_skips_outside_active_window(tmp_path):
    exit_code, payload = _run_scheduler(
        *_base_args(str(tmp_path / "trading_ledger.sqlite")),
        "--now",
        "2026-05-07T08:00:00+08:00",
    )

    assert exit_code == 0
    assert payload["status"] == "skipped"
    assert payload["reason"] == "outside_active_window"
    assert payload["schedule"]["next_run_at"] == "2026-05-07T09:30:00+08:00"


def test_scheduler_tick_surfaces_run_once_lock_skip(tmp_path):
    ledger_db = tmp_path / "trading_ledger.sqlite"
    ledger = SqliteTradingLedger(ledger_db)
    lock = ledger.try_acquire_lock(
        "trading_run_once",
        ttl_seconds=60,
        owner_id="already-running",
    )

    exit_code, payload = _run_scheduler(
        *_base_args(str(ledger_db)),
        "--now",
        "2026-05-07T10:00:00+08:00",
    )

    assert lock is not None
    assert exit_code == 0
    assert payload["status"] == "skipped"
    assert payload["run_once"]["reason"] == "lock_unavailable"
    assert ledger.list_runs() == []
    assert ledger.get_scheduler_tick("test-strategy") is None
