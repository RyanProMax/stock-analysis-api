from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _format_ratio_summary(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"{value * 100:.2f}%"


def _build_growth_summary(revenue_yoy: Optional[float], net_profit_yoy: Optional[float]) -> str:
    parts = []
    if revenue_yoy is not None:
        parts.append(f"revenue_yoy={_format_ratio_summary(revenue_yoy)}")
    if net_profit_yoy is not None:
        parts.append(f"net_profit_yoy={_format_ratio_summary(net_profit_yoy)}")
    return ", ".join(parts)


def _market_tag(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    return "us" if any(ch.isalpha() for ch in text) else "cn"


def _source_item(provider: str, result: str, duration_ms: int = 0) -> Dict[str, Any]:
    return {"provider": provider, "result": result, "duration_ms": duration_ms}


def parse_json_field(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
    return value


def _non_empty_dict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return value if value else None


def _block_data(fundamental_ctx: Optional[Dict[str, Any]], block_name: str) -> Optional[Dict[str, Any]]:
    if not isinstance(fundamental_ctx, dict):
        return None
    block = fundamental_ctx.get(block_name)
    if not isinstance(block, dict):
        return None
    return _non_empty_dict(block.get("data"))


def build_fundamental_block(
    status: str,
    payload: Optional[Dict[str, Any]] = None,
    source_chain: Optional[List[Dict[str, Any]]] = None,
    errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "coverage": {"status": status},
        "source_chain": source_chain or [],
        "errors": errors or [],
        "data": payload or {},
    }


def _has_meaningful_payload(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, str):
        return payload.strip().lower() not in {"", "-", "nan", "none", "null", "n/a", "na"}
    if isinstance(payload, dict):
        return any(_has_meaningful_payload(v) for v in payload.values())
    if isinstance(payload, (list, tuple, set)):
        return any(_has_meaningful_payload(v) for v in payload)
    return True


def infer_block_status(payload: Any, fallback_status: str) -> str:
    if _has_meaningful_payload(payload):
        return "ok"
    if fallback_status in ("failed", "partial", "not_supported"):
        return fallback_status
    return "partial"


def build_market_not_supported_context(market: str, reason: str) -> Dict[str, Any]:
    chain = [_source_item("fundamental_pipeline", "not_supported")]
    blocks = {
        block: build_fundamental_block("not_supported", {}, chain, [reason])
        for block in (
            "valuation",
            "growth",
            "earnings",
            "institution",
            "capital_flow",
            "dragon_tiger",
            "boards",
        )
    }
    return {
        "market": market,
        "status": "not_supported",
        "coverage": {block: blocks[block]["status"] for block in blocks},
        "source_chain": chain,
        "errors": [reason],
        **blocks,
    }


def build_us_fundamental_context_from_info(
    symbol: str,
    info: Dict[str, Any],
    latest_price: Optional[float],
    as_of: Optional[str],
    normalized_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return build_fundamental_context(
        symbol=symbol,
        financial_data={
            "raw_data": {
                "info": info or {},
                "normalized_fields": normalized_fields or {},
            }
        },
        latest_price=latest_price,
        as_of=as_of,
    )


def extract_fundamental_context(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
) -> Optional[Dict[str, Any]]:
    snapshot_obj = parse_json_field(context_snapshot)
    if isinstance(snapshot_obj, dict):
        enhanced = snapshot_obj.get("enhanced_context")
        if isinstance(enhanced, dict):
            fundamental = enhanced.get("fundamental_context")
            if isinstance(fundamental, dict):
                return fundamental

    fallback_obj = parse_json_field(fallback_fundamental_payload)
    if isinstance(fallback_obj, dict):
        return fallback_obj
    return None


def extract_fundamental_detail_fields(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    fundamental_ctx = extract_fundamental_context(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    if not isinstance(fundamental_ctx, dict):
        return {"financial_report": None, "dividend_metrics": None}

    earnings_data = _block_data(fundamental_ctx, "earnings")
    valuation_data = _block_data(fundamental_ctx, "valuation")
    growth_data = _block_data(fundamental_ctx, "growth")
    institution_data = _block_data(fundamental_ctx, "institution")
    if not isinstance(earnings_data, dict):
        return {
            "financial_report": None,
            "dividend_metrics": None,
            "valuation_metrics": valuation_data,
            "growth_metrics": growth_data,
            "institution_metrics": institution_data,
        }

    return {
        "financial_report": _non_empty_dict(earnings_data.get("financial_report")),
        "dividend_metrics": _non_empty_dict(earnings_data.get("dividend")),
        "valuation_metrics": valuation_data,
        "growth_metrics": growth_data,
        "institution_metrics": institution_data,
    }


def extract_company_profile_fields(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
    extra_metrics: Optional[Dict[str, Any]] = None,
    symbol: Optional[str] = None,
    company_name: Optional[str] = None,
) -> Dict[str, Any]:
    extra_metrics = extra_metrics or {}
    details = extract_fundamental_detail_fields(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    valuation = details.get("valuation_metrics") or {}
    growth = details.get("growth_metrics") or {}

    return {
        "symbol": symbol,
        "name": company_name,
        "sector": extra_metrics.get("sector"),
        "industry": extra_metrics.get("industry"),
        "overview": {
            "current_price": valuation.get("price"),
            "total_mv": valuation.get("total_mv"),
            "revenue": (details.get("financial_report") or {}).get("revenue"),
            "revenue_yoy": growth.get("revenue_yoy"),
        },
        "financials": {
            "gross_margin": growth.get("gross_margin"),
            "ebitda_margin": extra_metrics.get("ebitdaMargins"),
            "operating_margin": extra_metrics.get("operatingMargins"),
            "net_margin": extra_metrics.get("profitMargins"),
        },
        "valuation": {
            "pe_ratio": valuation.get("pe_ratio"),
            "forward_pe": extra_metrics.get("forwardPE"),
            "peg_ratio": extra_metrics.get("pegRatio"),
            "pb_ratio": valuation.get("pb_ratio"),
            "price_to_sales": (valuation.get("extensions") or {}).get("price_to_sales"),
        },
        "analyst_consensus": {
            "rating": extra_metrics.get("recommendationKey"),
            "target_mean_price": extra_metrics.get("targetMeanPrice"),
            "analyst_count": extra_metrics.get("numberOfAnalystOpinions"),
        },
    }


def build_fundamental_context(
    symbol: str,
    financial_data: Optional[Dict[str, Any]],
    latest_price: Optional[float],
    as_of: Optional[str],
) -> Dict[str, Any]:
    market = _market_tag(symbol)
    if not isinstance(financial_data, dict):
        return build_market_not_supported_context(market, "financial data unavailable")

    raw_data = financial_data.get("raw_data", {}) if isinstance(financial_data.get("raw_data"), dict) else {}
    normalized_fields = raw_data.get("normalized_fields", {}) if isinstance(raw_data.get("normalized_fields"), dict) else {}
    info = raw_data.get("info", {}) if isinstance(raw_data.get("info"), dict) else {}

    valuation_payload = {}
    growth_payload = {}
    earnings_payload = {}
    institution_payload = {}
    valuation_source = [_source_item("yfinance.info" if market == "us" else "financial_provider", "ok")]
    growth_source = [_source_item("yfinance.info" if market == "us" else "financial_provider", "ok")]
    earnings_source = [_source_item("yfinance.info" if market == "us" else "financial_provider", "ok")]
    institution_source = [_source_item("yfinance.info" if market == "us" else "financial_provider", "ok")]

    if market == "us":
        dividend_payload = normalized_fields.get("dividend_metrics", {})
        earnings_source = [
            _source_item("yfinance.info", "ok"),
            _source_item(
                "yfinance.dividends" if dividend_payload else "yfinance.dividends",
                "ok" if dividend_payload else "partial",
            ),
        ]
        valuation_payload = {
            "price": latest_price,
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "total_mv": info.get("marketCap"),
            "circ_mv": None,
            "extensions": {
                "enterprise_value": info.get("enterpriseValue"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
            },
        }
        growth_payload = {
            "revenue_yoy": info.get("revenueGrowth"),
            "net_profit_yoy": info.get("earningsGrowth"),
            "roe": info.get("returnOnEquity"),
            "gross_margin": info.get("grossMargins"),
            "summary": _build_growth_summary(info.get("revenueGrowth"), info.get("earningsGrowth")),
        }
        insider_ratio = (
            normalized_fields.get("held_percent_insiders", {}).get("value")
            if isinstance(normalized_fields.get("held_percent_insiders"), dict)
            else None
        )
        institution_ratio = (
            normalized_fields.get("held_percent_institutions", {}).get("value")
            if isinstance(normalized_fields.get("held_percent_institutions"), dict)
            else None
        )
        short_interest_ratio = (
            normalized_fields.get("shares_percent_shares_out", {}).get("value")
            if isinstance(normalized_fields.get("shares_percent_shares_out"), dict)
            else None
        )
        earnings_payload = {
            "financial_report": {
                "report_date": as_of,
                "revenue": info.get("totalRevenue"),
                "net_profit_parent": info.get("netIncomeToCommon"),
                "operating_cash_flow": info.get("operatingCashflow"),
                "roe": info.get("returnOnEquity"),
            },
            "dividend": dividend_payload if isinstance(dividend_payload, dict) else {},
            "forecast_summary": "",
            "quick_report_summary": "",
        }
        institution_payload = {
            "insider_holding_ratio": insider_ratio,
            "institution_holding_ratio": institution_ratio,
            "short_interest_ratio": short_interest_ratio,
            "institution_holding_change": None,
            "top10_holder_change": None,
            "summary": ", ".join(
                part
                for part in (
                    (
                        f"insiders={_format_ratio_summary(insider_ratio)}"
                        if insider_ratio is not None
                        else None
                    ),
                    (
                        f"institutions={_format_ratio_summary(institution_ratio)}"
                        if institution_ratio is not None
                        else None
                    ),
                    (
                        f"short_interest={_format_ratio_summary(short_interest_ratio)}"
                        if short_interest_ratio is not None
                        else None
                    ),
                )
                if part
            ),
        }
    else:
        growth_source = [_source_item("tushare.income", "ok")]
        earnings_source = [_source_item("tushare.income", "ok")]
        institution_source = [_source_item("financial_provider", "partial")]
        valuation_payload = {
            "pe_ratio": financial_data.get("pe_ratio"),
            "pb_ratio": financial_data.get("pb_ratio"),
            "price": latest_price,
        }
        growth_payload = {
            "revenue_yoy": financial_data.get("revenue_growth"),
            "roe": financial_data.get("roe"),
            "debt_to_assets": financial_data.get("debt_ratio"),
            "summary": _build_growth_summary(financial_data.get("revenue_growth"), None),
        }
        income_meta = raw_data.get("income_meta", {}) if isinstance(raw_data.get("income_meta"), dict) else {}
        institution_payload = {}
        earnings_payload = {
            "financial_report": {
                "report_date": income_meta.get("latest_end_date"),
                "announcement_date": income_meta.get("latest_ann_date"),
                "revenue_growth_ratio": income_meta.get("revenue_growth_ratio"),
                "roe": (
                    raw_data.get("fina_indicator_meta", {}).get("roe_ratio")
                    if isinstance(raw_data.get("fina_indicator_meta"), dict)
                    else None
                ),
            },
            "dividend": {},
            "forecast_summary": "",
            "quick_report_summary": "",
        }
        institution_payload = {
            "institution_holding_change": None,
            "top10_holder_change": None,
            "summary": "",
        }

    unsupported_chain = [_source_item("fundamental_pipeline", "not_supported")]
    blocks = {
        "valuation": build_fundamental_block(
            infer_block_status(valuation_payload, "partial"),
            valuation_payload,
            valuation_source,
            [],
        ),
        "growth": build_fundamental_block(
            infer_block_status(growth_payload, "partial"),
            growth_payload,
            growth_source,
            [],
        ),
        "earnings": build_fundamental_block(
            infer_block_status(earnings_payload, "partial"),
            earnings_payload,
            earnings_source,
            [],
        ),
        "institution": build_fundamental_block(
            infer_block_status(institution_payload, "partial"),
            institution_payload,
            institution_source,
            [],
        ),
        "capital_flow": build_fundamental_block("not_supported", {}, unsupported_chain, ["not implemented"]),
        "dragon_tiger": build_fundamental_block("not_supported", {}, unsupported_chain, ["not implemented"]),
        "boards": build_fundamental_block("not_supported", {}, unsupported_chain, ["not implemented"]),
    }

    coverage = {name: block["status"] for name, block in blocks.items()}
    all_sources: List[Dict[str, Any]] = []
    all_errors: List[str] = []
    for block in blocks.values():
        all_sources.extend(block.get("source_chain", []))
        all_errors.extend(block.get("errors", []))

    if all(value == "not_supported" for value in coverage.values()):
        status = "not_supported"
    elif "failed" in coverage.values() or "partial" in coverage.values():
        status = "partial"
    else:
        status = "ok"

    return {
        "market": market,
        "status": status,
        "coverage": coverage,
        "source_chain": all_sources,
        "errors": all_errors,
        **blocks,
    }
