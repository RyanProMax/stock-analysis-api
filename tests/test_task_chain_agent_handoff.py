from __future__ import annotations

from io import StringIO
import json
import sqlite3

from src.repositories.task_chain_repository import SqliteTaskChainRepository
from src.services.task_chain_cli import main as task_chain_main
from src.services.task_chain_service import TaskChainService


def _run_cli(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = task_chain_main(list(args), writer=writer)
    return exit_code, json.loads(writer.getvalue())


def test_kol_scan_assistant_prompt_creates_pending_handoff(tmp_path, monkeypatch):
    skill_root = tmp_path / "stock-kol-intel"
    command_dir = skill_root / "commands"
    command_dir.mkdir(parents=True)
    (command_dir / "kol.py").write_text("print('unused')", encoding="utf-8")
    monkeypatch.setenv("STOCK_KOL_INTEL_ROOT", str(skill_root))

    full_prompt = "build the complete KOL report\n" + ("detail " * 300)
    monkeypatch.setattr(
        TaskChainService,
        "_run_external_command",
        staticmethod(
            lambda *args, **kwargs: {
                "status": "ok",
                "stdout": json.dumps(
                    {
                        "reply": {
                            "type": "assistant_prompt",
                            "content": full_prompt,
                            "ack": "queued",
                        }
                    }
                ),
                "stderr": "",
                "returncode": 0,
            }
        ),
    )

    repository = SqliteTaskChainRepository(tmp_path / "task_chain.sqlite")
    service = TaskChainService(repository)
    result, next_specs = service._execute_task(
        {"id": "task-1", "task_type": "kol_scan", "payload": {"market": "hk_us"}},
        now="2026-05-15T10:00:00+00:00",
        current_run_id="run-1",
    )

    assert result["status"] == "agent_required"
    assert result["handoff_id"]
    assert result["prompt_chars"] == len(full_prompt.strip())
    assert result["prompt_preview"] == full_prompt.strip()[:1200]
    assert [spec.task_type for spec in next_specs] == ["kol_scan"]

    handoff = repository.get_agent_handoff(result["handoff_id"])
    assert handoff["source_task_id"] == "task-1"
    assert handoff["source_run_id"] == "run-1"
    assert handoff["task_type"] == "kol_scan"
    assert handoff["status"] == "pending"
    assert handoff["prompt_text"] == full_prompt.strip()
    assert handoff["prompt_json"]["reply"]["ack"] == "queued"


def test_agent_handoff_list_claim_complete_and_no_double_claim(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    handoff = repository.create_agent_handoff(
        source_task_id="task-1",
        source_run_id="run-1",
        task_type="kol_scan",
        prompt_text="run KOL report",
        prompt_json={"reply": {"type": "assistant_prompt"}},
        created_at="2026-05-15T10:00:00+00:00",
    )

    list_exit, list_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "list",
        "pending",
    )
    assert list_exit == 0
    assert [item["id"] for item in list_payload["handoffs"]] == [handoff["id"]]

    claim_exit, claim_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "claim",
        handoff["id"],
        "--claimed-by",
        "agent-a",
        "--lease-ttl-seconds",
        "120",
        "--now",
        "2026-05-15T10:01:00+00:00",
    )
    assert claim_exit == 0
    assert claim_payload["handoff"]["status"] == "claimed"
    assert claim_payload["handoff"]["claimed_by"] == "agent-a"

    second_claim_exit, second_claim_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "claim",
        handoff["id"],
        "--claimed-by",
        "agent-b",
        "--now",
        "2026-05-15T10:02:00+00:00",
    )
    assert second_claim_exit == 2
    assert second_claim_payload["status"] == "failed"

    result = {
        "handoff_id": handoff["id"],
        "agent_role": "kol_researcher",
        "agent_id": "kol-agent-v1",
        "model": "test-model",
        "input_hash": claim_payload["handoff"]["input_hash"],
        "status": "completed",
        "evidence_refs": [{"type": "task_chain_run", "id": "run-1"}],
        "summary": "done",
        "findings": [],
        "confidence": "medium",
        "limitations": [],
        "proposed_next_actions": [],
        "forbidden_actions_attempted": False,
    }
    complete_exit, complete_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        handoff["id"],
        "--owner-id",
        "agent-a",
        "--result-json",
        json.dumps(result),
        "--now",
        "2026-05-15T10:02:59+00:00",
    )
    assert complete_exit == 0
    assert complete_payload["handoff"]["status"] == "completed"
    assert complete_payload["handoff"]["result_json"]["summary"] == "done"

    completed_claim_exit, completed_claim_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "claim",
        handoff["id"],
        "--claimed-by",
        "agent-c",
    )
    assert completed_claim_exit == 2
    assert completed_claim_payload["status"] == "failed"

    assert repository.get_agent_handoff(handoff["id"])["claimed_by"] == "agent-a"


