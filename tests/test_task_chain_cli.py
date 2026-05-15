from __future__ import annotations

from io import StringIO
import json

from src.repositories.task_chain_repository import SqliteTaskChainRepository
from src.services.task_chain_cli import main as task_chain_main


def _run_cli(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = task_chain_main(list(args), writer=writer)
    payload = json.loads(writer.getvalue())
    return exit_code, payload


def test_bootstrap_and_tick_complete_due_task_and_schedule_next(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")

    bootstrap_exit, bootstrap_payload = _run_cli(
        "--task-db",
        task_db,
        "bootstrap",
        "--task-type",
        "market_observe",
        "--due-at",
        "2026-05-15T01:30:00+00:00",
        "--payload-json",
        '{"market":"cn","symbols":"300442,603228"}',
    )

    assert bootstrap_exit == 0
    assert bootstrap_payload["status"] == "ok"
    assert bootstrap_payload["task"]["task_type"] == "market_observe"

    tick_exit, tick_payload = _run_cli(
        "--task-db",
        task_db,
        "tick",
        "--now",
        "2026-05-15T01:31:00+00:00",
        "--owner-id",
        "worker-a",
    )

    assert tick_exit == 0
    assert tick_payload["status"] == "ok"
    assert tick_payload["task"]["task_type"] == "market_observe"
    assert tick_payload["run"]["status"] == "ok"
    assert tick_payload["result"]["objective"] == "observe_market_and_prepare_research"
    assert tick_payload["next_tasks"][0]["task_type"] == "alpha_mine"
    assert tick_payload["next_tasks"][0]["due_at"] == "2026-05-15T01:36:00+00:00"

    repository = SqliteTaskChainRepository(task_db)
    completed = repository.get_task(bootstrap_payload["task"]["id"])
    assert completed["status"] == "completed"
    pending = repository.list_tasks(status="pending")
    assert [task["task_type"] for task in pending] == ["alpha_mine"]


def test_tick_skips_when_next_task_is_not_due(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    _run_cli(
        "--task-db",
        task_db,
        "bootstrap",
        "--task-type",
        "market_observe",
        "--due-at",
        "2026-05-15T01:30:00+00:00",
    )
    _run_cli(
        "--task-db",
        task_db,
        "tick",
        "--now",
        "2026-05-15T01:31:00+00:00",
    )

    exit_code, payload = _run_cli(
        "--task-db",
        task_db,
        "tick",
        "--now",
        "2026-05-15T01:32:00+00:00",
    )

    assert exit_code == 0
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no_due_task"


def test_full_mvp_chain_reaches_clean_hourly_report(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    _run_cli(
        "--task-db",
        task_db,
        "bootstrap",
        "--task-type",
        "market_observe",
        "--due-at",
        "2026-05-15T01:30:00+00:00",
        "--payload-json",
        '{"market":"hk_us","mode":"paper_only"}',
    )

    ticks = [
        "2026-05-15T01:31:00+00:00",
        "2026-05-15T01:36:01+00:00",
        "2026-05-15T01:41:02+00:00",
        "2026-05-15T01:46:03+00:00",
        "2026-05-15T01:51:04+00:00",
    ]
    payload = {}
    for now in ticks:
        exit_code, payload = _run_cli(
            "--task-db",
            task_db,
            "tick",
            "--now",
            now,
            "--owner-id",
            "worker-a",
        )
        assert exit_code == 0
        assert payload["status"] == "ok"

    assert payload["task"]["task_type"] == "hourly_report"
    assert payload["result"]["summary"]["tasks_total"] == 4
    assert payload["result"]["summary"]["tasks_by_status"] == {"ok": 4}
    assert payload["next_tasks"][0]["task_type"] == "market_observe"
    assert payload["next_tasks"][0]["due_at"] == "2026-05-15T02:51:04+00:00"


def test_running_task_with_active_lease_is_not_reentered(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    task = repository.create_task(
        task_type="alpha_mine",
        due_at="2026-05-15T01:30:00+00:00",
        payload={"market": "cn"},
        created_at="2026-05-15T01:29:00+00:00",
    )
    acquired = repository.acquire_due_task(
        now="2026-05-15T01:31:00+00:00",
        owner_id="worker-a",
        lease_ttl_seconds=300,
    )

    assert acquired["id"] == task["id"]

    exit_code, payload = _run_cli(
        "--task-db",
        task_db,
        "tick",
        "--now",
        "2026-05-15T01:32:00+00:00",
        "--owner-id",
        "worker-b",
    )

    assert exit_code == 0
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no_due_task"


def test_expired_lease_can_be_recovered(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    task = repository.create_task(
        task_type="alpha_mine",
        due_at="2026-05-15T01:30:00+00:00",
        payload={"market": "cn"},
        created_at="2026-05-15T01:29:00+00:00",
    )
    repository.acquire_due_task(
        now="2026-05-15T01:31:00+00:00",
        owner_id="worker-a",
        lease_ttl_seconds=60,
    )

    recovered = repository.acquire_due_task(
        now="2026-05-15T01:33:00+00:00",
        owner_id="worker-b",
        lease_ttl_seconds=60,
    )

    assert recovered["id"] == task["id"]
    assert recovered["lease_owner"] == "worker-b"


def test_hourly_report_records_summary_and_schedules_next_observation(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    _run_cli(
        "--task-db",
        task_db,
        "bootstrap",
        "--task-type",
        "hourly_report",
        "--due-at",
        "2026-05-15T02:00:00+00:00",
    )

    exit_code, payload = _run_cli(
        "--task-db",
        task_db,
        "tick",
        "--now",
        "2026-05-15T02:00:00+00:00",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["result"]["report_type"] == "hourly"
    assert payload["result"]["summary"]["tasks_total"] == 0
    assert payload["next_tasks"][0]["task_type"] == "market_observe"
    assert payload["next_tasks"][0]["due_at"] == "2026-05-15T03:00:00+00:00"

    summaries = SqliteTaskChainRepository(task_db).list_summaries(summary_type="hourly")
    assert len(summaries) == 1
    assert summaries[0]["summary"]["report_type"] == "hourly"


def test_daily_report_contains_correction_reviews_and_next_day_plan(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    _run_cli(
        "--task-db",
        task_db,
        "bootstrap",
        "--task-type",
        "daily_report",
        "--due-at",
        "2026-05-15T07:30:00+00:00",
    )

    exit_code, payload = _run_cli(
        "--task-db",
        task_db,
        "tick",
        "--now",
        "2026-05-15T07:30:00+00:00",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    result = payload["result"]
    assert result["report_type"] == "daily"
    assert [review["role"] for review in result["correction_reviews"]] == [
        "trade_auditor",
        "strategy_reviewer",
        "risk_reviewer",
        "contrarian_reviewer",
    ]
    assert all(
        review["verdict"] in {"pass", "warn", "fail"}
        for review in result["correction_reviews"]
    )
    assert payload["next_tasks"][0]["task_type"] == "market_observe"

    summaries = SqliteTaskChainRepository(task_db).list_summaries(summary_type="daily")
    assert len(summaries) == 1
    assert summaries[0]["summary"]["correction_reviews"][0]["role"] == "trade_auditor"
