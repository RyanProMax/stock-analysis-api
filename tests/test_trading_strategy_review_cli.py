from __future__ import annotations

from io import StringIO
import json

from src.services.trading_run_once_cli import main as trading_run_once_main
from src.services.trading_strategy_review_cli import main as trading_strategy_review_main


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


def _run_review(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = trading_strategy_review_main(list(args), writer=writer)
    return exit_code, _strict_json_loads(writer.getvalue())


def test_trading_strategy_review_cli_generates_candidate_proposal_without_applying_changes(
    tmp_path,
):
    ledger_db = tmp_path / "trading_ledger.sqlite"
    _run_once(ledger_db, price=101)
    _run_once(ledger_db, price=105)

    exit_code, payload = _run_review(
        "--ledger-db",
        str(ledger_db),
        "--date",
        "2026-05-07",
        "--timezone",
        "Asia/Shanghai",
        "--min-runs",
        "2",
        "--max-rejection-rate",
        "0.75",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "trading_strategy_review"
    assert payload["review"]["gate_status"] == "passed"
    assert payload["review"]["ledger_backtest"]["method"] == "ledger_snapshot_replay"
    assert payload["review"]["ledger_backtest"]["runs_total"] == 2
    assert payload["review"]["ledger_backtest"]["order_mark_to_market"][0]["code"] == "HK.00700"
    assert payload["strategy_proposal"]["schema_version"] == "trading_strategy_proposal.v1"
    assert payload["strategy_proposal"]["status"] == "candidate"
    assert payload["strategy_proposal"]["strategy_version"] == "threshold-v1"
    assert payload["strategy_proposal"]["approval_required"] is True
    assert payload["strategy_proposal"]["effective_status"] == "candidate_only"
    assert (
        payload["strategy_proposal"]["proposed_changes"][0]["type"] == "keep_strategy_under_review"
    )


def test_trading_strategy_review_cli_blocks_proposal_when_sample_is_too_small(tmp_path):
    ledger_db = tmp_path / "trading_ledger.sqlite"
    _run_once(ledger_db, price=101)

    exit_code, payload = _run_review(
        "--ledger-db",
        str(ledger_db),
        "--date",
        "2026-05-07",
        "--timezone",
        "Asia/Shanghai",
        "--min-runs",
        "2",
    )

    assert exit_code == 0
    assert payload["status"] == "blocked"
    assert payload["review"]["gate_status"] == "blocked"
    assert payload["review"]["gate_reasons"] == ["insufficient_runs"]
    assert payload["strategy_proposal"]["status"] == "blocked"
    assert payload["strategy_proposal"]["approval_required"] is True
    assert payload["strategy_proposal"]["effective_status"] == "not_applied"
    assert payload["strategy_proposal"]["proposed_changes"] == []