def test_agent_handoff_complete_and_fail_require_owner_for_p1b_handoffs(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    to_complete = repository.create_agent_handoff(
        source_task_id="task-1",
        source_run_id=None,
        task_type="kol_scan",
        prompt_text="run",
        prompt_json={"reply": {"type": "assistant_prompt"}},
    )
    result_file = tmp_path / "result.json"
    result_file.write_text('{"score":1}', encoding="utf-8")

    complete_exit, complete_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        to_complete["id"],
        "--result-file",
        str(result_file),
    )
    assert complete_exit == 2
    assert "owner_id" in complete_payload["error"]

    to_fail = repository.create_agent_handoff(
        source_task_id="task-2",
        source_run_id=None,
        task_type="kol_scan",
        prompt_text="run",
        prompt_json={"reply": {"type": "assistant_prompt"}},
    )
    fail_exit, fail_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "fail",
        to_fail["id"],
        "--error",
        "agent unavailable",
    )
    assert fail_exit == 2
    assert "owner_id" in fail_payload["error"]


def test_agent_handoff_enqueue_is_idempotent_and_records_events(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps(
            {
                "market": "hk_us",
                "symbols": ["HK.00700"],
                "prompt_text": "Build KOL evidence report",
            }
        ),
        encoding="utf-8",
    )

    first_exit, first_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "enqueue",
        "--source-task-id",
        "task-1",
        "--source-run-id",
        "run-1",
        "--source-task-type",
        "kol_scan",
        "--role",
        "kol_researcher",
        "--input-json",
        str(input_file),
        "--now",
        "2026-05-15T10:00:00+00:00",
    )
    assert first_exit == 0
    assert first_payload["status"] == "ok"
    assert first_payload["idempotent"] is False

    handoff = first_payload["handoff"]
    assert handoff["role"] == "kol_researcher"
    assert handoff["input_hash"].startswith("sha256:")
    assert handoff["idempotency_key"] == "task_run:run-1:kol_researcher"
    assert handoff["allowed_actions"] == ["semantic_review", "evidence_summary"]
    assert "activate_strategy" in handoff["forbidden_actions"]

    second_exit, second_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "enqueue",
        "--source-task-id",
        "task-1",
        "--source-run-id",
        "run-1",
        "--source-task-type",
        "kol_scan",
        "--role",
        "kol_researcher",
        "--input-json",
        str(input_file),
        "--now",
        "2026-05-15T10:01:00+00:00",
    )
    assert second_exit == 0
    assert second_payload["idempotent"] is True
    assert second_payload["handoff"]["id"] == handoff["id"]

    repository = SqliteTaskChainRepository(task_db)
    events = repository.list_agent_handoff_events(handoff["id"])
    assert [event["event_type"] for event in events] == ["enqueued"]
    assert events[0]["payload"]["idempotency_key"] == "task_run:run-1:kol_researcher"


def test_agent_handoff_claim_next_uses_role_lease_and_reclaims_expired(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    kol = repository.create_agent_handoff(
        source_task_id="task-1",
        source_run_id="run-1",
        task_type="kol_scan",
        role="kol_researcher",
        prompt_text="run KOL report",
        prompt_json={"reply": {"type": "assistant_prompt"}},
        created_at="2026-05-15T10:00:00+00:00",
    )
    repository.create_agent_handoff(
        source_task_id="task-2",
        source_run_id="run-2",
        task_type="news_scan",
        role="news_researcher",
        prompt_text="run news report",
        prompt_json={"reply": {"type": "assistant_prompt"}},
        created_at="2026-05-15T10:00:01+00:00",
    )

    claim_exit, claim_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "claim-next",
        "--role",
        "kol_researcher",
        "--owner-id",
        "agent-a",
        "--lease-ttl-seconds",
        "60",
        "--now",
        "2026-05-15T10:01:00+00:00",
    )
    assert claim_exit == 0
    assert claim_payload["handoff"]["id"] == kol["id"]
    assert claim_payload["handoff"]["status"] == "claimed"
    assert claim_payload["handoff"]["handoff_id"] == kol["id"]
    assert claim_payload["handoff"]["claimed_by"] == "agent-a"
    assert claim_payload["handoff"]["lease_expires_at"] == "2026-05-15T10:02:00+00:00"

    empty_exit, empty_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "claim-next",
        "--role",
        "kol_researcher",
        "--owner-id",
        "agent-b",
        "--lease-ttl-seconds",
        "60",
        "--now",
        "2026-05-15T10:01:30+00:00",
    )
    assert empty_exit == 0
    assert empty_payload == {"status": "skipped", "reason": "no_pending_handoff"}

    expired_output = {
        "handoff_id": kol["id"],
        "agent_role": "kol_researcher",
        "agent_id": "kol-agent-v1",
        "model": "test-model",
        "input_hash": claim_payload["handoff"]["input_hash"],
        "status": "completed",
        "evidence_refs": [{"type": "task_chain_run", "id": "run-1"}],
        "summary": "summary",
        "findings": [],
        "confidence": "medium",
        "limitations": [],
        "proposed_next_actions": [],
        "forbidden_actions_attempted": False,
    }
    expired_complete_exit, expired_complete_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        kol["id"],
        "--owner-id",
        "agent-a",
        "--result-json",
        json.dumps(expired_output),
        "--now",
        "2026-05-15T10:02:00+00:00",
    )
    assert expired_complete_exit == 2
    assert "lease expired" in expired_complete_payload["error"]

    reclaim_exit, reclaim_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "claim-next",
        "--role",
        "kol_researcher",
        "--owner-id",
        "agent-b",
        "--lease-ttl-seconds",
        "60",
        "--now",
        "2026-05-15T10:02:00+00:00",
    )
    assert reclaim_exit == 0
    assert reclaim_payload["handoff"]["claimed_by"] == "agent-b"

    events = repository.list_agent_handoff_events(kol["id"])
    assert [event["event_type"] for event in events] == [
        "enqueued",
        "claimed",
        "reclaimed",
    ]


