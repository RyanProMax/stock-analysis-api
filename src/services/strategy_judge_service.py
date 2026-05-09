from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from ..model.serialization import json_safe
from ..model.strategy import StrategyJudgeVerdict, StrategyProposal


class StrategyJudgeService:
    def judge(
        self,
        *,
        proposal_payload: dict[str, Any],
        evaluation_payload: dict[str, Any],
        evaluator_id: str,
        researcher_id: str | None = None,
        min_rank_ic_mean: float = 0.03,
        min_quantile_spread: float = 0.0,
        max_turnover: float = 1.0,
        min_observations: int = 20,
        allow_data_gaps: bool = False,
    ) -> dict:
        proposal = self._proposal(proposal_payload)
        evaluation = self._evaluation(evaluation_payload)
        summary = evaluation["summary"]
        metrics = evaluation["metrics"]
        thresholds = {
            "min_rank_ic_mean": float(min_rank_ic_mean),
            "min_quantile_spread": float(min_quantile_spread),
            "max_turnover": float(max_turnover),
            "min_observations": int(min_observations),
            "allow_data_gaps": bool(allow_data_gaps),
        }
        reasons = self._reasons(
            evaluator_id=evaluator_id,
            researcher_id=researcher_id,
            metrics=metrics,
            summary=summary,
            thresholds=thresholds,
        )
        gate_status = "blocked" if reasons else "passed"
        verdict = StrategyJudgeVerdict(
            verdict_id=self._verdict_id(proposal, evaluation),
            proposal_id=proposal["proposal_id"],
            strategy_version=proposal["strategy_version"],
            evaluator_id=str(evaluator_id).strip(),
            researcher_id=researcher_id,
            generated_at=self._now(),
            gate_status=gate_status,
            evaluation_id=evaluation.get("evaluation_id"),
            thresholds=thresholds,
            metrics={
                "rank_ic_mean": metrics.get("rank_ic_mean"),
                "quantile_spread": metrics.get("quantile_spread"),
                "turnover": metrics.get("turnover"),
                "observations": summary.get("observations"),
                "data_gaps": summary.get("data_gaps") or [],
            },
            reasons=reasons,
            human_review_ready=gate_status == "passed",
        ).to_dict()
        return json_safe(
            {
                "status": gate_status,
                "source": "strategy_judge",
                "verdict": verdict,
                "strategy_proposal": proposal if gate_status == "passed" else None,
            }
        )

    def _proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("strategy_proposal") if "strategy_proposal" in payload else payload
        if not isinstance(source, dict):
            raise ValueError("proposal payload must be an object")
        normalized = {
            **source,
            "approval_required": source.get("approval_required", True),
            "effective_status": source.get("effective_status", "candidate_only"),
        }
        return StrategyProposal(**normalized).to_dict()

    def _evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("alpha_evaluation") if "alpha_evaluation" in payload else payload
        if not isinstance(source, dict):
            raise ValueError("evaluation payload must be an object")
        evaluation = (
            source.get("evaluation") if isinstance(source.get("evaluation"), dict) else source
        )
        summary = source.get("summary") if isinstance(source.get("summary"), dict) else {}
        metrics = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), dict) else {}
        data_gaps = list(summary.get("data_gaps") or []) + list(evaluation.get("data_gaps") or [])
        observations = summary.get("observations")
        if observations is None:
            observations = self._sample_observations(evaluation.get("sample_split") or {})
        return {
            "evaluation_id": evaluation.get("evaluation_id"),
            "summary": {
                "observations": int(observations or 0),
                "data_gaps": self._dedupe(data_gaps),
            },
            "metrics": metrics,
        }

    def _reasons(
        self,
        *,
        evaluator_id: str,
        researcher_id: str | None,
        metrics: dict[str, Any],
        summary: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        if not str(evaluator_id or "").strip():
            reasons.append("missing_evaluator_id")
        if researcher_id and str(evaluator_id).strip() == str(researcher_id).strip():
            reasons.append("evaluator_must_be_independent")
        rank_ic = self._float_or_none(metrics.get("rank_ic_mean"))
        if rank_ic is None:
            reasons.append("rank_ic_mean_missing")
        elif rank_ic < thresholds["min_rank_ic_mean"]:
            reasons.append("rank_ic_mean_below_threshold")
        spread = self._float_or_none(metrics.get("quantile_spread"))
        if spread is None:
            reasons.append("quantile_spread_missing")
        elif spread < thresholds["min_quantile_spread"]:
            reasons.append("quantile_spread_below_threshold")
        turnover = self._float_or_none(metrics.get("turnover"))
        if turnover is not None and turnover > thresholds["max_turnover"]:
            reasons.append("turnover_above_threshold")
        if int(summary.get("observations") or 0) < int(thresholds["min_observations"]):
            reasons.append("insufficient_observations")
        if summary.get("data_gaps") and not thresholds["allow_data_gaps"]:
            reasons.append("data_gaps_present")
        return reasons

    def _sample_observations(self, sample_split: dict[str, Any]) -> int:
        total = 0
        for section in sample_split.values():
            if isinstance(section, dict):
                total += int(section.get("observations") or 0)
        return total

    def _float_or_none(self, value) -> float | None:
        if value in (None, ""):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _verdict_id(self, proposal: dict[str, Any], evaluation: dict[str, Any]) -> str:
        evaluation_id = evaluation.get("evaluation_id") or "evaluation"
        return f"judge-{proposal['proposal_id']}-{evaluation_id}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
