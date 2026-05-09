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


def _research_loop_run(
    *,
    run_id: str,
    factor: str,
    rank_ic_mean: float,
    status: str = "needs_iteration",
    judge_reasons: list[str] | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "status": status,
        "source": "alpha_research_loop",
        "computed_at": f"2026-05-{run_id[-2:]}T08:00:00+00:00",
        "team": {
            "researcher": {"id": "researcher-agent"},
            "backtester": {"id": "backtester-agent"},
            "evaluator": {"id": "judge-agent"},
        },
        "request": {"market": "cn", "factors": [factor]},
        "summary": {
            "iterations": 1,
            "passed_attempts": 1 if status == "human_review_ready" else 0,
            "blocked_attempts": 0 if status == "human_review_ready" else 1,
            "selected_factor": factor if status == "human_review_ready" else None,
            "approval_required": True,
            "proposal_not_applied": True,
        },
        "attempts": [
            {
                "iteration": 1,
                "factor": factor,
                "status": "passed" if status == "human_review_ready" else "blocked",
                "metrics": {"rank_ic_mean": rank_ic_mean, "quantile_spread": 0.02},
                "judge_reasons": judge_reasons or [],
            }
        ],
        "selected": {"factor": factor} if status == "human_review_ready" else None,
        "next_research_actions": [] if status == "human_review_ready" else ["revise_factor"],
    }


def _passed_verdict(strategy_version: str, proposal_id: str | None = None) -> dict:
    proposal_id = proposal_id or f"proposal-{strategy_version}"
    return {
        "verdict_id": f"judge-{proposal_id}-eval-20260509",
        "proposal_id": proposal_id,
        "strategy_version": strategy_version,
        "evaluator_id": "judge-agent",
        "generated_at": "2026-05-09T14:00:00+00:00",
        "gate_status": "passed",
        "researcher_id": "researcher-agent",
        "evaluation_id": "eval-20260509",
        "thresholds": {"min_rank_ic_mean": 0.03},
        "metrics": {"rank_ic_mean": 0.08, "observations": 30},
        "reasons": [],
        "human_review_ready": True,
        "proposal_not_applied": True,
    }


def _record_passed_verdict(service: StrategyRegistryService, strategy_version: str) -> None:
    assert service.record_judge_verdict(_passed_verdict(strategy_version))["status"] == "ok"


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


