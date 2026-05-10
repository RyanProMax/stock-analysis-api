from __future__ import annotations

from io import StringIO
import json

from src.repositories.strategy_registry_repository import SqliteStrategyRegistry
from src.services.strategy_judge_cli import main as strategy_judge_cli_main
from src.services.strategy_registry_cli import main as strategy_registry_cli_main
from src.services.strategy_registry_service import StrategyRegistryService


def _proposal() -> dict:
    return {
        "proposal_id": "proposal-alpha-daily-2026-05-12-momentum_5d",
        "strategy_version": "alpha_topn_momentum_5d.20260512",
        "generated_at": "2026-05-12T08:00:00+00:00",
        "source": "researcher-agent",
        "proposed_changes": [
            {
                "type": "register_alpha_topn_candidate",
                "parameters": {
                    "market": "cn",
                    "factor": "momentum_5d",
                    "top_n": 10,
                    "forward_windows": [1, 3],
                },
            }
        ],
        "evidence": {"alpha_evaluation_id": "alpha-eval-2026-05-12-momentum_5d"},
        "approval_required": True,
        "effective_status": "candidate_only",
    }


def _evaluation(
    *,
    rank_ic_mean: float | None = 0.08,
    quantile_spread: float | None = 0.03,
    turnover: float | None = 0.2,
    observations: int = 30,
    data_gaps: list[str] | None = None,
) -> dict:
    return {
        "status": "ok" if not data_gaps else "partial",
        "source": "alpha_evaluate",
        "summary": {
            "symbols": 10,
            "observations": observations,
            "data_gaps": data_gaps or [],
        },
        "evaluation": {
            "evaluation_id": "alpha-eval-2026-05-12-momentum_5d",
            "candidate_id": "factor:momentum_5d",
            "method": "factor_forward_returns",
            "as_of": "2026-05-12",
            "forward_windows": [1, 3],
            "metrics": {
                "rank_ic_mean": rank_ic_mean,
                "rank_ic_tstat": 2.1,
                "quantile_spread": quantile_spread,
                "turnover": turnover,
            },
            "sample_split": {
                "train": {"observations": 18},
                "validation": {"observations": 6},
                "out_of_sample": {"observations": 6},
            },
            "data_gaps": data_gaps or [],
            "status": "ok" if not data_gaps else "partial",
        },
    }


def _champion_verdict() -> dict:
    return {
        "verdict_id": "judge-proposal-active-eval-active",
        "proposal_id": "proposal-active",
        "strategy_version": "alpha_topn_momentum_5d.20260501",
        "evaluator_id": "judge-agent",
        "generated_at": "2026-05-01T08:00:00+00:00",
        "gate_status": "passed",
        "researcher_id": "researcher-agent",
        "evaluation_id": "eval-active",
        "thresholds": {"min_rank_ic_mean": 0.03},
        "metrics": {
            "rank_ic_mean": 0.08,
            "quantile_spread": 0.025,
            "turnover": 0.2,
            "observations": 60,
        },
        "reasons": [],
        "human_review_ready": True,
        "proposal_not_applied": True,
    }


def _write_json(tmp_path, name: str, payload: dict):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _run_judge(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = strategy_judge_cli_main(list(args), writer=writer)
    return exit_code, json.loads(writer.getvalue())


def _run_registry(service: StrategyRegistryService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = strategy_registry_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_strategy_judge_passes_when_metrics_meet_thresholds_without_applying(tmp_path):
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal())
    evaluation_path = _write_json(tmp_path, "evaluation.json", _evaluation())

    exit_code, payload = _run_judge(
        "--proposal-json",
        str(proposal_path),
        "--evaluation-json",
        str(evaluation_path),
        "--evaluator-id",
        "judge-agent",
        "--researcher-id",
        "researcher-agent",
        "--min-rank-ic-mean",
        "0.05",
        "--min-quantile-spread",
        "0.01",
        "--max-turnover",
        "0.5",
        "--min-observations",
        "20",
    )

    assert exit_code == 0
    assert payload["status"] == "passed"
    assert payload["source"] == "strategy_judge"
    verdict = payload["verdict"]
    assert verdict["gate_status"] == "passed"
    assert verdict["human_review_ready"] is True
    assert verdict["proposal_not_applied"] is True
    assert verdict["evaluator_id"] == "judge-agent"
    assert verdict["researcher_id"] == "researcher-agent"
    assert verdict["reasons"] == []
    assert "judge_not_strategy_author" in verdict["constraints"]
    assert payload["strategy_proposal"]["proposal_id"] == _proposal()["proposal_id"]
    json.dumps(payload, allow_nan=False)


def test_strategy_judge_blocks_failed_metrics_and_same_agent_evaluation(tmp_path):
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal())
    evaluation_path = _write_json(
        tmp_path,
        "evaluation.json",
        _evaluation(rank_ic_mean=0.01, quantile_spread=-0.01, observations=8, data_gaps=["gap"]),
    )

    exit_code, payload = _run_judge(
        "--proposal-json",
        str(proposal_path),
        "--evaluation-json",
        str(evaluation_path),
        "--evaluator-id",
        "researcher-agent",
        "--researcher-id",
        "researcher-agent",
        "--min-rank-ic-mean",
        "0.05",
        "--min-quantile-spread",
        "0.01",
        "--max-turnover",
        "0.5",
        "--min-observations",
        "20",
    )

    assert exit_code == 0
    assert payload["status"] == "blocked"
    verdict = payload["verdict"]
    assert verdict["gate_status"] == "blocked"
    assert verdict["human_review_ready"] is False
    assert payload["strategy_proposal"] is None
    assert "evaluator_must_be_independent" in verdict["reasons"]
    assert "rank_ic_mean_below_threshold" in verdict["reasons"]
    assert "quantile_spread_below_threshold" in verdict["reasons"]
    assert "insufficient_observations" in verdict["reasons"]
    assert "data_gaps_present" in verdict["reasons"]
    json.dumps(payload, allow_nan=False)


