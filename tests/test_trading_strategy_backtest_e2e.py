from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


def test_trading_strategy_backtest_script_entrypoint_outputs_strict_json():
    repo_root = Path(__file__).resolve().parents[1]
    kline_json = json.dumps(
        [
            {"code": "HK.00700", "time_key": "2026-05-01", "close": 99},
            {"code": "HK.00700", "time_key": "2026-05-02", "close": 101},
            {"code": "HK.00700", "time_key": "2026-05-03", "close": 105},
        ],
        ensure_ascii=False,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/trading_strategy_backtest.py"),
            "--codes",
            "HK.00700",
            "--kline-json",
            kline_json,
            "--strategy-version",
            "threshold-v1",
            "--buy-above",
            "HK.00700=100",
            "--quantity",
            "10",
            "--max-order-notional",
            "2000",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = _strict_json_loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["source"] == "trading_strategy_backtest"
    assert payload["summary"]["orders_total"] == 1
