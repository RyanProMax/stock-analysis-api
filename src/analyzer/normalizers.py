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
from ..data_provider.fundamental_context import (
    build_fundamental_context,
    extract_company_profile_fields,
    extract_fundamental_detail_fields,
)
from .research_strategy import build_earnings_research_strategy


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


def _normalize_sources(*source_groups: Any) -> List[str]:
    normalized: List[str] = []
    for group in source_groups:
        if isinstance(group, str):
            text = group.strip()
            if text and text not in normalized:
                normalized.append(text)
            continue
        if isinstance(group, dict):
            provider = str(group.get("provider") or "").strip()
            result = str(group.get("result") or "").strip().lower()
            if result in {"not_supported", "failed"}:
                continue
            if provider and provider not in normalized:
                normalized.append(provider)
            continue
        if isinstance(group, (list, tuple)):
            for item in group:
                for source in _normalize_sources(item):
                    if source not in normalized:
                        normalized.append(source)
    return normalized


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


def watch_poll_contract(item: Dict[str, Any]) -> Dict[str, Any]:
    computed_at = item.get("computed_at")
    quote = item.get("quote", {})
    fundamentals = item.get("fundamentals", {})
    technical = item.get("technical", {})
    earnings_watch = item.get("earnings_watch", {})

    facts = {
        "quote": {
            "price": make_field(
                "price",
                quote.get("price"),
                quote.get("price"),
                "currency",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("price") is not None else "unavailable",
            ),
            "change_pct": make_field(
                "change_pct",
                quote.get("change_pct"),
                format_ratio_as_percent(quote.get("change_pct")),
                "ratio",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("change_pct") is not None else "unavailable",
            ),
            "change_amount": make_field(
                "change_amount",
                quote.get("change_amount"),
                quote.get("change_amount"),
                "currency",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("change_amount") is not None else "unavailable",
            ),
            "open": make_field(
                "open",
                quote.get("open"),
                quote.get("open"),
                "currency",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("open") is not None else "unavailable",
            ),
            "high": make_field(
                "high",
                quote.get("high"),
                quote.get("high"),
                "currency",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("high") is not None else "unavailable",
            ),
            "low": make_field(
                "low",
                quote.get("low"),
                quote.get("low"),
                "currency",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("low") is not None else "unavailable",
            ),
            "pre_close": make_field(
                "pre_close",
                quote.get("pre_close"),
                quote.get("pre_close"),
                "currency",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("pre_close") is not None else "unavailable",
            ),
            "volume": make_field(
                "volume",
                quote.get("volume"),
                quote.get("volume"),
                "shares",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("volume") is not None else "unavailable",
            ),
            "amount": make_field(
                "amount",
                quote.get("amount"),
                quote.get("amount"),
                "currency",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("amount") is not None else "unavailable",
            ),
            "turnover_rate": make_field(
                "turnover_rate",
                quote.get("turnover_rate"),
                format_ratio_as_percent(quote.get("turnover_rate")),
                "ratio",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("turnover_rate") is not None else "unavailable",
            ),
            "amplitude": make_field(
                "amplitude",
                quote.get("amplitude"),
                format_ratio_as_percent(quote.get("amplitude")),
                "ratio",
                "spot",
                "reported",
                quote.get("source") or "market_data",
                quote.get("as_of") or computed_at,
                status="available" if quote.get("amplitude") is not None else "unavailable",
            ),
        },
        "fundamentals": {
            "pe_ratio": make_field(
                "pe_ratio",
                fundamentals.get("pe_ratio"),
                fundamentals.get("pe_ratio"),
                "multiple",
                "spot",
                "reported",
                fundamentals.get("source") or "financial_data",
                computed_at,
                status="available" if fundamentals.get("pe_ratio") is not None else "unavailable",
            ),
            "pb_ratio": make_field(
                "pb_ratio",
                fundamentals.get("pb_ratio"),
                fundamentals.get("pb_ratio"),
                "multiple",
                "spot",
                "reported",
                fundamentals.get("source") or "financial_data",
                computed_at,
                status="available" if fundamentals.get("pb_ratio") is not None else "unavailable",
            ),
            "market_cap": make_field(
                "market_cap",
                fundamentals.get("market_cap"),
                fundamentals.get("market_cap"),
                "currency",
                "spot",
                "reported",
                fundamentals.get("source") or "financial_data",
                computed_at,
                status="available" if fundamentals.get("market_cap") is not None else "unavailable",
            ),
            "dividend_yield": make_field(
                "dividend_yield",
                fundamentals.get("dividend_yield"),
                format_ratio_as_percent(fundamentals.get("dividend_yield")),
                "ratio",
                "ttm",
                "derived",
                fundamentals.get("source") or "financial_data",
                computed_at,
                status="available" if fundamentals.get("dividend_yield") is not None else "unavailable",
            ),
            "revenue_ttm": make_field(
                "revenue_ttm",
                fundamentals.get("revenue_ttm"),
                fundamentals.get("revenue_ttm"),
                "currency",
                "ttm",
                "reported",
                fundamentals.get("source") or "financial_data",
                computed_at,
                status="available" if fundamentals.get("revenue_ttm") is not None else "unavailable",
            ),
        },
    }
    analysis = {
        "delta": item.get("delta", {}),
        "alerts": item.get("alerts", []),
        "technical": {
            "trend": technical.get("trend"),
            "ma_alignment": technical.get("ma_alignment"),
            "breakout_state": technical.get("breakout_state"),
            "volume_ratio": technical.get("volume_ratio"),
            "volume_ratio_state": technical.get("volume_ratio_state"),
        },
        "earnings_watch": {
            "next_earnings_date": earnings_watch.get("next_earnings_date"),
            "earnings_proximity_days": earnings_watch.get("earnings_proximity_days"),
        },
    }
    payload = InterfacePayload(
        entity={
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "market": item.get("market"),
        },
        facts=facts,
        analysis=analysis,
        meta=InterfaceMeta(
            as_of=computed_at,
            sources=_normalize_sources(item.get("source_chain", [])),
            data_completeness="partial" if item.get("partial") else "complete",
            limitations=[
                "US quote fields may degrade to latest available daily snapshot when realtime quote is unavailable",
                "Polling baseline is shared globally by symbol across callers",
            ],
            interface_type="mixed",
        ),
    )
    data = payload.to_dict()
    data["meta"].update(
        {
            "computed_at": computed_at,
            "source_chain": item.get("source_chain", []),
            "baseline_at": item.get("baseline_at"),
            "poll_interval_hint": "5-10m",
            "status": item.get("status"),
            "partial": item.get("partial", False),
        }
    )
    return data


