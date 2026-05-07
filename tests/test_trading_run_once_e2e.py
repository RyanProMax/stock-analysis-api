from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def _run_trading_script(ledger_db: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/trading_run_once.py",
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
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_trading_run_once_script_entrypoint_reuses_sqlite_ledger(tmp_path):
    ledger_db = tmp_path / "trading_ledger.sqlite"

    first = _run_trading_script(ledger_db)
    second = _run_trading_script(ledger_db)

    first_payload = _strict_json_loads(first.stdout)
    second_payload = _strict_json_loads(second.stdout)

    assert first.stderr == ""
    assert second.stderr == ""
    assert first_payload["status"] == "ok"
    assert first_payload["orders"][0]["result"]["status"] == "dry_run_submitted"
    assert second_payload["status"] == "ok"
    assert second_payload["orders"] == []
    assert second_payload["risk_decisions"][0]["reason"] == "duplicate_idempotency_key"