def test_strategy_registry_approve_requires_passed_judge_verdict(tmp_path):
    service = _service(tmp_path)
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal("alpha_topn_v1.20260509"))
    assert _run_cli(service, "propose", "--proposal-json", str(proposal_path))[0] == 0

    exit_code, payload = _run_cli(
        service,
        "approve",
        "--strategy-version",
        "alpha_topn_v1.20260509",
        "--approved-by",
        "ryan",
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "passed judge verdict required" in payload["error"]
    assert service.current()["current_strategy"] is None


def test_strategy_registry_approve_requires_verdict_for_same_proposal(tmp_path):
    service = _service(tmp_path)
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal("alpha_topn_v1.20260509"))
    assert _run_cli(service, "propose", "--proposal-json", str(proposal_path))[0] == 0
    assert (
        service.record_judge_verdict(
            _passed_verdict("alpha_topn_v1.20260509", proposal_id="different-proposal")
        )["status"]
        == "ok"
    )

    exit_code, payload = _run_cli(
        service,
        "approve",
        "--strategy-version",
        "alpha_topn_v1.20260509",
        "--approved-by",
        "ryan",
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "passed judge verdict required" in payload["error"]
    assert service.current()["current_strategy"] is None


def test_strategy_registry_approve_then_activate_allows_single_active_strategy(tmp_path):
    service = _service(tmp_path)
    first = _write_json(tmp_path, "proposal-1.json", _proposal("alpha_topn_v1.20260509"))
    second = _write_json(tmp_path, "proposal-2.json", _proposal("alpha_topn_v2.20260510"))
    assert _run_cli(service, "propose", "--proposal-json", str(first))[0] == 0
    _record_passed_verdict(service, "alpha_topn_v1.20260509")
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
    _record_passed_verdict(service, "alpha_topn_v2.20260510")
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


def test_strategy_registry_rejects_reapprove_active_strategy(tmp_path):
    service = _service(tmp_path)
    proposal = _write_json(tmp_path, "proposal.json", _proposal("alpha_topn_v1.20260509"))
    assert _run_cli(service, "propose", "--proposal-json", str(proposal))[0] == 0
    _record_passed_verdict(service, "alpha_topn_v1.20260509")
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
    assert _run_cli(service, "activate", "--strategy-version", "alpha_topn_v1.20260509")[0] == 0

    exit_code, payload = _run_cli(
        service,
        "approve",
        "--strategy-version",
        "alpha_topn_v1.20260509",
        "--approved-by",
        "ryan",
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "only candidate strategies can be approved" in payload["error"]
    assert service.current()["current_strategy"]["strategy_version"] == "alpha_topn_v1.20260509"
    assert service.current()["current_strategy"]["status"] == "active"


def test_strategy_registry_rejects_reactivate_active_or_retired_strategy(tmp_path):
    service = _service(tmp_path)
    first = _write_json(tmp_path, "proposal-1.json", _proposal("alpha_topn_v1.20260509"))
    second = _write_json(tmp_path, "proposal-2.json", _proposal("alpha_topn_v2.20260510"))
    for proposal in (first, second):
        assert _run_cli(service, "propose", "--proposal-json", str(proposal))[0] == 0
    for version in ("alpha_topn_v1.20260509", "alpha_topn_v2.20260510"):
        _record_passed_verdict(service, version)
        assert (
            _run_cli(
                service,
                "approve",
                "--strategy-version",
                version,
                "--approved-by",
                "ryan",
            )[0]
            == 0
        )
    assert _run_cli(service, "activate", "--strategy-version", "alpha_topn_v1.20260509")[0] == 0

    exit_code, active_payload = _run_cli(
        service,
        "activate",
        "--strategy-version",
        "alpha_topn_v1.20260509",
    )

    assert exit_code == 2
    assert "only approved strategies can be activated" in active_payload["error"]
    assert _run_cli(service, "activate", "--strategy-version", "alpha_topn_v2.20260510")[0] == 0

    exit_code, retired_payload = _run_cli(
        service,
        "activate",
        "--strategy-version",
        "alpha_topn_v1.20260509",
    )

    assert exit_code == 2
    assert "only approved strategies can be activated" in retired_payload["error"]
    assert service.current()["current_strategy"]["strategy_version"] == "alpha_topn_v2.20260510"
    assert len(service.registry.list_activation_history()) == 2


def test_strategy_registry_current_returns_no_active_strategy_when_empty(tmp_path):
    service = _service(tmp_path)

    exit_code, payload = _run_cli(service, "current")

    assert exit_code == 0
    assert payload["status"] == "empty"
    assert payload["current_strategy"] is None


def test_strategy_registry_research_history_summarizes_runs_and_factor_drift(tmp_path):
    service = _service(tmp_path)
    first = service.record_research_loop_run(
        _research_loop_run(
            run_id="research-loop-20260511",
            factor="momentum_5d",
            rank_ic_mean=0.04,
            judge_reasons=["rank_ic_mean_below_threshold"],
        )
    )
    second = service.record_research_loop_run(
        _research_loop_run(
            run_id="research-loop-20260512",
            factor="momentum_5d",
            rank_ic_mean=0.09,
            status="human_review_ready",
        )
    )
    assert first["status"] == "ok"
    assert second["status"] == "ok"

    exit_code, payload = _run_cli(service, "research-history", "--limit", "10")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["action"] == "research_history"
    assert payload["summary"]["runs"] == 2
    assert payload["summary"]["human_review_ready_runs"] == 1
    assert payload["summary"]["blocked_runs"] == 1
    assert payload["summary"]["top_block_reasons"][0]["reason"] == "rank_ic_mean_below_threshold"
    factor = payload["factor_drift"]["momentum_5d"]
    assert factor["attempts"] == 2
    assert factor["latest_rank_ic_mean"] == 0.09
    assert factor["previous_rank_ic_mean"] == 0.04
    assert round(factor["rank_ic_mean_change"], 6) == 0.05
    assert payload["current_strategy"] is None
    json.dumps(payload, allow_nan=False)
