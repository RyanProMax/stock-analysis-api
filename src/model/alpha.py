from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .serialization import json_safe

REQUIRED_SAMPLE_SPLITS = ("train", "validation", "out_of_sample")


@dataclass(frozen=True)
class AlphaCandidate:
    candidate_id: str
    universe_id: str
    as_of: str
    market: str
    symbol: str
    factor_values: dict[str, Any] = field(default_factory=dict)
    score: float | None = None
    rank: int | None = None
    reasons: list[str] = field(default_factory=list)
    data_quality: str = "unknown"
    status: str = "candidate"
    data_gaps: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id is required")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.rank is not None and self.rank <= 0:
            raise ValueError("rank must be positive")

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class AlphaEvaluation:
    evaluation_id: str
    candidate_id: str
    method: str
    as_of: str
    forward_windows: list[int]
    metrics: dict[str, Any] = field(default_factory=dict)
    sample_split: dict[str, Any] = field(default_factory=dict)
    cost_model: dict[str, Any] = field(default_factory=dict)
    data_gaps: list[str] = field(default_factory=list)
    status: str = "ok"

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ValueError("evaluation_id is required")
        if not self.candidate_id.strip():
            raise ValueError("candidate_id is required")
        if not self.method.strip():
            raise ValueError("method is required")
        if not self.forward_windows:
            raise ValueError("forward_windows must not be empty")
        if any(window <= 0 for window in self.forward_windows):
            raise ValueError("forward_windows must be positive")
        missing = [
            name for name in REQUIRED_SAMPLE_SPLITS if name not in self.sample_split
        ]
        if missing:
            raise ValueError(
                f"sample_split missing required section: {', '.join(missing)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))
