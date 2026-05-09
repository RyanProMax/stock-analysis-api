from __future__ import annotations

from io import StringIO
import json

from src.repositories.strategy_registry_repository import SqliteStrategyRegistry
from src.services.strategy_registry_cli import main as strategy_registry_cli_main
from src.services.strategy_registry_service import StrategyRegistryService


def _proposal(strategy_version: str, proposal_id: str | None = None) -> dict:
    return {
        "proposal_id": proposal_id or f"proposal-{strategy_version}",
        "strategy_version": strategy_version,
        "generated_at": "2026-05-09T13:00:00+00:00",
        "source": "alpha_daily_report",
        "proposed_changes": [
            {
                "type": "set_parameters",
                "parameters": {"top_n": 10, "rebalance": "1d"},
                "risk_limits": {"max_weight": 0.1},
            }
        ],
        "evidence": {
            "alpha_evaluation_id": "eval-20260509-momentum",
            "rank_ic_mean": 0.08,
        },
        "approval_required": True,
        "effective_status": "candidate_only",
    }


def _service(tmp_path) -> StrategyRegistryService:
    registry = SqliteStrategyRegistry(tmp_path / "strategy_registry.sqlite")
    return StrategyRegistryService(registry=registry)


def _write_json(tmp_path, name: str, payload: dict):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _run_cli(service: StrategyRegistryService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = strategy_registry_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_strategy_registry_propose_persists_candidate_without_applying(tmp_path):
    service = _service(tmp_path)
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal("alpha_topn_v1.20260509"))

    exit_code, payload = _run_cli(service, "propose", "--proposal-json", str(proposal_path))

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "strategy_registry"
    assert payload["action"] == "propose"
    assert payload["proposal"]["approval_required"] is True
    assert payload["proposal"]["effective_status"] == "candidate_only"
    assert payload["strategy_version"]["strategy_version"] == "alpha_topn_v1.20260509"
    assert payload["strategy_version"]["status"] == "candidate"
    assert payload["strategy_version"]["approved_by"] is None
    assert payload["current_strategy"] is None
    assert payload["events"][0]["to_status"] == "candidate"
    json.dumps(payload, allow_nan=False)


def test_strategy_registry_activate_requires_approval_record(tmp_path):
    service = _service(tmp_path)
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal("alpha_topn_v1.20260509"))
    assert _run_cli(service, "propose", "--proposal-json", str(proposal_path))[0] == 0

    exit_code, payload = _run_cli(
        service,
        "activate",
        "--strategy-version",
        "alpha_topn_v1.20260509",
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "approval record required" in payload["error"]
    assert service.current()["current_strategy"] is None


def test_strategy_registry_approve_then_activate_allows_single_active_strategy(tmp_path):
    service = _service(tmp_path)
    first = _write_json(tmp_path, "proposal-1.json", _proposal("alpha_topn_v1.20260509"))
    second = _write_json(tmp_path, "proposal-2.json", _proposal("alpha_topn_v2.20260510"))
    assert _run_cli(service, "propose", "--proposal-json", str(first))[0] == 0
    assert (
        _run_cli(
            service,
            "approve",
            "--strategy-version",
            "alpha_topn_v1.20260509",
            "--approved-by",
            "ryan",
        )[0]
        == 0
    )

    exit_code, activated = _run_cli(
        service,
        "activate",
        "--strategy-version",
        "alpha_topn_v1.20260509",
    )

    assert exit_code == 0
    assert activated["status"] == "ok"
    assert activated["current_strategy"]["strategy_version"] == "alpha_topn_v1.20260509"
    assert activated["current_strategy"]["status"] == "active"

    assert _run_cli(service, "propose", "--proposal-json", str(second))[0] == 0
    assert (
        _run_cli(
            service,
            "approve",
            "--strategy-version",
            "alpha_topn_v2.20260510",
            "--approved-by",
            "ryan",
        )[0]
        == 0
    )
    exit_code, switched = _run_cli(
        service,
        "activate",
        "--strategy-version",
        "alpha_topn_v2.20260510",
    )

    assert exit_code == 0
    assert switched["current_strategy"]["strategy_version"] == "alpha_topn_v2.20260510"
    versions = {item["strategy_version"]: item for item in service.list_versions()["items"]}
    assert versions["alpha_topn_v1.20260509"]["status"] == "retired"
    assert versions["alpha_topn_v2.20260510"]["status"] == "active"
    assert len(service.registry.list_active_versions()) == 1
    assert len(service.registry.list_activation_history()) == 2
    assert len(service.registry.list_events()) >= 5


def test_strategy_registry_current_returns_no_active_strategy_when_empty(tmp_path):
    service = _service(tmp_path)

    exit_code, payload = _run_cli(service, "current")

    assert exit_code == 0
    assert payload["status"] == "empty"
    assert payload["current_strategy"] is None
