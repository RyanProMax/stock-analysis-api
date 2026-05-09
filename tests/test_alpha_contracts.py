from __future__ import annotations

import json
import math

import pytest

from src.model.alpha import AlphaCandidate, AlphaEvaluation
from src.model.strategy import StrategyProposal, StrategyVersion


def test_alpha_candidate_serializes_json_safe_values():
    candidate = AlphaCandidate(
        candidate_id="alpha-20260509-000001",
        universe_id="cn-watchlist",
        as_of="2026-05-09",
        market="cn",
        symbol="300827",
        factor_values={
            "momentum_20d": 0.12,
            "bad_value": math.inf,
            "nested": {"nan_value": math.nan},
        },
        score=math.nan,
        rank=1,
        reasons=["trend_confirmed", "volume_expansion"],
        data_quality="partial",
    )

    payload = candidate.to_dict()

    assert payload["factor_values"]["bad_value"] is None
    assert payload["factor_values"]["nested"]["nan_value"] is None
    assert payload["score"] is None
    json.dumps(payload, allow_nan=False)


def test_alpha_evaluation_requires_valid_sample_split_and_metrics():
    evaluation = AlphaEvaluation(
        evaluation_id="eval-20260509-momentum",
        candidate_id="alpha-20260509-000001",
        method="factor_ic",
        as_of="2026-05-09",
        forward_windows=[1, 5, 20],
        metrics={
            "rank_ic_mean": 0.08,
            "rank_ic_tstat": 2.1,
            "quantile_spread": 0.034,
            "turnover": 0.42,
        },
        sample_split={
            "train": {"start": "2026-01-01", "end": "2026-03-31"},
            "validation": {"start": "2026-04-01", "end": "2026-04-30"},
            "out_of_sample": {"start": "2026-05-01", "end": "2026-05-09"},
        },
        cost_model={"type": "fixed_bps", "bps": 10},
        data_gaps=[],
    )

    payload = evaluation.to_dict()

    assert payload["status"] == "ok"
    assert payload["forward_windows"] == [1, 5, 20]
    assert payload["metrics"]["rank_ic_mean"] == 0.08
    json.dumps(payload, allow_nan=False)


def test_alpha_evaluation_rejects_missing_out_of_sample_split():
    with pytest.raises(ValueError, match="out_of_sample"):
        AlphaEvaluation(
            evaluation_id="eval-20260509-momentum",
            candidate_id="alpha-20260509-000001",
            method="factor_ic",
            as_of="2026-05-09",
            forward_windows=[1, 5],
            metrics={"rank_ic_mean": 0.05},
            sample_split={"train": {"start": "2026-01-01", "end": "2026-03-31"}},
        )


def test_strategy_proposal_defaults_to_human_approval_required():
    proposal = StrategyProposal(
        proposal_id="proposal-20260509-alpha-topn",
        strategy_version="alpha_topn_v1.20260509",
        generated_at="2026-05-09T07:00:00+00:00",
        source="alpha_daily_report",
        proposed_changes=[
            {
                "type": "set_parameters",
                "parameters": {"top_n": 10, "rebalance": "1d"},
            }
        ],
        evidence={
            "alpha_evaluation_id": "eval-20260509-momentum",
            "rank_ic_mean": 0.08,
        },
    )

    payload = proposal.to_dict()

    assert payload["approval_required"] is True
    assert payload["effective_status"] == "candidate_only"
    assert payload["constraints"] == [
        "proposal_not_applied_to_runtime",
        "requires_human_approval",
        "agent_not_in_intraday_order_path",
    ]
    json.dumps(payload, allow_nan=False)


def test_strategy_version_allows_only_governed_statuses():
    active = StrategyVersion(
        strategy_version="alpha_topn_v1.20260509",
        status="active",
        source_proposal_id="proposal-20260509-alpha-topn",
        parameters={"top_n": 10},
        risk_limits={"max_weight": 0.1},
        created_at="2026-05-09T07:00:00+00:00",
        approved_by="ryan",
    )

    assert active.to_dict()["status"] == "active"

    with pytest.raises(ValueError, match="unsupported strategy status"):
        StrategyVersion(
            strategy_version="alpha_topn_v1.20260509",
            status="auto_applied",
            source_proposal_id="proposal-20260509-alpha-topn",
            parameters={},
            risk_limits={},
            created_at="2026-05-09T07:00:00+00:00",
        )
