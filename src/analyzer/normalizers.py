from typing import Any, Dict, List, Optional

from ..model.contracts import (
    InterfaceMeta,
    InterfacePayload,
    StandardField,
    build_standard_field,
    compute_trailing_dividend_yield,
    format_ratio_as_percent,
    normalize_percent_to_ratio,
    select_latest_metric_column,
)


def _parse_percent(display_value: Any) -> Optional[float]:
    if display_value in (None, "N/A"):
        return None
    if isinstance(display_value, (int, float)):
        return float(display_value)
    text = str(display_value).strip().replace("%", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text) / 100.0
    except ValueError:
        return None


def _parse_number(display_value: Any) -> Optional[float]:
    if display_value in (None, "N/A"):
        return None
    if isinstance(display_value, (int, float)):
        return float(display_value)
    text = str(display_value).strip().replace(",", "")
    if text.endswith("x"):
        text = text[:-1]
    if text.startswith("$"):
        text = text[1:]
    multipliers = {"B": 1e9, "M": 1e6, "T": 1e12}
    if text and text[-1] in multipliers:
        try:
            return float(text[:-1]) * multipliers[text[-1]]
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def make_field(
    field: str,
    value: Any,
    display_value: Any,
    unit: str,
    period_type: str,
    data_type: str,
    source: str,
    as_of: Optional[str] = None,
    status: str = "available",
    confidence: str = "medium",
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return StandardField(
        field=field,
        value=value,
        display_value=display_value,
        unit=unit,
        period_type=period_type,
        data_type=data_type,
        source=source,
        as_of=as_of,
        status=status,
        confidence=confidence,
        notes=notes or [],
    ).to_dict()


def stock_record(record: Dict[str, Any], source: str = "stock_list_provider") -> Dict[str, Any]:
    return {
        "ts_code": record.get("ts_code", ""),
        "symbol": record.get("symbol", ""),
        "name": record.get("name", ""),
        "area": record.get("area"),
        "industry": record.get("industry"),
        "market": record.get("market"),
        "list_date": record.get("list_date"),
        "meta": {
            "source": source,
            "status": "available",
            "as_of": None,
        },
    }


def stock_analysis_contract(report: Dict[str, Any]) -> Dict[str, Any]:
    as_of = report.get("as_of")
    raw_info = report.get("fundamental", {}).get("raw_data", {}).get("info", {})
    normalized_fields = report.get("fundamental", {}).get("raw_data", {}).get("normalized_fields", {})
    fields = {}
    for factor in report.get("fundamental", {}).get("factors", []):
        key = factor.get("key")
        status = factor.get("status")
        if key in normalized_fields:
            fields[key] = normalized_fields[key]
            continue
        source = "yfinance.info"
        unit = "string"
        value = status
        period_type = "spot"
        if key in {"heldPercentInsiders", "heldPercentInstitutions", "sharesPercentSharesOut", "payoutRatio"}:
            unit = "ratio"
            value = _parse_percent(status)
        elif key in {"marketCap", "enterpriseValue", "totalCash", "totalDebt", "totalRevenue", "operatingCashflow", "freeCashflow", "ebitda", "netIncomeToCommon", "grossProfits"}:
            unit = "currency"
            value = raw_info.get(key)
        elif key in {"trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months", "enterpriseToEbitda", "enterpriseToRevenue", "trailingEps", "forwardEps", "revenuePerShare", "beta", "currentRatio", "quickRatio", "debtToEquity"}:
            unit = "number"
            value = _parse_number(status)
        elif key in {"profitMargins", "grossMargins", "operatingMargins", "ebitdaMargins", "returnOnAssets", "returnOnEquity", "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth"}:
            unit = "ratio"
            value = _parse_percent(status)
            period_type = "ttm"
        fields[key] = make_field(
            field=key,
            value=value,
            display_value=status,
            unit=unit,
            period_type=period_type,
            data_type="reported",
            source=source,
            as_of=as_of,
        )

    facts = {
        "market_snapshot": {
            "price": make_field("price", report.get("price"), report.get("price"), "currency", "spot", "reported", "market_data", as_of),
        },
        "fundamentals": fields,
    }
    analysis = {
        "fear_greed": {
            "index": make_field("fear_greed_index", report.get("fear_greed", {}).get("index"), report.get("fear_greed", {}).get("label"), "score", "spot", "derived", "technical_analysis", as_of),
        },
        "technical_signals": report.get("technical", {}).get("factors", []),
        "trend": report.get("trend_analysis"),
        "qlib": report.get("qlib", {}).get("factors", []),
    }
    payload = InterfacePayload(
        entity={"symbol": report.get("symbol"), "name": report.get("stock_name")},
        facts=facts,
        analysis=analysis,
        meta=InterfaceMeta(
            as_of=as_of,
            sources=[report.get("technical", {}).get("data_source", ""), report.get("fundamental", {}).get("data_source", "")],
            data_completeness="partial",
            limitations=["Derived technical signals are not reported facts"],
            interface_type="mixed",
        ),
    )
    return payload.to_dict()


def earnings_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    as_of = result.get("as_of")
    summary = result.get("earnings_summary", {})
    facts = {
        "quarterly": {
            "revenue": make_field("revenue", _parse_number(summary.get("revenue", {}).get("actual")), summary.get("revenue", {}).get("actual"), "currency", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
            "net_income": make_field("net_income", _parse_number(summary.get("net_income", {}).get("actual")), summary.get("net_income", {}).get("actual"), "currency", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
            "ebitda": make_field("ebitda", _parse_number(summary.get("ebitda", {}).get("actual")), summary.get("ebitda", {}).get("actual"), "currency", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
            "eps": make_field("eps", _parse_number(summary.get("earnings_per_share", {}).get("eps")), summary.get("earnings_per_share", {}).get("eps"), "currency_per_share", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
        },
        "consensus_comparison": result.get("beat_miss_analysis"),
    }
    if result.get("beat_miss_analysis", {}).get("status") == "unavailable":
        facts["consensus_comparison"]["status"] = "unavailable"
    analysis = {
        "estimated_segments": result.get("segment_performance", []),
        "guidance_interpretation": result.get("guidance", {}),
        "key_metrics": result.get("key_metrics", {}),
        "trends": result.get("trends", {}),
    }
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts=facts,
        analysis=analysis,
        meta=InterfaceMeta(
            as_of=as_of,
            sources=result.get("sources", []),
            data_completeness="partial",
            limitations=["Segment data may be estimated when company-level segment disclosure is unavailable"],
            interface_type="mixed",
        ),
    )
    payload.entity["quarter"] = result.get("quarter")
    payload.meta.to_dict()["quarter"] = result.get("quarter")
    data = payload.to_dict()
    data["meta"].update(
        {
            "quarter": result.get("quarter"),
            "fiscal_year": result.get("fiscal_year"),
            "fiscal_period": result.get("fiscal_period"),
            "report_date": result.get("report_date"),
        }
    )
    return data


def normalized_snapshot_field(
    canonical_field: str,
    value: Any,
    display_value: Any,
    as_of: Optional[str] = None,
    status: str = "available",
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return build_standard_field(
        canonical_field=canonical_field,
        value=value,
        display_value=display_value,
        as_of=as_of,
        status=status,
        notes=notes,
    )


def competitive_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    as_of = None
    peers = []
    for item in result.get("comparative", {}).get("comparison_table", []):
        peers.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "market_cap": make_field("market_cap", item.get("market_cap", 0) * 1e9, item.get("market_cap"), "currency", "spot", "reported", "yfinance.info", as_of),
                "revenue": make_field("revenue", item.get("revenue", 0) * 1e9, item.get("revenue"), "currency", "ttm", "reported", "yfinance.info", as_of),
                "growth": make_field("growth", (item.get("growth", 0) / 100.0), item.get("growth"), "ratio", "ttm", "reported", "yfinance.info", as_of),
            }
        )
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts={
            "company_profile": result.get("target_profile", {}),
            "peer_set": peers,
        },
        analysis={
            "market_context": result.get("market_context", {}),
            "positioning": result.get("positioning", {}),
            "comparative": result.get("comparative", {}),
            "moat_assessment": result.get("moat_assessment", {}),
            "industry_metrics": result.get("industry_metrics", {}),
            "scenario_analysis": result.get("scenario_analysis", {}),
        },
        meta=InterfaceMeta(
            as_of=as_of,
            sources=["yfinance.info"],
            data_completeness="partial",
            limitations=["Market context, moat, and scenario outputs are heuristic analysis"],
            interface_type="mixed",
        ),
    )
    data = payload.to_dict()
    data["meta"]["peer_selection"] = {
        "method": "hardcoded_industry_peer_map",
        "limitations": ["Peer universe is heuristic and may omit relevant companies"],
    }
    return data


def dcf_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    as_of = result.get("as_of")
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name"), "currency": result.get("currency")},
        facts={
            "inputs": {
                "current_price": make_field("current_price", result.get("current_price"), result.get("current_price"), "currency", "spot", "reported", "yfinance.info", as_of),
                "wacc": make_field("wacc", result.get("wacc") / 100.0 if result.get("wacc") is not None else None, result.get("wacc"), "ratio", "forward", "derived", "dcf_model", as_of),
                "fcf_history": {
                    "source": result.get("fcf_source"),
                    "status": result.get("data_completeness", "partial"),
                },
            }
        },
        analysis={
            "outputs": {
                "enterprise_value": result.get("enterprise_value"),
                "equity_value": result.get("equity_value"),
                "implied_price": result.get("implied_price"),
                "upside": result.get("upside"),
                "recommendation": result.get("recommendation"),
                "confidence": result.get("confidence"),
                "valuation_range": result.get("valuation_range"),
                "sensitivity": result.get("sensitivity"),
            }
        },
        meta=InterfaceMeta(
            as_of=as_of,
            sources=[result.get("fcf_source", ""), result.get("assumptions_source", "")],
            data_completeness=result.get("data_completeness", "partial"),
            limitations=["DCF output is a model estimate, not a reported market fact"],
            interface_type="model",
        ),
    )
    return payload.to_dict()


def comps_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    payload = InterfacePayload(
        entity={"symbol": result.get("target_symbol"), "name": result.get("target_name"), "sector": result.get("sector"), "industry": result.get("industry")},
        facts={
            "target": {
                "symbol": result.get("target_symbol"),
                "name": result.get("target_name"),
            },
            "peer_set": result.get("comps", []),
        },
        analysis={
            "operating_metrics": result.get("operating_metrics", {}),
            "valuation_multiples": result.get("valuation_multiples", {}),
            "percentiles": result.get("percentiles", {}),
            "implied_valuation": result.get("implied_valuation", {}),
            "recommendation": {
                "rating": result.get("recommendation"),
                "confidence": result.get("confidence"),
            },
        },
        meta=InterfaceMeta(
            as_of=None,
            sources=["yfinance.info"],
            data_completeness="partial",
            limitations=result.get("peer_selection_limitations", []),
            interface_type="mixed",
        ),
    )
    data = payload.to_dict()
    data["meta"]["peer_selection"] = {
        "method": result.get("peer_selection_method"),
        "universe": result.get("peer_universe", []),
    }
    return data


def lbo_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts={"baseline": {"purchase_price": result.get("purchase_price"), "current_price": result.get("current_price")}},
        analysis={"outputs": result},
        meta=InterfaceMeta(
            as_of=None,
            sources=[result.get("assumptions_source", "")],
            data_completeness="partial",
            limitations=["LBO output is scenario modeling based on assumptions"],
            interface_type="model",
        ),
    )
    return payload.to_dict()


def three_statement_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts={"baseline": {"historical_source": result.get("historical_source"), "as_of": result.get("as_of")}},
        analysis={"outputs": result},
        meta=InterfaceMeta(
            as_of=result.get("as_of"),
            sources=[result.get("historical_source", "")],
            data_completeness="partial",
            limitations=result.get("limitations", []),
            interface_type="model",
        ),
    )
    return payload.to_dict()
