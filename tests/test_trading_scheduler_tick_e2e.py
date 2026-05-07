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


def test_trading_scheduler_tick_script_entrypoint_outputs_strict_json(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/trading_scheduler_tick.py",
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
            "--state-key",
            "e2e-strategy",
            "--now",
            "2026-05-07T10:00:00+08:00",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = _strict_json_loads(proc.stdout)

    assert proc.stderr == ""
    assert payload["status"] == "ok"
    assert payload["source"] == "trading_scheduler_tick"
    assert payload["run_once"]["orders"][0]["result"]["status"] == "dry_run_submitted"