def test_strategy_judge_blocks_challenger_that_does_not_improve_on_champion(tmp_path):
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal())
    evaluation_path = _write_json(
        tmp_path,
        "evaluation.json",
        _evaluation(rank_ic_mean=0.081, quantile_spread=0.026, observations=80),
    )
    champion_path = _write_json(tmp_path, "champion.json", _champion_verdict())

    exit_code, payload = _run_judge(
        "--proposal-json",
        str(proposal_path),
        "--evaluation-json",
        str(evaluation_path),
        "--champion-json",
        str(champion_path),
        "--evaluator-id",
        "judge-agent",
        "--researcher-id",
        "researcher-agent",
        "--min-rank-ic-mean",
        "0.03",
        "--min-quantile-spread",
        "0.0",
        "--min-challenger-rank-ic-delta",
        "0.01",
        "--min-challenger-quantile-spread-delta",
        "0.005",
        "--min-observations",
        "20",
    )

    assert exit_code == 0
    assert payload["status"] == "blocked"
    verdict = payload["verdict"]
    assert "challenger_rank_ic_not_improved" in verdict["reasons"]
    assert "challenger_quantile_spread_not_improved" in verdict["reasons"]
    assert verdict["metrics"]["champion"]["strategy_version"] == "alpha_topn_momentum_5d.20260501"
    assert verdict["metrics"]["improvement"]["rank_ic_mean_delta"] == 0.001
    assert verdict["metrics"]["improvement"]["quantile_spread_delta"] == 0.001
    assert payload["strategy_proposal"] is None
    json.dumps(payload, allow_nan=False)


def test_strategy_judge_passes_challenger_when_it_beats_active_champion(tmp_path):
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal())
    evaluation_path = _write_json(
        tmp_path,
        "evaluation.json",
        _evaluation(rank_ic_mean=0.10, quantile_spread=0.04, observations=80),
    )
    champion_path = _write_json(tmp_path, "champion.json", _champion_verdict())

    exit_code, payload = _run_judge(
        "--proposal-json",
        str(proposal_path),
        "--evaluation-json",
        str(evaluation_path),
        "--champion-json",
        str(champion_path),
        "--evaluator-id",
        "judge-agent",
        "--researcher-id",
        "researcher-agent",
        "--min-rank-ic-mean",
        "0.03",
        "--min-quantile-spread",
        "0.0",
        "--min-challenger-rank-ic-delta",
        "0.01",
        "--min-challenger-quantile-spread-delta",
        "0.005",
        "--min-observations",
        "20",
    )

    assert exit_code == 0
    assert payload["status"] == "passed"
    assert payload["verdict"]["metrics"]["champion"]["rank_ic_mean"] == 0.08
    assert payload["verdict"]["metrics"]["improvement"]["rank_ic_mean_delta"] == 0.02
    assert payload["strategy_proposal"]["proposal_id"] == _proposal()["proposal_id"]
    json.dumps(payload, allow_nan=False)


def test_strategy_registry_records_judge_verdict_without_approval(tmp_path):
    registry = SqliteStrategyRegistry(tmp_path / "strategy_registry.sqlite")
    service = StrategyRegistryService(registry=registry)
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal())
    verdict_path = _write_json(
        tmp_path,
        "verdict.json",
        _run_judge(
            "--proposal-json",
            str(proposal_path),
            "--evaluation-json",
            str(_write_json(tmp_path, "evaluation.json", _evaluation())),
            "--evaluator-id",
            "judge-agent",
            "--researcher-id",
            "researcher-agent",
        )[1]["verdict"],
    )

    exit_code, payload = _run_registry(
        service,
        "record-verdict",
        "--verdict-json",
        str(verdict_path),
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["action"] == "record_judge_verdict"
    assert payload["record"]["verdict"]["gate_status"] == "passed"
    assert service.current()["current_strategy"] is None
    assert registry.list_judge_verdicts()[0]["verdict"]["evaluator_id"] == "judge-agent"


def test_strategy_registry_rejects_applied_judge_verdict(tmp_path):
    registry = SqliteStrategyRegistry(tmp_path / "strategy_registry.sqlite")
    service = StrategyRegistryService(registry=registry)
    proposal_path = _write_json(tmp_path, "proposal.json", _proposal())
    verdict = _run_judge(
        "--proposal-json",
        str(proposal_path),
        "--evaluation-json",
        str(_write_json(tmp_path, "evaluation.json", _evaluation())),
        "--evaluator-id",
        "judge-agent",
        "--researcher-id",
        "researcher-agent",
    )[1]["verdict"]
    verdict["proposal_not_applied"] = False
    verdict_path = _write_json(tmp_path, "verdict.json", verdict)

    exit_code, payload = _run_registry(
        service,
        "record-verdict",
        "--verdict-json",
        str(verdict_path),
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "cannot be applied directly" in payload["error"]
    assert registry.list_judge_verdicts() == []
