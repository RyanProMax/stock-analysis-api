from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .serialization import json_safe

GOVERNED_STRATEGY_STATUSES = {
    "draft",
    "candidate",
    "approved",
    "active",
    "retired",
    "rejected",
}

DEFAULT_PROPOSAL_CONSTRAINTS = [
    "proposal_not_applied_to_runtime",
    "requires_human_approval",
    "agent_not_in_intraday_order_path",
]

JUDGE_VERDICT_STATUSES = {"passed", "blocked"}

DEFAULT_JUDGE_CONSTRAINTS = [
    "judge_not_strategy_author",
    "verdict_not_applied_to_runtime",
    "requires_human_review",
    "agent_not_in_intraday_order_path",
]


@dataclass(frozen=True)
class StrategyProposal:
    proposal_id: str
    strategy_version: str
    generated_at: str
    source: str
    proposed_changes: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = True
    effective_status: str = "candidate_only"
    constraints: list[str] = field(default_factory=lambda: list(DEFAULT_PROPOSAL_CONSTRAINTS))
    status: str = "candidate"

    def __post_init__(self) -> None:
        if not self.proposal_id.strip():
            raise ValueError("proposal_id is required")
        if not self.strategy_version.strip():
            raise ValueError("strategy_version is required")
        if self.approval_required is not True:
            raise ValueError("strategy proposals must require human approval")
        if self.effective_status != "candidate_only":
            raise ValueError("strategy proposals cannot be applied directly")

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class StrategyVersion:
    strategy_version: str
    status: str
    source_proposal_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_limits: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    approved_by: str | None = None
    retired_at: str | None = None

    def __post_init__(self) -> None:
        if not self.strategy_version.strip():
            raise ValueError("strategy_version is required")
        if self.status not in GOVERNED_STRATEGY_STATUSES:
            raise ValueError(f"unsupported strategy status: {self.status}")
        if self.status in {"approved", "active"} and not (self.approved_by or "").strip():
            raise ValueError("approved_by is required for approved or active strategies")

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class StrategyJudgeVerdict:
    verdict_id: str
    proposal_id: str
    strategy_version: str
    evaluator_id: str
    generated_at: str
    gate_status: str
    researcher_id: str | None = None
    evaluation_id: str | None = None
    thresholds: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    human_review_ready: bool = False
    proposal_not_applied: bool = True
    constraints: list[str] = field(default_factory=lambda: list(DEFAULT_JUDGE_CONSTRAINTS))

    def __post_init__(self) -> None:
        if not self.verdict_id.strip():
            raise ValueError("verdict_id is required")
        if not self.proposal_id.strip():
            raise ValueError("proposal_id is required")
        if not self.strategy_version.strip():
            raise ValueError("strategy_version is required")
        if not self.evaluator_id.strip():
            raise ValueError("evaluator_id is required")
        if self.gate_status not in JUDGE_VERDICT_STATUSES:
            raise ValueError(f"unsupported judge gate status: {self.gate_status}")
        if self.proposal_not_applied is not True:
            raise ValueError("judge verdict cannot be applied directly")
        if self.gate_status == "blocked" and self.human_review_ready:
            raise ValueError("blocked verdict cannot be human-review ready")

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))