def stock_analysis_contract(report: Dict[str, Any]) -> Dict[str, Any]:
    as_of = report.get("as_of")
    fundamental_context = build_fundamental_context(
        symbol=report.get("symbol", ""),
        financial_data={"raw_data": report.get("fundamental", {}).get("raw_data", {})},
        latest_price=report.get("price"),
        as_of=as_of,
    )
    facts = {
        "market_snapshot": {
            "price": make_field(
                "price",
                report.get("price"),
                report.get("price"),
                "currency",
                "spot",
                "reported",
                "market_data",
                as_of,
            ),
        },
        "fundamentals": fundamental_context,
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
            sources=_normalize_sources(
                report.get("technical", {}).get("data_source", ""),
                report.get("qlib", {}).get("data_source", ""),
                fundamental_context.get("source_chain", []),
            ),
            data_completeness="partial",
            limitations=["Derived technical signals are not reported facts"],
            interface_type="mixed",
        ),
    )
    return payload.to_dict()


def earnings_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    as_of = result.get("as_of")
    summary = result.get("earnings_summary", {})
    fundamental_context = (
        result.get("fundamental_context", {})
        if isinstance(result.get("fundamental_context"), dict)
        else {}
    )
    detail_fields = extract_fundamental_detail_fields(
        context_snapshot=None,
        fallback_fundamental_payload=fundamental_context,
    )
    dividend_metrics = detail_fields.get("dividend_metrics") or {}
    facts = {
        "quarterly": {
            "revenue": make_field("revenue", _parse_number(summary.get("revenue", {}).get("actual")), summary.get("revenue", {}).get("actual"), "currency", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
            "net_income": make_field("net_income", _parse_number(summary.get("net_income", {}).get("actual")), summary.get("net_income", {}).get("actual"), "currency", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
            "ebitda": make_field("ebitda", _parse_number(summary.get("ebitda", {}).get("actual")), summary.get("ebitda", {}).get("actual"), "currency", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
            "eps": make_field("eps", _parse_number(summary.get("earnings_per_share", {}).get("eps")), summary.get("earnings_per_share", {}).get("eps"), "currency_per_share", "quarterly", "reported", "yfinance.quarterly_income_stmt", as_of),
        },
        "consensus_comparison": result.get("beat_miss_analysis"),
        "fundamentals": fundamental_context,
    }
    if result.get("beat_miss_analysis", {}).get("status") == "unavailable":
        facts["consensus_comparison"]["status"] = "unavailable"
    analysis = {
        "research_strategy": build_earnings_research_strategy(result),
        "estimated_segments": result.get("segment_performance", []),
        "guidance_interpretation": result.get("guidance", {}),
        "key_metrics": {
            **result.get("key_metrics", {}),
            "dividend_metrics": dividend_metrics,
        },
        "trends": result.get("trends", {}),
    }
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts=facts,
        analysis=analysis,
        meta=InterfaceMeta(
            as_of=as_of,
            sources=_normalize_sources(result.get("sources", []), fundamental_context.get("source_chain", [])),
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


def _standard_company_profile(raw_profile: Dict[str, Any], as_of: Optional[str]) -> Dict[str, Any]:
    return {
        "symbol": raw_profile.get("symbol"),
        "name": raw_profile.get("name"),
        "sector": raw_profile.get("sector"),
        "industry": raw_profile.get("industry"),
        "overview": {
            "current_price": make_field("current_price", raw_profile["overview"].get("current_price"), raw_profile["overview"].get("current_price"), "currency", "spot", "reported", "yfinance.info", as_of),
            "total_mv": make_field("total_mv", raw_profile["overview"].get("total_mv"), raw_profile["overview"].get("total_mv"), "currency", "spot", "reported", "yfinance.info", as_of),
            "revenue": make_field("revenue", raw_profile["overview"].get("revenue"), raw_profile["overview"].get("revenue"), "currency", "ttm", "reported", "yfinance.info", as_of),
            "revenue_yoy": make_field("revenue_yoy", raw_profile["overview"].get("revenue_yoy"), raw_profile["overview"].get("revenue_yoy"), "ratio", "ttm", "reported", "yfinance.info", as_of),
        },
        "financials": {
            "gross_margin": make_field("gross_margin", raw_profile["financials"].get("gross_margin"), raw_profile["financials"].get("gross_margin"), "ratio", "ttm", "reported", "yfinance.info", as_of),
            "ebitda_margin": make_field("ebitda_margin", raw_profile["financials"].get("ebitda_margin"), raw_profile["financials"].get("ebitda_margin"), "ratio", "ttm", "reported", "yfinance.info", as_of),
            "operating_margin": make_field("operating_margin", raw_profile["financials"].get("operating_margin"), raw_profile["financials"].get("operating_margin"), "ratio", "ttm", "reported", "yfinance.info", as_of),
            "net_margin": make_field("net_margin", raw_profile["financials"].get("net_margin"), raw_profile["financials"].get("net_margin"), "ratio", "ttm", "reported", "yfinance.info", as_of),
        },
        "valuation": {
            "pe_ratio": make_field("pe_ratio", raw_profile["valuation"].get("pe_ratio"), raw_profile["valuation"].get("pe_ratio"), "number", "spot", "reported", "yfinance.info", as_of),
            "forward_pe": make_field("forward_pe", raw_profile["valuation"].get("forward_pe"), raw_profile["valuation"].get("forward_pe"), "number", "forward", "reported", "yfinance.info", as_of),
            "peg_ratio": make_field("peg_ratio", raw_profile["valuation"].get("peg_ratio"), raw_profile["valuation"].get("peg_ratio"), "number", "forward", "reported", "yfinance.info", as_of),
            "pb_ratio": make_field("pb_ratio", raw_profile["valuation"].get("pb_ratio"), raw_profile["valuation"].get("pb_ratio"), "number", "spot", "reported", "yfinance.info", as_of),
            "price_to_sales": make_field("price_to_sales", raw_profile["valuation"].get("price_to_sales"), raw_profile["valuation"].get("price_to_sales"), "number", "ttm", "reported", "yfinance.info", as_of),
        },
        "analyst_consensus": {
            "rating": raw_profile["analyst_consensus"].get("rating"),
            "target_mean_price": make_field("target_mean_price", raw_profile["analyst_consensus"].get("target_mean_price"), raw_profile["analyst_consensus"].get("target_mean_price"), "currency", "forward", "consensus", "yfinance.info", as_of),
            "analyst_count": raw_profile["analyst_consensus"].get("analyst_count"),
        },
    }


def competitive_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    as_of = None
    target_metrics = result.get("target_metrics", {}) if isinstance(result.get("target_metrics"), dict) else {}
    fundamental_context = (
        result.get("fundamental_context", {})
        if isinstance(result.get("fundamental_context"), dict)
        else {}
    )
    peers = []
    for item in result.get("comparative", {}).get("comparison_table", []):
        peers.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "total_mv": make_field("total_mv", item.get("market_cap", 0) * 1e9, item.get("market_cap"), "currency", "spot", "reported", "yfinance.info", as_of),
                "revenue": make_field("revenue", item.get("revenue", 0) * 1e9, item.get("revenue"), "currency", "ttm", "reported", "yfinance.info", as_of),
                "revenue_yoy": make_field("revenue_yoy", (item.get("growth", 0) / 100.0), item.get("growth"), "ratio", "ttm", "reported", "yfinance.info", as_of),
            }
        )
    company_profile = result.get("target_profile", {})
    if target_metrics or fundamental_context:
        raw_profile = extract_company_profile_fields(
            context_snapshot=None,
            fallback_fundamental_payload=fundamental_context,
            extra_metrics=target_metrics,
            symbol=result.get("symbol"),
            company_name=result.get("company_name"),
        )
        company_profile = _standard_company_profile(raw_profile, as_of)
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts={
            "fundamentals": fundamental_context,
            "company_profile": company_profile,
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
            sources=_normalize_sources(
                "yfinance.info",
                fundamental_context.get("source_chain", []),
                result.get("market_context", {}).get("methodology"),
                result.get("market_context", {}).get("estimated_market_context", {}).get("methodology"),
            ),
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
    fundamental_context = (
        result.get("fundamental_context", {})
        if isinstance(result.get("fundamental_context"), dict)
        else {}
    )
    detail_fields = extract_fundamental_detail_fields(
        context_snapshot=None,
        fallback_fundamental_payload=fundamental_context,
    )
    valuation_metrics = detail_fields.get("valuation_metrics") or {}
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name"), "currency": result.get("currency")},
        facts={
            "fundamentals": fundamental_context,
            "inputs": {
                "current_price": make_field("current_price", valuation_metrics.get("price", result.get("current_price")), valuation_metrics.get("price", result.get("current_price")), "currency", "spot", "reported", "yfinance.info", as_of),
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
            sources=_normalize_sources(
                result.get("fcf_source", ""),
                result.get("assumptions_source", ""),
                fundamental_context.get("source_chain", []),
            ),
            data_completeness=result.get("data_completeness", "partial"),
            limitations=["DCF output is a model estimate, not a reported market fact"],
            interface_type="model",
        ),
    )
    return payload.to_dict()


def comps_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    fundamental_context = (
        result.get("fundamental_context", {})
        if isinstance(result.get("fundamental_context"), dict)
        else {}
    )
    detail_fields = extract_fundamental_detail_fields(
        context_snapshot=None,
        fallback_fundamental_payload=fundamental_context,
    )
    raw_profile = extract_company_profile_fields(
        context_snapshot=None,
        fallback_fundamental_payload=fundamental_context,
        extra_metrics={
            "sector": result.get("sector"),
            "industry": result.get("industry"),
        },
        symbol=result.get("target_symbol"),
        company_name=result.get("target_name"),
    )
    payload = InterfacePayload(
        entity={"symbol": result.get("target_symbol"), "name": result.get("target_name"), "sector": result.get("sector"), "industry": result.get("industry")},
        facts={
            "fundamentals": fundamental_context,
            "target": {
                "symbol": result.get("target_symbol"),
                "name": result.get("target_name"),
                "company_profile": _standard_company_profile(raw_profile, None),
                "financial_report": detail_fields.get("financial_report"),
                "valuation_metrics": detail_fields.get("valuation_metrics"),
                "growth_metrics": detail_fields.get("growth_metrics"),
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
            sources=_normalize_sources("yfinance.info", fundamental_context.get("source_chain", [])),
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
    fundamental_context = (
        result.get("fundamental_context", {})
        if isinstance(result.get("fundamental_context"), dict)
        else {}
    )
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts={
            "fundamentals": fundamental_context,
            "baseline": {
                "purchase_price": result.get("purchase_price"),
                "current_price": result.get("current_price"),
            },
        },
        analysis={"outputs": result},
        meta=InterfaceMeta(
            as_of=None,
            sources=_normalize_sources(
                result.get("assumptions_source", ""),
                fundamental_context.get("source_chain", []),
            ),
            data_completeness="partial",
            limitations=["LBO output is scenario modeling based on assumptions"],
            interface_type="model",
        ),
    )
    return payload.to_dict()


def three_statement_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    fundamental_context = (
        result.get("fundamental_context", {})
        if isinstance(result.get("fundamental_context"), dict)
        else {}
    )
    payload = InterfacePayload(
        entity={"symbol": result.get("symbol"), "name": result.get("company_name")},
        facts={
            "fundamentals": fundamental_context,
            "baseline": {
                "historical_source": result.get("historical_source"),
                "as_of": result.get("as_of"),
            },
        },
        analysis={"outputs": result},
        meta=InterfaceMeta(
            as_of=result.get("as_of"),
            sources=_normalize_sources(
                result.get("historical_source", ""),
                fundamental_context.get("source_chain", []),
            ),
            data_completeness="partial",
            limitations=result.get("limitations", []),
            interface_type="model",
        ),
    )
    return payload.to_dict()
