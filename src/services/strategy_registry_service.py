from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from ..model.serialization import json_safe
from ..model.strategy import StrategyJudgeVerdict, StrategyProposal, StrategyVersion
from ..repositories.strategy_registry_repository import SqliteStrategyRegistry


class StrategyRegistryService:
    def __init__(self, registry: Optional[SqliteStrategyRegistry] = None) -> None:
        self.registry = registry or SqliteStrategyRegistry()

    def propose(self, proposal_payload: dict[str, Any]) -> dict:
        normalized = self._normalize_proposal(proposal_payload)
        proposal = StrategyProposal(**normalized).to_dict()
        parameters, risk_limits = self._extract_strategy_contract(proposal)
        version = StrategyVersion(
            strategy_version=proposal["strategy_version"],
            status="candidate",
            source_proposal_id=proposal["proposal_id"],
            parameters=parameters,
            risk_limits=risk_limits,
            created_at=proposal["generated_at"],
        ).to_dict()
        saved = self.registry.save_candidate_strategy(proposal=proposal, version=version)
        return json_safe(
            {
                "status": "ok",
                "source": "strategy_registry",
                "action": "propose",
                "proposal": proposal,
                "strategy_version": saved,
                "current_strategy": self.registry.current_strategy(),
                "events": self.registry.list_events(proposal["strategy_version"]),
            }
        )

    def approve(self, *, strategy_version: str, approved_by: str) -> dict:
        approved = self.registry.approve_strategy(
            strategy_version=strategy_version,
            approved_by=approved_by,
        )
        return json_safe(
            {
                "status": "ok",
                "source": "strategy_registry",
                "action": "approve",
                "strategy_version": approved,
                "approval": self.registry.latest_approval(strategy_version),
                "current_strategy": self.registry.current_strategy(),
                "events": self.registry.list_events(strategy_version),
            }
        )

    def activate(self, *, strategy_version: str) -> dict:
        result = self.registry.activate_strategy(strategy_version)
        return json_safe(
            {
                "status": "ok",
                "source": "strategy_registry",
                "action": "activate",
                "current_strategy": result["current_strategy"],
                "retired_strategies": result["retired_strategies"],
                "activation": result["activation"],
                "events": self.registry.list_events(strategy_version),
            }
        )

    def current(self) -> dict:
        current_strategy = self.registry.current_strategy()
        return json_safe(
            {
                "status": "ok" if current_strategy else "empty",
                "source": "strategy_registry",
                "action": "current",
                "current_strategy": current_strategy,
            }
        )

    def list_versions(self) -> dict:
        items = self.registry.list_versions()
        return json_safe(
            {
                "status": "ok" if items else "empty",
                "source": "strategy_registry",
                "action": "list",
                "items": items,
            }
        )

    def record_alpha_candidate(self, candidate: dict[str, Any]) -> dict:
        record = self.registry.record_alpha_candidate(candidate)
        return json_safe(
            {
                "status": "ok",
                "source": "strategy_registry",
                "action": "record_alpha_candidate",
                "record": record,
            }
        )

    def record_alpha_evaluation(self, evaluation: dict[str, Any]) -> dict:
        record = self.registry.record_alpha_evaluation(evaluation)
        return json_safe(
            {
                "status": "ok",
                "source": "strategy_registry",
                "action": "record_alpha_evaluation",
                "record": record,
            }
        )

    def record_judge_verdict(self, verdict: dict[str, Any]) -> dict:
        normalized = StrategyJudgeVerdict(**verdict).to_dict()
        record = self.registry.record_judge_verdict(normalized)
        return json_safe(
            {
                "status": "ok",
                "source": "strategy_registry",
                "action": "record_judge_verdict",
                "record": record,
                "current_strategy": self.registry.current_strategy(),
                "events": self.registry.list_events(normalized.get("strategy_version")),
            }
        )

    def record_research_loop_run(self, run: dict[str, Any]) -> dict:
        if not isinstance(run, dict):
            raise ValueError("research loop run payload must be an object")
        record = self.registry.record_research_loop_run(json_safe(run))
        return json_safe(
            {
                "status": "ok",
                "source": "strategy_registry",
                "action": "record_research_loop_run",
                "record": record,
                "current_strategy": self.registry.current_strategy(),
            }
        )

    def research_history(self, *, limit: int = 20) -> dict:
        runs = self.registry.list_research_loop_runs(limit=max(int(limit), 0))
        reason_counts: Counter[str] = Counter()
        factor_attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run in runs:
            payload = run.get("payload") or {}
            for attempt in payload.get("attempts") or []:
                if not isinstance(attempt, dict):
                    continue
                for reason in attempt.get("judge_reasons") or []:
                    reason_counts[str(reason)] += 1
                factor = str(attempt.get("factor") or "").strip()
                if not factor:
                    continue
                metrics = attempt.get("metrics") if isinstance(attempt.get("metrics"), dict) else {}
                factor_attempts[factor].append(
                    {
                        "run_id": run.get("run_id"),
                        "status": attempt.get("status"),
                        "rank_ic_mean": self._float_or_none(metrics.get("rank_ic_mean")),
                        "quantile_spread": self._float_or_none(metrics.get("quantile_spread")),
                        "recorded_at": run.get("recorded_at"),
                    }
                )
        factor_drift = {
            factor: self._factor_drift(attempts)
            for factor, attempts in sorted(factor_attempts.items())
        }
        summary = {
            "runs": len(runs),
            "human_review_ready_runs": sum(
                1 for run in runs if run.get("status") == "human_review_ready"
            ),
            "blocked_runs": sum(1 for run in runs if run.get("status") == "needs_iteration"),
            "top_block_reasons": [
                {"reason": reason, "count": count} for reason, count in reason_counts.most_common()
            ],
        }
        return json_safe(
            {
                "status": "ok" if runs else "empty",
                "source": "strategy_registry",
                "action": "research_history",
                "summary": summary,
                "factor_drift": factor_drift,
                "items": runs,
                "current_strategy": self.registry.current_strategy(),
            }
        )

    def _normalize_proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_payload = (
            payload.get("strategy_proposal") if "strategy_proposal" in payload else payload
        )
        if not isinstance(source_payload, dict):
            raise ValueError("proposal payload must be an object")
        strategy_version = str(source_payload.get("strategy_version") or "").strip()
        if not strategy_version:
            raise ValueError("strategy_version is required")
        generated_at = str(source_payload.get("generated_at") or self._now()).strip()
        proposal_id = str(
            source_payload.get("proposal_id") or f"proposal-{strategy_version}-{generated_at[:10]}"
        ).strip()
        source = str(source_payload.get("source") or payload.get("source") or "strategy_registry")
        return {
            **source_payload,
            "proposal_id": proposal_id,
            "strategy_version": strategy_version,
            "generated_at": generated_at,
            "source": source,
        }

    def _extract_strategy_contract(self, proposal: dict[str, Any]) -> tuple[dict, dict]:
        parameters: dict[str, Any] = {}
        risk_limits: dict[str, Any] = {}
        for change in proposal.get("proposed_changes") or []:
            if not isinstance(change, dict):
                continue
            if isinstance(change.get("parameters"), dict):
                parameters.update(change["parameters"])
            if isinstance(change.get("risk_limits"), dict):
                risk_limits.update(change["risk_limits"])
        return parameters, risk_limits

    def _factor_drift(self, attempts: list[dict[str, Any]]) -> dict[str, Any]:
        latest = attempts[-1]
        previous = attempts[-2] if len(attempts) > 1 else None
        latest_rank_ic = latest.get("rank_ic_mean")
        previous_rank_ic = previous.get("rank_ic_mean") if previous else None
        return {
            "attempts": len(attempts),
            "latest_status": latest.get("status"),
            "latest_rank_ic_mean": latest_rank_ic,
            "previous_rank_ic_mean": previous_rank_ic,
            "rank_ic_mean_change": (
                latest_rank_ic - previous_rank_ic
                if latest_rank_ic is not None and previous_rank_ic is not None
                else None
            ),
            "latest_quantile_spread": latest.get("quantile_spread"),
            "latest_run_id": latest.get("run_id"),
        }

    def _float_or_none(self, value) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
