from __future__ import annotations

from io import StringIO
import json

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

    complete_exit, complete_payload = _run_cli(
        "--task-db",
        task_db,
        "handoff",
        "complete",
        handoff["id"],
        "--result-json",
        '{"final_markdown":"done"}',
        "--now",
        "2026-05-15T10:03:00+00:00",
    )
    assert complete_exit == 0
    assert complete_payload["handoff"]["status"] == "completed"
    assert complete_payload["handoff"]["result_json"] == {"final_markdown": "done"}

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


def test_agent_handoff_complete_supports_result_file_and_fail_outputs_json(tmp_path):
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
    assert complete_exit == 0
    assert complete_payload["handoff"]["result_json"] == {"score": 1}

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
    assert fail_exit == 0
    assert fail_payload["handoff"]["status"] == "failed"
    assert fail_payload["handoff"]["error"] == "agent unavailable"