def test_agent_handoff_complete_validates_owner_hash_role_and_output_schema(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    handoff = repository.create_agent_handoff(
        source_task_id="task-1",
        source_run_id="run-1",
        task_type="kol_scan",
        role="kol_researcher",
        prompt_text="run KOL report",
        prompt_json={"reply": {"type": "assistant_prompt"}},
        created_at="2026-05-15T10:00:00+00:00",
    )
    claimed = repository.claim_next_agent_handoff(
        role="kol_researcher",
        owner_id="agent-a",
        lease_ttl_seconds=60,
        now="2026-05-15T10:01:00+00:00",
    )
    assert claimed["id"] == handoff["id"]

    wrong_hash = {
        "handoff_id": handoff["id"],
        "agent_role": "kol_researcher",
        "agent_id": "kol-agent-v1",
        "model": "test-model",
        "input_hash": "sha256:wrong",
        "status": "completed",
        "evidence_refs": [{"type": "task_chain_run", "id": "run-1"}],
        "summary": "summary",
        "findings": [],
        "confidence": "medium",
        "limitations": [],
        "proposed_next_actions": [],
        "forbidden_actions_attempted": False,
    }
    wrong_exit, wrong_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        handoff["id"],
        "--owner-id",
        "agent-a",
        "--result-json",
        json.dumps(wrong_hash),
        "--now",
        "2026-05-15T10:01:30+00:00",
    )
    assert wrong_exit == 2
    assert wrong_payload["status"] == "failed"
    assert "input_hash" in wrong_payload["error"]
    assert repository.get_agent_handoff(handoff["id"])["status"] == "claimed"

    valid_output = {**wrong_hash, "input_hash": claimed["input_hash"]}
    complete_exit, complete_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        handoff["id"],
        "--owner-id",
        "agent-a",
        "--result-json",
        json.dumps(valid_output),
        "--now",
        "2026-05-15T10:01:45+00:00",
    )
    assert complete_exit == 0
    assert complete_payload["handoff"]["status"] == "completed"
    assert complete_payload["handoff"]["result_json"]["summary"] == "summary"

    outputs = repository.list_agent_handoff_outputs(handoff["id"])
    assert [output["agent_id"] for output in outputs] == ["kol-agent-v1"]
    events = repository.list_agent_handoff_events(handoff["id"])
    assert events[-1]["event_type"] == "completed"


