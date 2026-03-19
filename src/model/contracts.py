from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StandardField:
    field: str
    value: Any
    display_value: Any
    unit: str
    period_type: str
    data_type: str
    source: str
    as_of: Optional[str] = None
    status: str = "available"
    confidence: str = "medium"
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "display_value": self.display_value,
            "unit": self.unit,
            "period_type": self.period_type,
            "data_type": self.data_type,
            "source": self.source,
            "as_of": self.as_of,
            "status": self.status,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class InterfaceMeta:
    as_of: Optional[str]
    sources: List[str] = field(default_factory=list)
    data_completeness: str = "partial"
    limitations: List[str] = field(default_factory=list)
    schema_version: str = "2.0.0"
    interface_type: str = "mixed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "sources": self.sources,
            "data_completeness": self.data_completeness,
            "limitations": self.limitations,
            "schema_version": self.schema_version,
            "interface_type": self.interface_type,
        }


@dataclass
class InterfacePayload:
    entity: Dict[str, Any]
    facts: Dict[str, Any]
    analysis: Dict[str, Any]
    meta: InterfaceMeta

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity": self.entity,
            "facts": self.facts,
            "analysis": self.analysis,
            "meta": self.meta.to_dict(),
        }
