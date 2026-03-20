from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


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


@dataclass(frozen=True)
class SourceFieldSpec:
    canonical_field: str
    source: str
    source_field: str
    unit_raw: str
    unit_normalized: str
    period_type: str
    data_type: str
    confidence: str = "medium"
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_field": self.canonical_field,
            "source": self.source,
            "source_field": self.source_field,
            "unit_raw": self.unit_raw,
            "unit_normalized": self.unit_normalized,
            "period_type": self.period_type,
            "data_type": self.data_type,
            "confidence": self.confidence,
            "notes": self.notes,
        }


FIELD_REGISTRY: Dict[str, SourceFieldSpec] = {
    "dividend_yield": SourceFieldSpec(
        canonical_field="dividend_yield",
        source="yfinance.dividends+market_price",
        source_field="dividends/currentPrice",
        unit_raw="currency_events_and_spot_price",
        unit_normalized="ratio",
        period_type="ttm",
        data_type="derived",
        confidence="high",
        notes=["Derived from trailing 12M cash dividends divided by spot price"],
    ),
    "payout_ratio": SourceFieldSpec(
        canonical_field="payout_ratio",
        source="yfinance.info",
        source_field="payoutRatio",
        unit_raw="ratio_snapshot",
        unit_normalized="ratio",
        period_type="ttm_or_snapshot",
        data_type="reported_snapshot",
        confidence="medium",
    ),
    "book_value_per_share": SourceFieldSpec(
        canonical_field="book_value_per_share",
        source="yfinance.info",
        source_field="bookValue",
        unit_raw="currency_per_share",
        unit_normalized="currency_per_share",
        period_type="spot",
        data_type="reported_snapshot",
        confidence="medium",
        notes=["Per-share field only; must not be used as total equity"],
    ),
    "held_percent_insiders": SourceFieldSpec(
        canonical_field="held_percent_insiders",
        source="yfinance.info",
        source_field="heldPercentInsiders",
        unit_raw="ratio_snapshot",
        unit_normalized="ratio",
        period_type="spot",
        data_type="reported_snapshot",
        confidence="medium",
    ),
    "held_percent_institutions": SourceFieldSpec(
        canonical_field="held_percent_institutions",
        source="yfinance.info",
        source_field="heldPercentInstitutions",
        unit_raw="ratio_snapshot",
        unit_normalized="ratio",
        period_type="spot",
        data_type="reported_snapshot",
        confidence="medium",
    ),
    "shares_percent_shares_out": SourceFieldSpec(
        canonical_field="shares_percent_shares_out",
        source="yfinance.info",
        source_field="sharesPercentSharesOut",
        unit_raw="ratio_snapshot",
        unit_normalized="ratio",
        period_type="spot",
        data_type="reported_snapshot",
        confidence="medium",
    ),
    "pe_ratio_ttm": SourceFieldSpec(
        canonical_field="pe_ratio_ttm",
        source="tushare.daily_basic",
        source_field="pe_ttm",
        unit_raw="multiple",
        unit_normalized="multiple",
        period_type="ttm",
        data_type="reported",
        confidence="high",
    ),
    "price_to_book": SourceFieldSpec(
        canonical_field="price_to_book",
        source="tushare.daily_basic",
        source_field="pb",
        unit_raw="multiple",
        unit_normalized="multiple",
        period_type="spot",
        data_type="reported",
        confidence="high",
    ),
    "roe": SourceFieldSpec(
        canonical_field="roe",
        source="tushare.fina_indicator",
        source_field="roe",
        unit_raw="percent",
        unit_normalized="ratio",
        period_type="reported_period",
        data_type="reported",
        confidence="high",
    ),
    "debt_to_assets_ratio": SourceFieldSpec(
        canonical_field="debt_to_assets_ratio",
        source="tushare.fina_indicator",
        source_field="debt_to_assets",
        unit_raw="percent",
        unit_normalized="ratio",
        period_type="reported_period",
        data_type="reported",
        confidence="high",
    ),
    "revenue_growth": SourceFieldSpec(
        canonical_field="revenue_growth",
        source="tushare.income",
        source_field="revenue",
        unit_raw="currency_period_values",
        unit_normalized="ratio",
        period_type="reported_period",
        data_type="derived",
        confidence="medium",
        notes=["Must be computed from same-period comparable reports only"],
    ),
}


def get_field_spec(canonical_field: str) -> Optional[SourceFieldSpec]:
    return FIELD_REGISTRY.get(canonical_field)


def format_ratio_as_percent(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def normalize_percent_to_ratio(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric / 100.0


def compute_trailing_dividend_yield(
    dividends: Any,
    current_price: Any,
    as_of: Optional[Any] = None,
) -> Optional[float]:
    try:
        price = float(current_price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    if dividends is None:
        return None

    series: Optional[pd.Series] = None
    if isinstance(dividends, pd.Series):
        series = dividends.dropna()
    elif isinstance(dividends, Iterable):
        rows = []
        for item in dividends:
            if not isinstance(item, dict):
                continue
            date_value = item.get("date")
            amount = item.get("amount")
            if date_value is None or amount is None:
                continue
            rows.append((pd.Timestamp(date_value), float(amount)))
        if rows:
            rows.sort(key=lambda item: item[0])
            series = pd.Series([row[1] for row in rows], index=[row[0] for row in rows])

    if series is None or series.empty:
        return None

    end = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(series.index.max())
    start = end - timedelta(days=365)
    trailing = series[(series.index > start) & (series.index <= end)]
    if trailing.empty:
        return None
    return float(trailing.sum()) / price


def select_latest_metric_column(
    df: pd.DataFrame, reserved: Optional[set[str]] = None
) -> Optional[str]:
    reserved = reserved or {"选项", "指标"}
    candidates = [col for col in df.columns if col not in reserved]
    if not candidates:
        return None
    dated: List[tuple[pd.Timestamp, str]] = []
    for col in candidates:
        try:
            dated.append((pd.Timestamp(str(col)), col))
        except Exception:
            continue
    if dated:
        dated.sort(reverse=True)
        return dated[0][1]
    return candidates[0]


def build_standard_field(
    canonical_field: str,
    value: Any,
    display_value: Any,
    as_of: Optional[str] = None,
    status: str = "available",
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    spec = get_field_spec(canonical_field)
    if spec is None:
        raise KeyError(f"Unknown field registry key: {canonical_field}")
    return StandardField(
        field=canonical_field,
        value=value,
        display_value=display_value,
        unit=spec.unit_normalized,
        period_type=spec.period_type,
        data_type=spec.data_type,
        source=spec.source,
        as_of=as_of,
        status=status,
        confidence=spec.confidence,
        notes=list(spec.notes) + (notes or []),
    ).to_dict()


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