def test_agent_handoff_complete_rejects_wrong_owner_and_forbidden_or_unknown_actions(
    tmp_path,
):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    handoff = repository.create_agent_handoff(
        source_task_id="task-1",
        source_run_id="run-1",
        task_type="kol_scan",
        role="kol_researcher",
        prompt_text="run KOL report",
        prompt_json={"reply": {"type": "assistant_prompt"}},
        created_at="2026-05-15T10:00:00+00:00",
    )
    claimed = repository.claim_next_agent_handoff(
        role="kol_researcher",
        owner_id="agent-a",
        lease_ttl_seconds=60,
        now="2026-05-15T10:01:00+00:00",
    )
    base_output = {
        "handoff_id": handoff["id"],
        "agent_role": "kol_researcher",
        "agent_id": "kol-agent-v1",
        "model": "test-model",
        "input_hash": claimed["input_hash"],
        "status": "completed",
        "evidence_refs": [{"type": "task_chain_run", "id": "run-1"}],
        "summary": "summary",
        "findings": [],
        "confidence": "medium",
        "limitations": [],
        "proposed_next_actions": [],
        "forbidden_actions_attempted": False,
    }

    wrong_owner_exit, wrong_owner_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        handoff["id"],
        "--owner-id",
        "agent-b",
        "--result-json",
        json.dumps(base_output),
        "--now",
        "2026-05-15T10:01:30+00:00",
    )
    assert wrong_owner_exit == 2
    assert "different owner" in wrong_owner_payload["error"]

    forbidden_output = {
        **base_output,
        "proposed_next_actions": [{"action": "approve_strategy"}],
    }
    forbidden_exit, forbidden_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        handoff["id"],
        "--owner-id",
        "agent-a",
        "--result-json",
        json.dumps(forbidden_output),
        "--now",
        "2026-05-15T10:01:31+00:00",
    )
    assert forbidden_exit == 2
    assert "forbidden proposed action" in forbidden_payload["error"]

    unknown_output = {
        **base_output,
        "proposed_next_actions": [{"action": "place_order"}],
    }
    unknown_exit, unknown_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        handoff["id"],
        "--owner-id",
        "agent-a",
        "--result-json",
        json.dumps(unknown_output),
        "--now",
        "2026-05-15T10:01:32+00:00",
    )
    assert unknown_exit == 2
    assert "not allowed" in unknown_payload["error"]


def test_agent_handoff_fail_and_replay_require_owner_and_preserve_input(tmp_path):
    task_db = str(tmp_path / "task_chain.sqlite")
    repository = SqliteTaskChainRepository(task_db)
    handoff = repository.create_agent_handoff(
        source_task_id="task-1",
        source_run_id="run-1",
        task_type="kol_scan",
        role="kol_researcher",
        prompt_text="run KOL report",
        prompt_json={"reply": {"type": "assistant_prompt"}},
        created_at="2026-05-15T10:00:00+00:00",
    )
    repository.claim_next_agent_handoff(
        role="kol_researcher",
        owner_id="agent-a",
        lease_ttl_seconds=60,
        now="2026-05-15T10:01:00+00:00",
    )

    fail_exit, fail_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "fail",
        handoff["id"],
        "--owner-id",
        "agent-a",
        "--error-type",
        "schema_validation_failed",
        "--error-message",
        "missing evidence_refs",
        "--retryable",
        "true",
        "--now",
        "2026-05-15T10:01:30+00:00",
    )
    assert fail_exit == 0
    assert fail_payload["handoff"]["status"] == "failed"
    assert fail_payload["handoff"]["error"] == "schema_validation_failed: missing evidence_refs"

    replay_exit, replay_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "replay",
        "--handoff-id",
        handoff["id"],
    )
    assert replay_exit == 0
    assert replay_payload["handoff"]["id"] == handoff["id"]
    assert replay_payload["handoff"]["prompt_text"] == "run KOL report"
    assert (
        replay_payload["handoff"]["input_payload"]["prompt_json"]["reply"]["type"]
        == "assistant_prompt"
    )
    assert [event["event_type"] for event in replay_payload["events"]] == [
        "enqueued",
        "claimed",
        "failed",
    ]


def test_agent_handoff_migrates_legacy_p1a_rows_for_claim_next(tmp_path):
    task_db = tmp_path / "task_chain.sqlite"
    conn = sqlite3.connect(str(task_db))
    conn.execute("""
        CREATE TABLE task_chain_agent_handoffs (
            id TEXT PRIMARY KEY,
            source_task_id TEXT,
            source_run_id TEXT,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            prompt_json TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            claimed_by TEXT,
            claimed_at TEXT
        )
        """)
    conn.execute(
        """
        INSERT INTO task_chain_agent_handoffs (
            id, source_task_id, source_run_id, task_type, status,
            prompt_json, prompt_text, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-1",
            "task-1",
            "run-1",
            "kol_scan",
            "pending",
            '{"reply":{"type":"assistant_prompt"}}',
            "legacy prompt",
            "2026-05-15T10:00:00+00:00",
            "2026-05-15T10:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()

    repository = SqliteTaskChainRepository(task_db)
    migrated = repository.get_agent_handoff("legacy-1")
    assert migrated["role"] == "kol_researcher"
    assert migrated["input_hash"].startswith("sha256:")
    assert migrated["idempotency_key"] == "legacy:legacy-1"
    assert "approve_strategy" in migrated["forbidden_actions"]

    claimed = repository.claim_next_agent_handoff(
        role="kol_researcher",
        owner_id="agent-a",
        lease_ttl_seconds=60,
        now="2026-05-15T10:01:00+00:00",
    )
    assert claimed["id"] == "legacy-1"
    assert claimed["claimed_by"] == "agent-a"
