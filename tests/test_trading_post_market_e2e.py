from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_trading_post_market_scripts_read_real_ledger_chain(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    ledger_db = tmp_path / "trading_ledger.sqlite"
    snapshots_json = json.dumps(
        [
            {
                "code": "HK.00700",
                "name": "Tencent",
                "price": 101,
                "as_of": "2026-05-07T15:59:00+08:00",
                "source": "fixture",
            }
        ],
        ensure_ascii=False,
    )

    run_once = _run_script(
        str(repo_root / "scripts/trading_run_once.py"),
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
    )
    summary = _run_script(
        str(repo_root / "scripts/trading_daily_summary.py"),
        "--ledger-db",
        str(ledger_db),
        "--date",
        "2026-05-07",
    )
    review = _run_script(
        str(repo_root / "scripts/trading_strategy_review.py"),
        "--ledger-db",
        str(ledger_db),
        "--date",
        "2026-05-07",
        "--min-runs",
        "1",
    )

    assert run_once.returncode == 0
    assert summary.returncode == 0
    assert review.returncode == 0
    assert run_once.stderr == ""
    assert summary.stderr == ""
    assert review.stderr == ""
    assert _strict_json_loads(run_once.stdout)["status"] == "ok"
    summary_payload = _strict_json_loads(summary.stdout)
    review_payload = _strict_json_loads(review.stdout)
    assert summary_payload["summary"]["orders_total"] == 1
    assert review_payload["strategy_proposal"]["status"] == "candidate"
