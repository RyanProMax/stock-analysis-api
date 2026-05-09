from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..model.serialization import json_safe
from ..model.strategy import StrategyProposal, StrategyVersion
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

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
