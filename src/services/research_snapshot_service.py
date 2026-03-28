from __future__ import annotations

from collections import Counter
import copy
from datetime import datetime, timezone
import json
from typing import Any, Dict, Mapping, Optional, Sequence

import pandas as pd

from ..analyzer.competitive_analyzer import CompetitiveAnalyzer
from ..analyzer.comps_analyzer import CompsAnalyzer
from ..analyzer.dcf_model import DCFModel
from ..analyzer.earnings_analyzer import EarningsAnalyzer
from ..analyzer.lbo_model import LBOModel
from ..analyzer.normalizers import (
    comps_contract,
    dcf_contract,
    lbo_contract,
    three_statement_contract,
)
from ..analyzer.three_statement_model import ThreeStatementModel
from ..data_provider.fundamental_context import build_fundamental_context
from ..data_provider.manager import data_manager
from ..data_provider.sources.yfinance import YfinanceDataSource
from ..data_provider.sources.tushare import TushareDataSource
from ..model.contracts import InterfaceMeta, InterfacePayload


class ResearchSnapshotService:
    STRATEGY = "fsp_objective_research_snapshot_v1"
    TOP_LEVEL_SOURCE = "research_snapshot_dispatcher"
    PROVIDER_ORDER = ("tushare",)
    CN_NATIVE_CORE_BLOCKS = ("research_report", "report_rc")
    CN_NATIVE_OPTIONAL_BLOCKS = ("anns_d", "news", "major_news")
    NEWS_SOURCES = ("cls", "sina", "wallstreetcn", "10jqka")
    MAJOR_NEWS_SOURCES = ("新浪财经", "财联社", "中证网", "第一财经")
    DEFAULT_MODULES = {
        "cn": ("research_report", "report_rc", "anns_d", "news", "major_news", "earnings"),
        "us": ("earnings", "earnings_preview", "dcf", "comps", "three_statement"),
    }
    CRITICAL_MODULES = {
        "cn": ("research_report", "report_rc"),
        "us": ("earnings", "dcf", "comps", "three_statement"),
    }
    OPTIONAL_MODULES = (
        "lbo",
        "three_statement_scenarios",
        "competitive",
        "catalysts",
        "model_update",
        "sector_overview",
        "screen",
    )
    RAW_MODULES = ("research_report", "report_rc", "anns_d", "news", "major_news")
    STRUCTURED_MODULES = (
        "earnings",
        "earnings_preview",
        "dcf",
        "comps",
        "three_statement",
        "lbo",
        "three_statement_scenarios",
        "competitive",
        "catalysts",
        "model_update",
        "sector_overview",
        "screen",
    )
    MODULES = (
        "research_report",
        "report_rc",
        "anns_d",
        "news",
        "major_news",
        "earnings",
        "earnings_preview",
        "dcf",
        "comps",
        "three_statement",
        "lbo",
        "three_statement_scenarios",
        "competitive",
        "catalysts",
        "model_update",
        "sector_overview",
        "screen",
    )
    US_ONLY_MODULES = {
        "dcf",
        "comps",
        "three_statement",
        "lbo",
        "three_statement_scenarios",
        "competitive",
        "earnings_preview",
        "sector_overview",
    }
    OBJECTIVE_FORBIDDEN_KEYS = {
        "recommendation",
        "confidence",
        "price_target",
        "moat_assessment",
        "thesis",
        "conviction",
    }

    def __init__(self, providers: Optional[Mapping[str, Any]] = None):
        self.providers = dict(providers or {"tushare": TushareDataSource})

    def poll_snapshot(
        self,
        *,
        market: str,
        symbols: Sequence[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        modules: Optional[Sequence[str]] = None,
        module_options: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_market = self._normalize_market(market)
        normalized_symbols = self._normalize_symbols(symbols)
        computed_at = datetime.now(timezone.utc).isoformat()
        window = self._resolve_window(start_date=start_date, end_date=end_date)
        resolved_modules = self._resolve_modules(normalized_market, modules)
        normalized_module_options = self._normalize_module_options(module_options)
        items = [
            self._build_item(
                market=normalized_market,
                requested_symbol=symbol,
                modules=resolved_modules,
                module_options=normalized_module_options,
                start_date=window["start_date"],
                end_date=window["end_date"],
                news_start=window["news_start"],
                news_end=window["news_end"],
                change_anchor=window["change_anchor"],
            )
            for symbol in normalized_symbols
        ]
        overall_status = self._merge_item_statuses(items)

        return {
            "status": overall_status,
            "computed_at": computed_at,
            "source": self.TOP_LEVEL_SOURCE,
            "market": normalized_market,
            "strategy": self.STRATEGY,
            "request": {
                "market": normalized_market,
                "symbols": normalized_symbols,
                "start_date": window["start_date"],
                "end_date": window["end_date"],
                "modules": list(resolved_modules),
                "module_options": normalized_module_options,
            },
            "items": items,
        }

    def _build_cn_native_item(
        self,
        *,
        requested_symbol: str,
        start_date: str,
        end_date: str,
        news_start: str,
        news_end: str,
        change_anchor: pd.Timestamp,
    ) -> Dict[str, Any]:
        attempted_sources = list(self.PROVIDER_ORDER)
        if len(requested_symbol) != 6 or not requested_symbol.isdigit():
            return self._build_failed_item(
                requested_symbol=requested_symbol,
                code="invalid_symbol",
                message="CN research snapshot expects a 6-digit stock code.",
                attempted_sources=attempted_sources,
            )

        security = self._dispatch_record(
            "fetch_security_info",
            market="cn",
            symbol=requested_symbol,
        )
        security_record = security.get("record")
        if security.get("status") in {"permission_denied", "error"}:
            return self._build_failed_item(
                requested_symbol=requested_symbol,
                code="security_lookup_failed",
                message=security.get("error") or "Security lookup failed.",
                attempted_sources=attempted_sources,
            )
        if not security_record:
            return self._build_failed_item(
                requested_symbol=requested_symbol,
                code="invalid_symbol",
                message="Unable to resolve the requested CN symbol from Tushare.",
                attempted_sources=attempted_sources,
            )

        info = self._build_identity(security_record)
        if security_record.get("security_type") != "stock":
            return self._build_not_supported_item(
                requested_symbol=requested_symbol,
                info=info,
                attempted_sources=attempted_sources,
            )

        ts_code = str(security_record.get("ts_code") or "").strip().upper()
        report_rc_requested = self._dispatch_block(
            "fetch_report_rc",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        report_rc_requested_items = self._sort_and_dedupe_rows(
            report_rc_requested["records"],
            order=(
                ("report_date", False),
                ("quarter", False),
                ("org_name", True),
                ("report_title", True),
            ),
        )
        has_requested_stock_specific_report_rc = self._has_stock_specific_report_rc_rows(
            report_rc_requested_items
        )
        report_rc = self._resolve_report_rc_block(
            requested_block=report_rc_requested,
            ts_code=ts_code,
            requested_start_date=start_date,
            requested_end_date=end_date,
        )
        report_rc_items = self._sort_and_dedupe_rows(
            report_rc["records"],
            order=(
                ("report_date", False),
                ("quarter", False),
                ("org_name", True),
                ("report_title", True),
            ),
        )
        report_rc["records"] = report_rc_items

        if has_requested_stock_specific_report_rc:
            research_report = self._dispatch_block(
                "fetch_research_report",
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            research_report = self._empty_block(
                attempted_sources=attempted_sources,
                source_status="empty",
                source_error=None,
                extra={
                    "skip_reason": "no_stock_specific_report_rc_in_requested_window",
                    "requested_start_date": start_date,
                    "requested_end_date": end_date,
                },
            )
        anns_d = self._dispatch_block(
            "fetch_anns_d",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        news = self._collect_news_block(
            method_name="fetch_news",
            sources=self.NEWS_SOURCES,
            symbol=requested_symbol,
            ts_code=ts_code,
            name=str(security_record.get("name") or ""),
            start_date=news_start,
            end_date=news_end,
        )
        major_news = self._collect_news_block(
            method_name="fetch_major_news",
            sources=self.MAJOR_NEWS_SOURCES,
            symbol=requested_symbol,
            ts_code=ts_code,
            name=str(security_record.get("name") or ""),
            start_date=news_start,
            end_date=news_end,
        )

        research_items = self._sort_and_dedupe_rows(
            research_report["records"],
            order=(
                ("trade_date", False),
                ("inst_csname", True),
                ("title", True),
            ),
        )
        anns_d_items = self._sort_and_dedupe_rows(
            anns_d["records"],
            order=(
                ("ann_date", False),
                ("rec_time", False),
                ("title", True),
            ),
        )
        news_items = self._sort_and_dedupe_rows(
            news["records"],
            order=(("datetime", False), ("pub_time", False), ("src", True)),
        )
        major_news_items = self._sort_and_dedupe_rows(
            major_news["records"],
            order=(("pub_time", False), ("datetime", False), ("src", True)),
        )

        research_report["records"] = research_items
        report_rc["records"] = report_rc_items
        anns_d["records"] = anns_d_items
        news["records"] = news_items
        major_news["records"] = major_news_items

        core_statuses = [
            research_report["source_status"],
            report_rc["source_status"],
        ]
        optional_statuses = [
            anns_d["source_status"],
            news["source_status"],
            major_news["source_status"],
        ]

        if any(
            status in {"permission_denied", "error", "not_supported"} for status in core_statuses
        ):
            item_status = "failed"
            error = {
                "code": "core_source_unavailable",
                "message": "Core research blocks are unavailable from the current source chain.",
            }
        elif any(
            status in {"permission_denied", "error", "not_supported"}
            for status in optional_statuses
        ):
            item_status = "partial"
            error = None
        else:
            item_status = "ok"
            error = None

        return {
            "requested_symbol": requested_symbol,
            "status": item_status,
            "error": error,
            "info": info,
            "research_report": research_report,
            "report_rc": report_rc,
            "anns_d": anns_d,
            "news": news,
            "major_news": major_news,
            "derived": self._build_derived(
                research_report=research_items,
                report_rc=report_rc_items,
                anns_d=anns_d_items,
                news=news_items,
                major_news=major_news_items,
                change_anchor=change_anchor,
            ),
        }

    def _build_item(
        self,
        *,
        market: str,
        requested_symbol: str,
        modules: Sequence[str],
        module_options: Mapping[str, Any],
        start_date: str,
        end_date: str,
        news_start: str,
        news_end: str,
        change_anchor: pd.Timestamp,
    ) -> Dict[str, Any]:
        if market == "cn":
            return self._build_cn_item(
                requested_symbol=requested_symbol,
                modules=modules,
                module_options=module_options,
                start_date=start_date,
                end_date=end_date,
                news_start=news_start,
                news_end=news_end,
                change_anchor=change_anchor,
            )
        return self._build_us_item(
            requested_symbol=requested_symbol,
            modules=modules,
            module_options=module_options,
            start_date=start_date,
            end_date=end_date,
            news_start=news_start,
            news_end=news_end,
            change_anchor=change_anchor,
        )

    def _build_cn_item(
        self,
        *,
        requested_symbol: str,
        modules: Sequence[str],
        module_options: Mapping[str, Any],
        start_date: str,
        end_date: str,
        news_start: str,
        news_end: str,
        change_anchor: pd.Timestamp,
    ) -> Dict[str, Any]:
        attempted_sources = list(self.PROVIDER_ORDER)
        if len(requested_symbol) != 6 or not requested_symbol.isdigit():
            return self._build_dynamic_item_failure(
                requested_symbol=requested_symbol,
                status="failed",
                code="invalid_symbol",
                message="CN research snapshot expects a 6-digit stock code.",
                modules=modules,
                attempted_sources=attempted_sources,
            )

        security = self._dispatch_record(
            "fetch_security_info", market="cn", symbol=requested_symbol
        )
        security_record = security.get("record")
        if security.get("status") in {"permission_denied", "error"}:
            return self._build_dynamic_item_failure(
                requested_symbol=requested_symbol,
                status="failed",
                code="security_lookup_failed",
                message=security.get("error") or "Security lookup failed.",
                modules=modules,
                attempted_sources=attempted_sources,
            )
        if not security_record:
            return self._build_dynamic_item_failure(
                requested_symbol=requested_symbol,
                status="failed",
                code="invalid_symbol",
                message="Unable to resolve the requested CN symbol from Tushare.",
                modules=modules,
                attempted_sources=attempted_sources,
            )

        info = self._build_identity(security_record)
        if security_record.get("security_type") != "stock":
            return self._build_dynamic_item_failure(
                requested_symbol=requested_symbol,
                status="not_supported",
                code="security_not_supported",
                message="CN research snapshot only supports listed common stock.",
                modules=modules,
                attempted_sources=attempted_sources,
                info=info,
            )

        module_cache: Dict[str, Any] = {"security_record": security_record, "info": info}
        module_results: Dict[str, Any] = {}
        native_modules_requested = any(
            module in self.RAW_MODULES or module in {"catalysts"} for module in modules
        )
        if native_modules_requested:
            module_cache["cn_native_item"] = self._build_cn_native_item(
                requested_symbol=requested_symbol,
                start_date=start_date,
                end_date=end_date,
                news_start=news_start,
                news_end=news_end,
                change_anchor=change_anchor,
            )

        for module in modules:
            module_results[module] = self._execute_module(
                market="cn",
                module=module,
                requested_symbol=requested_symbol,
                module_options=module_options,
                module_cache=module_cache,
                start_date=start_date,
                end_date=end_date,
                news_start=news_start,
                news_end=news_end,
                change_anchor=change_anchor,
            )

        native_item = module_cache.get("cn_native_item")
        if isinstance(native_item, dict):
            module_results["derived"] = native_item.get("derived", self._empty_derived())

        item_status, error = self._summarize_module_results(
            market="cn",
            modules=modules,
            module_results=module_results,
        )
        return {
            "requested_symbol": requested_symbol,
            "status": item_status,
            "error": error,
            "info": info,
            **module_results,
        }

    def _build_us_item(
        self,
        *,
        requested_symbol: str,
        modules: Sequence[str],
        module_options: Mapping[str, Any],
        start_date: str,
        end_date: str,
        news_start: str,
        news_end: str,
        change_anchor: pd.Timestamp,
    ) -> Dict[str, Any]:
        security = self._fetch_us_security_info(requested_symbol)
        info = security["info"]
        attempted_sources = security["attempted_sources"]
        if security["status"] == "error":
            return self._build_dynamic_item_failure(
                requested_symbol=requested_symbol,
                status="failed",
                code="security_lookup_failed",
                message=security["error"] or "US security lookup failed.",
                modules=modules,
                attempted_sources=attempted_sources,
                info=info,
            )
        if security["status"] == "empty":
            return self._build_dynamic_item_failure(
                requested_symbol=requested_symbol,
                status="failed",
                code="invalid_symbol",
                message="Unable to resolve the requested US symbol from yfinance.",
                modules=modules,
                attempted_sources=attempted_sources,
                info=info,
            )
        if security["status"] == "not_supported":
            return self._build_dynamic_item_failure(
                requested_symbol=requested_symbol,
                status="not_supported",
                code="security_not_supported",
                message=security["error"] or "US research snapshot only supports common stock.",
                modules=modules,
                attempted_sources=attempted_sources,
                info=info,
            )

        module_cache: Dict[str, Any] = {
            "security_record": security["record"],
            "info": info,
        }
        module_results: Dict[str, Any] = {}
        for module in modules:
            module_results[module] = self._execute_module(
                market="us",
                module=module,
                requested_symbol=requested_symbol,
                module_options=module_options,
                module_cache=module_cache,
                start_date=start_date,
                end_date=end_date,
                news_start=news_start,
                news_end=news_end,
                change_anchor=change_anchor,
            )

        item_status, error = self._summarize_module_results(
            market="us",
            modules=modules,
            module_results=module_results,
        )
        return {
            "requested_symbol": requested_symbol,
            "status": item_status,
            "error": error,
            "info": info,
            **module_results,
        }

    def _execute_module(
        self,
        *,
        market: str,
        module: str,
        requested_symbol: str,
        module_options: Mapping[str, Any],
        module_cache: Dict[str, Any],
        start_date: str,
        end_date: str,
        news_start: str,
        news_end: str,
        change_anchor: pd.Timestamp,
    ) -> Dict[str, Any]:
        if module in module_cache:
            return copy.deepcopy(module_cache[module])

        native_item = module_cache.get("cn_native_item")
        if module in self.RAW_MODULES:
            if market != "cn":
                result = self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="CN-native research block is not supported for US market.",
                    attempted_sources=["yfinance"],
                )
            else:
                result = copy.deepcopy(
                    native_item.get(
                        module,
                        self._empty_block(
                            attempted_sources=list(self.PROVIDER_ORDER),
                            source_status="empty",
                            source_error=None,
                        ),
                    )
                )
        elif module == "earnings":
            result = (
                self._build_cn_earnings_module(
                    symbol=requested_symbol,
                    info=module_cache["info"],
                )
                if market == "cn"
                else self._build_us_earnings_module(
                    symbol=requested_symbol,
                    info=module_cache["info"],
                    options=module_options.get("earnings", {}),
                )
            )
        elif module == "dcf":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="DCF is only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_dcf_module(
                    symbol=requested_symbol,
                    options=module_options.get("dcf", {}),
                )
            )
        elif module == "comps":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="Comps is only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_comps_module(
                    symbol=requested_symbol,
                    options=module_options.get("comps", {}),
                )
            )
        elif module == "lbo":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="LBO is only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_lbo_module(
                    symbol=requested_symbol,
                    options=module_options.get("lbo", {}),
                )
            )
        elif module == "three_statement":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="Three-statement is only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_three_statement_module(
                    symbol=requested_symbol,
                    options=module_options.get("three_statement", {}),
                )
            )
        elif module == "three_statement_scenarios":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="Three-statement scenarios are only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_three_statement_scenarios_module(
                    symbol=requested_symbol,
                    options=module_options.get("three_statement", {}),
                )
            )
        elif module == "competitive":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="Competitive module is only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_competitive_module(
                    symbol=requested_symbol,
                    options=module_options.get("competitive", {}),
                )
            )
        elif module == "earnings_preview":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="Earnings preview is only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_earnings_preview_module(
                    symbol=requested_symbol,
                    info_record=module_cache["security_record"],
                )
            )
        elif module == "catalysts":
            result = self._build_catalysts_module(
                market=market,
                symbol=requested_symbol,
                info_record=module_cache["security_record"],
                native_item=native_item if isinstance(native_item, dict) else None,
                options=module_options.get("catalysts", {}),
            )
        elif module == "model_update":
            result = self._build_model_update_module(
                market=market,
                symbol=requested_symbol,
                info=module_cache["info"],
                module_options=module_options,
                module_cache=module_cache,
            )
        elif module == "sector_overview":
            result = (
                self._empty_module_result(
                    module=module,
                    status="not_supported",
                    error="Sector overview is only supported for US market.",
                    attempted_sources=list(self.PROVIDER_ORDER),
                )
                if market != "us"
                else self._build_sector_overview_module(
                    symbol=requested_symbol,
                    options=module_options.get("sector_overview", {}),
                )
            )
        elif module == "screen":
            result = self._build_screen_module(
                market=market,
                symbol=requested_symbol,
                info_record=module_cache["security_record"],
                options=module_options.get("screen", {}),
            )
        else:
            result = self._empty_module_result(
                module=module,
                status="not_supported",
                error=f"Unknown module: {module}",
                attempted_sources=list(self.PROVIDER_ORDER),
            )

        module_cache[module] = copy.deepcopy(result)
        return result

    def _resolve_modules(
        self,
        market: str,
        modules: Optional[Sequence[str]],
    ) -> list[str]:
        selected = list(self.DEFAULT_MODULES[market] if not modules else modules)
        normalized: list[str] = []
        for module in selected:
            text = str(module or "").strip()
            if not text:
                continue
            if text not in self.MODULES:
                raise ValueError(f"Unknown module: {text}")
            if text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_module_options(
        module_options: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(module_options, Mapping):
            return {}
        normalized: Dict[str, Any] = {}
        for key, value in module_options.items():
            normalized[str(key)] = value if isinstance(value, Mapping) else value
        return normalized

    @staticmethod
    def _merge_item_statuses(items: Sequence[Dict[str, Any]]) -> str:
        if not items:
            return "ok"
        statuses = {str(item.get("status") or "") for item in items}
        if statuses == {"not_implemented"}:
            return "not_implemented"
        if statuses == {"ok"}:
            return "ok"
        return "partial"

    def _fetch_us_security_info(self, symbol: str) -> Dict[str, Any]:
        attempted_sources = ["yfinance"]
        financial_data, raw_data = YfinanceDataSource.get_us_financial_data(symbol)
        info = raw_data.get("info") if isinstance(raw_data, dict) else None
        if not isinstance(info, dict) or not info:
            return {
                "record": None,
                "status": "empty",
                "error": None,
                "attempted_sources": attempted_sources,
                "info": self._empty_identity(),
            }

        quote_type = str(info.get("quoteType") or "").strip().lower()
        if quote_type and quote_type not in {"equity", "stock"}:
            record = {
                "symbol": symbol,
                "name": info.get("longName") or info.get("shortName") or symbol,
                "exchange": info.get("exchange"),
                "currency": info.get("currency"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "security_type": quote_type,
                "raw_data": raw_data,
            }
            return {
                "record": record,
                "status": "not_supported",
                "error": f"US research snapshot only supports common stock, got {quote_type}.",
                "attempted_sources": attempted_sources,
                "info": self._build_identity(record),
            }

        record = {
            "symbol": symbol,
            "name": info.get("longName") or info.get("shortName") or symbol,
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "security_type": "stock",
            "raw_data": raw_data,
        }
        return {
            "record": record,
            "status": "ok",
            "error": None,
            "attempted_sources": attempted_sources,
            "info": self._build_identity(record),
        }

    def _build_dynamic_item_failure(
        self,
        *,
        requested_symbol: str,
        status: str,
        code: str,
        message: str,
        modules: Sequence[str],
        attempted_sources: Sequence[str],
        info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        item = {
            "requested_symbol": requested_symbol,
            "status": status,
            "error": {"code": code, "message": message},
            "info": info or self._empty_identity(),
        }
        for module in modules:
            item[module] = self._empty_module_result(
                module=module,
                status="error" if status == "failed" else status,
                error=message,
                attempted_sources=attempted_sources,
            )
        return item

    def _empty_module_result(
        self,
        *,
        module: str,
        status: str,
        error: Optional[str],
        attempted_sources: Sequence[str],
    ) -> Dict[str, Any]:
        if module in self.RAW_MODULES:
            return self._empty_block(
                attempted_sources=attempted_sources,
                source_status=status,
                source_error=error,
            )
        return self._wrap_structured_module(
            payload=self._empty_structured_payload(
                interface_type="mixed",
                limitations=[error] if error else [],
            ),
            status=status,
            error=error,
            attempted_sources=attempted_sources,
        )

    def _module_status(self, module_payload: Dict[str, Any]) -> str:
        if "source_status" in module_payload:
            return str(module_payload.get("source_status") or "ok")
        if "module_status" in module_payload:
            return str(module_payload.get("module_status") or "ok")
        return "ok"

    def _summarize_module_results(
        self,
        *,
        market: str,
        modules: Sequence[str],
        module_results: Mapping[str, Dict[str, Any]],
    ) -> tuple[str, Optional[Dict[str, str]]]:
        requested_core_modules = [
            module for module in modules if module in self.CRITICAL_MODULES[market]
        ]
        modules_for_failure = requested_core_modules or list(modules)
        statuses = {
            module: self._module_status(module_results.get(module, {})) for module in modules
        }
        if any(
            statuses.get(module) in {"permission_denied", "error"} for module in modules_for_failure
        ):
            return (
                "failed",
                {
                    "code": "core_module_unavailable",
                    "message": "One or more requested core modules are unavailable from the current source chain.",
                },
            )
        if any(
            statuses.get(module)
            in {"partial", "permission_denied", "error", "not_supported", "not_implemented"}
            for module in modules
        ):
            return "partial", None
        return "ok", None

    def _build_cn_earnings_module(
        self,
        *,
        symbol: str,
        info: Dict[str, Any],
    ) -> Dict[str, Any]:
        financial_data, source_name = data_manager.get_financial_data(symbol)
        fundamental_context = build_fundamental_context(
            symbol=symbol,
            financial_data=financial_data,
            latest_price=None,
            as_of=None,
        )
        earnings_block = (
            fundamental_context.get("earnings", {})
            if isinstance(fundamental_context.get("earnings"), dict)
            else {}
        )
        growth_block = (
            fundamental_context.get("growth", {})
            if isinstance(fundamental_context.get("growth"), dict)
            else {}
        )
        valuation_block = (
            fundamental_context.get("valuation", {})
            if isinstance(fundamental_context.get("valuation"), dict)
            else {}
        )
        payload = self._make_structured_payload(
            entity={
                "symbol": symbol,
                "name": info.get("common", {}).get("name"),
                "market": "cn",
            },
            facts={
                "reported": earnings_block.get("data", {}),
                "consensus": {},
            },
            analysis={
                "derived": {
                    "fundamentals": fundamental_context,
                    "growth": growth_block.get("data", {}),
                    "valuation": valuation_block.get("data", {}),
                    "coverage": fundamental_context.get("coverage", {}),
                }
            },
            as_of=((earnings_block.get("data", {}) or {}).get("financial_report", {}) or {}).get(
                "report_date"
            ),
            sources=[source_name or "financial_provider"],
            data_completeness=fundamental_context.get("status", "partial"),
            limitations=["CN earnings module is limited by available provider financial coverage."],
            interface_type="mixed",
        )
        return self._wrap_structured_module(
            payload=payload,
            status=fundamental_context.get("status", "partial"),
            error=None,
            attempted_sources=[source_name or "financial_provider"],
        )

    def _build_us_earnings_module(
        self,
        *,
        symbol: str,
        info: Dict[str, Any],
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        analyzer = EarningsAnalyzer()
        result = analyzer.analyze(
            symbol=symbol,
            quarter=options.get("quarter"),
            fiscal_year=options.get("fiscal_year"),
        )
        if result.error:
            return self._wrap_structured_module(
                payload=self._empty_structured_payload(
                    interface_type="mixed",
                    limitations=[result.error],
                ),
                status="error",
                error=result.error,
                attempted_sources=["yfinance"],
            )

        result_dict = result.to_dict()
        payload = self._make_structured_payload(
            entity={
                "symbol": symbol,
                "name": result_dict.get("company_name"),
                "quarter": result_dict.get("quarter"),
                "fiscal_year": result_dict.get("fiscal_year"),
            },
            facts={
                "reported": result_dict.get("earnings_summary", {}),
                "consensus": result_dict.get("beat_miss_analysis", {}),
            },
            analysis={
                "derived": {
                    "fundamental_context": result_dict.get("fundamental_context", {}),
                    "key_metrics": result_dict.get("key_metrics", {}),
                    "trends": result_dict.get("trends", {}),
                }
            },
            as_of=result_dict.get("as_of"),
            sources=["yfinance"],
            data_completeness="partial",
            limitations=[],
            interface_type="mixed",
        )
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_dcf_module(
        self,
        *,
        symbol: str,
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        model = DCFModel(
            risk_free_rate=options.get("risk_free_rate", DCFModel.DEFAULT_RISK_FREE_RATE),
            equity_risk_premium=options.get(
                "equity_risk_premium",
                DCFModel.DEFAULT_EQUITY_RISK_PREMIUM,
            ),
            terminal_growth_rate=options.get(
                "terminal_growth_rate",
                DCFModel.DEFAULT_TERMINAL_GROWTH_RATE,
            ),
        )
        result = model.analyze(symbol)
        if result.error:
            return self._wrap_structured_module(
                payload=self._empty_structured_payload(
                    interface_type="model", limitations=[result.error]
                ),
                status="error",
                error=result.error,
                attempted_sources=["yfinance"],
            )
        payload = self._sanitize_structured_payload(dcf_contract(result.to_dict()))
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_comps_module(
        self,
        *,
        symbol: str,
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        analyzer = CompsAnalyzer()
        result = analyzer.analyze(symbol, options.get("sector"))
        if result.error:
            return self._wrap_structured_module(
                payload=self._empty_structured_payload(
                    interface_type="mixed", limitations=[result.error]
                ),
                status="error",
                error=result.error,
                attempted_sources=["yfinance"],
            )
        payload = self._sanitize_structured_payload(comps_contract(result.to_dict()))
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_lbo_module(
        self,
        *,
        symbol: str,
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        leverage = options.get("leverage", 0.65)
        leverage = leverage if isinstance(leverage, (int, float)) else 0.65
        model = LBOModel(
            holding_period=options.get("holding_period", LBOModel.DEFAULT_HOLDING_PERIOD),
            entry_multiple=options.get("entry_multiple", LBOModel.DEFAULT_ENTRY_MULTIPLE),
            exit_multiple=options.get("exit_multiple", LBOModel.DEFAULT_EXIT_MULTIPLE),
            senior_debt_pct=leverage * 0.8,
            mezz_debt_pct=leverage * 0.2,
        )
        result = model.analyze(symbol)
        if result.error:
            return self._wrap_structured_module(
                payload=self._empty_structured_payload(
                    interface_type="model", limitations=[result.error]
                ),
                status="error",
                error=result.error,
                attempted_sources=["yfinance"],
            )
        payload = self._sanitize_structured_payload(lbo_contract(result.to_dict()))
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_three_statement_module(
        self,
        *,
        symbol: str,
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        model = ThreeStatementModel(
            projection_years=options.get(
                "projection_years", ThreeStatementModel.DEFAULT_PROJECTION_YEARS
            )
        )
        result = model.analyze(symbol, str(options.get("scenario") or "base"))
        if result.error:
            return self._wrap_structured_module(
                payload=self._empty_structured_payload(
                    interface_type="model", limitations=[result.error]
                ),
                status="error",
                error=result.error,
                attempted_sources=["yfinance"],
            )
        payload = self._sanitize_structured_payload(three_statement_contract(result.to_dict()))
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_three_statement_scenarios_module(
        self,
        *,
        symbol: str,
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        model = ThreeStatementModel(
            projection_years=options.get(
                "projection_years", ThreeStatementModel.DEFAULT_PROJECTION_YEARS
            )
        )
        scenarios_result: Dict[str, Any] = {}
        for scenario in ("bull", "base", "bear"):
            result = model.analyze(symbol, scenario)
            if result.error:
                return self._wrap_structured_module(
                    payload=self._empty_structured_payload(
                        interface_type="model", limitations=[result.error]
                    ),
                    status="error",
                    error=result.error,
                    attempted_sources=["yfinance"],
                )
            scenarios_result[scenario] = {
                "revenue_growth": result.revenue_growth_rate,
                "key_metrics": result.key_metrics,
                "assumptions": result.assumptions,
            }
        payload = self._sanitize_structured_payload(
            three_statement_contract(
                {
                    "symbol": symbol,
                    "company_name": symbol,
                    "historical_source": "scenario_comparison",
                    "as_of": None,
                    "limitations": ["Scenario comparison derived from model outputs"],
                    "scenarios": scenarios_result,
                }
            )
        )
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_competitive_module(
        self,
        *,
        symbol: str,
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        analyzer = CompetitiveAnalyzer()
        competitors = options.get("competitors")
        competitor_list = None
        if isinstance(competitors, Sequence) and not isinstance(competitors, (str, bytes)):
            competitor_list = [
                str(item).strip().upper() for item in competitors if str(item).strip()
            ]
        result = analyzer.analyze(
            symbol=symbol,
            competitors=competitor_list,
            industry=str(options.get("industry") or "technology"),
        )
        if result.error:
            return self._wrap_structured_module(
                payload=self._empty_structured_payload(
                    interface_type="mixed", limitations=[result.error]
                ),
                status="error",
                error=result.error,
                attempted_sources=["yfinance"],
            )

        result_dict = result.to_dict()
        comparison_table = (result_dict.get("comparative") or {}).get("comparison_table", [])
        position_data = result_dict.get("positioning", {})
        valuation_values = [
            self._safe_numeric(item.get("pe_ratio"))
            for item in comparison_table
            if self._safe_numeric(item.get("pe_ratio")) is not None
        ]
        market_caps = [
            self._safe_numeric(item.get("market_cap"))
            for item in comparison_table
            if self._safe_numeric(item.get("market_cap")) is not None
        ]
        growth_values = [
            self._safe_numeric(item.get("growth"))
            for item in comparison_table
            if self._safe_numeric(item.get("growth")) is not None
        ]
        payload = self._make_structured_payload(
            entity={"symbol": symbol, "name": result_dict.get("company_name")},
            facts={
                "reported": {
                    "target_profile": self._strip_subjective_profile_fields(
                        result_dict.get("target_profile", {})
                    ),
                    "peer_set": comparison_table,
                },
                "consensus": {},
            },
            analysis={
                "derived": {
                    "positioning_matrix": {
                        "matrix": position_data.get("matrix", {}),
                        "data_points": position_data.get("data_points", []),
                    },
                    "comparison_table": comparison_table,
                    "industry_concentration": {
                        "peer_count": len(comparison_table),
                        "median_market_cap": self._median(market_caps),
                        "median_growth": self._median(growth_values),
                    },
                    "valuation_background": {
                        "median_pe_ratio": self._median(valuation_values),
                        "min_pe_ratio": min(valuation_values) if valuation_values else None,
                        "max_pe_ratio": max(valuation_values) if valuation_values else None,
                    },
                }
            },
            as_of=None,
            sources=["yfinance"],
            data_completeness="partial",
            limitations=["Peer universe is heuristic and based on competitive analyzer mapping."],
            interface_type="mixed",
        )
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_earnings_preview_module(
        self,
        *,
        symbol: str,
        info_record: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw_data = info_record.get("raw_data", {}) if isinstance(info_record, dict) else {}
        info = raw_data.get("info", {}) if isinstance(raw_data, dict) else {}
        next_earnings_date = self._resolve_next_earnings_date(raw_data)
        revenue_growth = self._safe_numeric(info.get("revenueGrowth"))
        earnings_growth = self._safe_numeric(info.get("earningsGrowth"))
        current_price = self._safe_numeric(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )
        base_move = max(min((earnings_growth or revenue_growth or 0.05), 0.15), 0.02)
        scenarios = {
            "bull": {
                "implied_price": current_price * (1 + base_move * 2) if current_price else None
            },
            "base": {"implied_price": current_price * (1 + base_move) if current_price else None},
            "bear": {"implied_price": current_price * (1 - base_move) if current_price else None},
        }
        payload = self._make_structured_payload(
            entity={"symbol": symbol, "name": info_record.get("name")},
            facts={
                "reported": {
                    "next_earnings_date": next_earnings_date,
                    "market_snapshot": {
                        "current_price": current_price,
                        "revenue_growth": revenue_growth,
                        "earnings_growth": earnings_growth,
                    },
                },
                "consensus": {},
            },
            analysis={
                "model_output": {
                    "scenarios": scenarios,
                },
                "derived": {
                    "key_metrics_to_watch": [
                        metric_name
                        for metric_name, metric_value in (
                            ("revenue_growth", revenue_growth),
                            ("earnings_growth", earnings_growth),
                        )
                        if metric_value is not None
                    ],
                },
            },
            as_of=next_earnings_date,
            sources=["yfinance"],
            data_completeness="partial",
            limitations=[
                "Preview scenarios are deterministic placeholders when Street consensus is unavailable."
            ],
            interface_type="mixed",
        )
        return self._wrap_structured_module(
            payload=payload,
            status="ok" if next_earnings_date else "partial",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_catalysts_module(
        self,
        *,
        market: str,
        symbol: str,
        info_record: Dict[str, Any],
        native_item: Optional[Dict[str, Any]],
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        events: list[Dict[str, Any]] = []
        limitations: list[str] = []
        if market == "cn":
            if native_item is not None:
                events.extend((native_item.get("derived") or {}).get("catalyst_timeline", []))
            else:
                limitations.append(
                    "CN catalyst module requires native research blocks for announcement/news events."
                )
        else:
            raw_data = info_record.get("raw_data", {}) if isinstance(info_record, dict) else {}
            next_earnings_date = self._resolve_next_earnings_date(raw_data)
            if next_earnings_date:
                events.append(
                    {
                        "event_type": "earnings",
                        "event_time": next_earnings_date,
                        "title": f"{symbol} earnings date",
                        "source_label": "yfinance.earnings_dates",
                    }
                )
            else:
                limitations.append("No future earnings date available from yfinance.")
        counts = Counter(
            str(event.get("event_type") or "").strip()
            for event in events
            if event.get("event_type")
        )
        payload = self._make_structured_payload(
            entity={"symbol": symbol, "name": info_record.get("name")},
            facts={"reported": {"events": events}, "consensus": {}},
            analysis={
                "derived": {
                    "event_type_distribution": dict(counts),
                    "event_count": len(events),
                    "horizon_days": options.get("horizon_days"),
                }
            },
            as_of=None,
            sources=[self.PROVIDER_ORDER[0] if market == "cn" else "yfinance"],
            data_completeness="partial" if limitations else "ok",
            limitations=limitations,
            interface_type="fact",
        )
        return self._wrap_structured_module(
            payload=payload,
            status="partial" if limitations else "ok",
            error=None,
            attempted_sources=[self.PROVIDER_ORDER[0] if market == "cn" else "yfinance"],
        )

    def _build_model_update_module(
        self,
        *,
        market: str,
        symbol: str,
        info: Dict[str, Any],
        module_options: Mapping[str, Any],
        module_cache: Dict[str, Any],
    ) -> Dict[str, Any]:
        refreshed_modules: Dict[str, Any] = {}
        earnings_module = module_cache.get("earnings")
        if earnings_module is None:
            earnings_module = self._execute_module(
                market=market,
                module="earnings",
                requested_symbol=symbol,
                module_options=module_options,
                module_cache=module_cache,
                start_date="",
                end_date="",
                news_start="",
                news_end="",
                change_anchor=pd.Timestamp.now().normalize(),
            )
        refreshed_modules["earnings"] = self._module_status(earnings_module)
        if market == "us":
            for module_name in ("dcf", "three_statement"):
                module_payload = module_cache.get(module_name)
                if module_payload is None:
                    module_payload = self._execute_module(
                        market=market,
                        module=module_name,
                        requested_symbol=symbol,
                        module_options=module_options,
                        module_cache=module_cache,
                        start_date="",
                        end_date="",
                        news_start="",
                        news_end="",
                        change_anchor=pd.Timestamp.now().normalize(),
                    )
                refreshed_modules[module_name] = self._module_status(module_payload)
        payload = self._make_structured_payload(
            entity={"symbol": symbol, "name": info.get("common", {}).get("name")},
            facts={"reported": {"input_overrides": dict(module_options)}, "consensus": {}},
            analysis={
                "derived": {
                    "refreshed_modules": refreshed_modules,
                    "available_actuals": (
                        (earnings_module.get("facts", {}) or {}).get("reported", {})
                        if isinstance(earnings_module, dict)
                        else {}
                    ),
                }
            },
            as_of=None,
            sources=[self.TOP_LEVEL_SOURCE],
            data_completeness="partial",
            limitations=[
                "Model update is a deterministic refresh summary, not a stored revision history."
            ],
            interface_type="mixed",
        )
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=[self.TOP_LEVEL_SOURCE],
        )

    def _build_sector_overview_module(
        self,
        *,
        symbol: str,
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        competitive_module = self._build_competitive_module(symbol=symbol, options=options)
        if competitive_module.get("module_status") == "error":
            return competitive_module
        comparison_table = (
            ((competitive_module.get("analysis") or {}).get("derived") or {}).get(
                "comparison_table"
            )
        ) or []
        market_caps = [
            self._safe_numeric(item.get("market_cap"))
            for item in comparison_table
            if self._safe_numeric(item.get("market_cap")) is not None
        ]
        growth_values = [
            self._safe_numeric(item.get("growth"))
            for item in comparison_table
            if self._safe_numeric(item.get("growth")) is not None
        ]
        gross_margin_values = [
            self._safe_numeric(item.get("gross_margin"))
            for item in comparison_table
            if self._safe_numeric(item.get("gross_margin")) is not None
        ]
        pe_values = [
            self._safe_numeric(item.get("pe_ratio"))
            for item in comparison_table
            if self._safe_numeric(item.get("pe_ratio")) is not None
        ]
        payload = self._make_structured_payload(
            entity={"symbol": symbol},
            facts={"reported": {"peer_set": comparison_table}, "consensus": {}},
            analysis={
                "derived": {
                    "peer_count": len(comparison_table),
                    "median_market_cap": self._median(market_caps),
                    "median_growth": self._median(growth_values),
                    "median_gross_margin": self._median(gross_margin_values),
                    "median_pe_ratio": self._median(pe_values),
                }
            },
            as_of=None,
            sources=["yfinance"],
            data_completeness="partial",
            limitations=[
                "Sector overview is derived from the peer set available to the competitive analyzer."
            ],
            interface_type="mixed",
        )
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=["yfinance"],
        )

    def _build_screen_module(
        self,
        *,
        market: str,
        symbol: str,
        info_record: Dict[str, Any],
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        filters = (
            options.get("filters", {}) if isinstance(options.get("filters", {}), Mapping) else {}
        )
        metrics = self._screen_metrics(market=market, symbol=symbol, info_record=info_record)
        evaluations = self._evaluate_filters(metrics=metrics, filters=filters)
        payload = self._make_structured_payload(
            entity={"symbol": symbol, "name": info_record.get("name")},
            facts={"reported": {"metrics": metrics}, "consensus": {}},
            analysis={
                "derived": {
                    "filters": evaluations,
                    "passed": (
                        all(item.get("passed") for item in evaluations.values())
                        if evaluations
                        else True
                    ),
                    "filter_count": len(evaluations),
                }
            },
            as_of=None,
            sources=[metrics.get("_source", self.TOP_LEVEL_SOURCE)],
            data_completeness="partial",
            limitations=[
                "Screen evaluates only the requested symbols, not a full market universe."
            ],
            interface_type="mixed",
        )
        return self._wrap_structured_module(
            payload=payload,
            status="ok",
            error=None,
            attempted_sources=[metrics.get("_source", self.TOP_LEVEL_SOURCE)],
        )

    def _make_structured_payload(
        self,
        *,
        entity: Dict[str, Any],
        facts: Dict[str, Any],
        analysis: Dict[str, Any],
        as_of: Optional[str],
        sources: Sequence[str],
        data_completeness: str,
        limitations: Sequence[str],
        interface_type: str,
    ) -> Dict[str, Any]:
        return InterfacePayload(
            entity=entity,
            facts=facts,
            analysis=analysis,
            meta=InterfaceMeta(
                as_of=as_of,
                sources=list(sources),
                data_completeness=data_completeness,
                limitations=list(limitations),
                interface_type=interface_type,
            ),
        ).to_dict()

    def _empty_structured_payload(
        self,
        *,
        interface_type: str,
        limitations: Sequence[str],
    ) -> Dict[str, Any]:
        return self._make_structured_payload(
            entity={},
            facts={},
            analysis={},
            as_of=None,
            sources=[],
            data_completeness="empty",
            limitations=limitations,
            interface_type=interface_type,
        )

    def _wrap_structured_module(
        self,
        *,
        payload: Dict[str, Any],
        status: str,
        error: Optional[str],
        attempted_sources: Sequence[str],
    ) -> Dict[str, Any]:
        wrapped = self._sanitize_structured_payload(payload)
        wrapped["module_status"] = status
        wrapped["module_error"] = error
        wrapped["attempted_sources"] = list(attempted_sources)
        return wrapped

    def _sanitize_structured_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = copy.deepcopy(payload)
        cleaned = self._prune_forbidden_keys(cleaned)
        self._strip_analyst_consensus_fields(cleaned)
        return cleaned

    def _prune_forbidden_keys(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._prune_forbidden_keys(item) for item in value]
        if isinstance(value, dict):
            pruned: Dict[str, Any] = {}
            for key, item in value.items():
                if key in self.OBJECTIVE_FORBIDDEN_KEYS:
                    continue
                pruned[key] = self._prune_forbidden_keys(item)
            return pruned
        return value

    def _strip_analyst_consensus_fields(self, payload: Dict[str, Any]) -> None:
        if isinstance(payload, dict):
            if isinstance(payload.get("analyst_consensus"), dict):
                analyst_count = payload["analyst_consensus"].get("analyst_count")
                payload["analyst_consensus"] = (
                    {"analyst_count": analyst_count} if analyst_count is not None else {}
                )
            for value in payload.values():
                self._strip_analyst_consensus_fields(value)
        elif isinstance(payload, list):
            for item in payload:
                self._strip_analyst_consensus_fields(item)

    @staticmethod
    def _strip_subjective_profile_fields(profile: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = copy.deepcopy(profile if isinstance(profile, dict) else {})
        if isinstance(sanitized.get("analyst_consensus"), dict):
            analyst_count = sanitized["analyst_consensus"].get("analyst_count")
            sanitized["analyst_consensus"] = (
                {"analyst_count": analyst_count} if analyst_count is not None else {}
            )
        return sanitized

    @staticmethod
    def _safe_numeric(value: Any) -> Optional[float]:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _median(values: Sequence[Optional[float]]) -> Optional[float]:
        clean = sorted(value for value in values if value is not None)
        if not clean:
            return None
        midpoint = len(clean) // 2
        if len(clean) % 2 == 1:
            return clean[midpoint]
        return (clean[midpoint - 1] + clean[midpoint]) / 2

    @staticmethod
    def _resolve_next_earnings_date(raw_data: Mapping[str, Any]) -> Optional[str]:
        candidates: list[pd.Timestamp] = []
        for value in raw_data.get("earnings_dates", []) if isinstance(raw_data, Mapping) else []:
            try:
                candidates.append(pd.Timestamp(value))
            except Exception:
                continue
        calendar = raw_data.get("calendar", {}) if isinstance(raw_data, Mapping) else {}
        if isinstance(calendar, Mapping):
            for key in ("Earnings Date", "earningsDate"):
                calendar_value = calendar.get(key)
                if isinstance(calendar_value, (list, tuple)):
                    iterable = calendar_value
                else:
                    iterable = [calendar_value]
                for item in iterable:
                    try:
                        candidates.append(pd.Timestamp(item))
                    except Exception:
                        continue
        now = pd.Timestamp.now(tz="UTC")
        future = sorted(timestamp for timestamp in candidates if timestamp >= now)
        if future:
            return future[0].isoformat()
        return None

    def _screen_metrics(
        self,
        *,
        market: str,
        symbol: str,
        info_record: Dict[str, Any],
    ) -> Dict[str, Any]:
        if market == "us":
            raw_data = info_record.get("raw_data", {}) if isinstance(info_record, dict) else {}
            info = raw_data.get("info", {}) if isinstance(raw_data, dict) else {}
            return {
                "_source": "yfinance",
                "market_cap": self._safe_numeric(info.get("marketCap")),
                "revenue_growth": self._safe_numeric(info.get("revenueGrowth")),
                "earnings_growth": self._safe_numeric(info.get("earningsGrowth")),
                "gross_margin": self._safe_numeric(info.get("grossMargins")),
                "pe_ratio": self._safe_numeric(info.get("trailingPE")),
                "price_to_book": self._safe_numeric(info.get("priceToBook")),
            }

        financial_data, source_name = data_manager.get_financial_data(symbol)
        return {
            "_source": source_name or "financial_provider",
            "pe_ratio": self._safe_numeric((financial_data or {}).get("pe_ratio")),
            "price_to_book": self._safe_numeric((financial_data or {}).get("pb_ratio")),
            "roe": self._safe_numeric((financial_data or {}).get("roe")),
            "revenue_growth": self._safe_numeric((financial_data or {}).get("revenue_growth")),
            "debt_ratio": self._safe_numeric((financial_data or {}).get("debt_ratio")),
        }

    def _evaluate_filters(
        self,
        *,
        metrics: Mapping[str, Any],
        filters: Mapping[str, Any],
    ) -> Dict[str, Any]:
        evaluations: Dict[str, Any] = {}
        for field, condition in filters.items():
            actual = self._safe_numeric(metrics.get(field))
            passed = True
            normalized_condition = (
                condition if isinstance(condition, Mapping) else {"eq": condition}
            )
            for operator, expected in normalized_condition.items():
                numeric_expected = self._safe_numeric(expected)
                if operator == "gte":
                    passed = (
                        passed
                        and actual is not None
                        and numeric_expected is not None
                        and actual >= numeric_expected
                    )
                elif operator == "lte":
                    passed = (
                        passed
                        and actual is not None
                        and numeric_expected is not None
                        and actual <= numeric_expected
                    )
                elif operator == "gt":
                    passed = (
                        passed
                        and actual is not None
                        and numeric_expected is not None
                        and actual > numeric_expected
                    )
                elif operator == "lt":
                    passed = (
                        passed
                        and actual is not None
                        and numeric_expected is not None
                        and actual < numeric_expected
                    )
                elif operator == "eq":
                    passed = (
                        passed
                        and actual is not None
                        and numeric_expected is not None
                        and actual == numeric_expected
                    )
                elif operator == "in":
                    passed = (
                        passed and metrics.get(field) in expected
                        if isinstance(expected, Sequence)
                        else False
                    )
            evaluations[str(field)] = {
                "actual": metrics.get(field),
                "condition": condition,
                "passed": bool(passed),
            }
        return evaluations

    def _build_failed_item(
        self,
        *,
        requested_symbol: str,
        code: str,
        message: str,
        attempted_sources: Sequence[str],
    ) -> Dict[str, Any]:
        return {
            "requested_symbol": requested_symbol,
            "status": "failed",
            "error": {"code": code, "message": message},
            "info": self._empty_identity(),
            "research_report": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="error",
                source_error=message,
            ),
            "report_rc": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="error",
                source_error=message,
            ),
            "anns_d": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="error",
                source_error=message,
            ),
            "news": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="error",
                source_error=message,
                extra={"filter_rule": self._filter_rule_text()},
            ),
            "major_news": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="error",
                source_error=message,
                extra={"filter_rule": self._filter_rule_text()},
            ),
            "derived": self._empty_derived(),
        }

    def _build_not_supported_item(
        self,
        *,
        requested_symbol: str,
        attempted_sources: Sequence[str],
        info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        message = "CN research snapshot only supports listed common stock."
        return {
            "requested_symbol": requested_symbol,
            "status": "not_supported",
            "error": {"code": "security_not_supported", "message": message},
            "info": info or self._empty_identity(),
            "research_report": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
            ),
            "report_rc": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
            ),
            "anns_d": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
            ),
            "news": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
                extra={"filter_rule": self._filter_rule_text()},
            ),
            "major_news": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
                extra={"filter_rule": self._filter_rule_text()},
            ),
            "derived": self._empty_derived(),
        }

    def _build_not_implemented_item(
        self,
        *,
        requested_symbol: str,
        attempted_sources: Sequence[str],
    ) -> Dict[str, Any]:
        message = "US research snapshot is reserved for a future implementation."
        return {
            "requested_symbol": requested_symbol,
            "status": "not_implemented",
            "error": {"code": "market_not_implemented", "message": message},
            "info": self._empty_identity(),
            "research_report": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
            ),
            "report_rc": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
            ),
            "anns_d": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
            ),
            "news": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
                extra={"filter_rule": self._filter_rule_text()},
            ),
            "major_news": self._empty_block(
                attempted_sources=attempted_sources,
                source_status="not_supported",
                source_error=message,
                extra={"filter_rule": self._filter_rule_text()},
            ),
            "derived": self._empty_derived(),
        }

    def _dispatch_record(self, method_name: str, **kwargs: Any) -> Dict[str, Any]:
        attempted_sources: list[str] = []
        fallback = {
            "record": None,
            "status": "empty",
            "error": None,
            "source": None,
            "attempted_sources": attempted_sources,
        }
        for provider_name in self.PROVIDER_ORDER:
            attempted_sources.append(provider_name)
            provider = self.providers.get(provider_name)
            if provider is None or not hasattr(provider, method_name):
                fallback = {
                    "record": None,
                    "status": "not_supported",
                    "error": f"{method_name} not supported by {provider_name}",
                    "source": provider_name,
                    "attempted_sources": attempted_sources,
                }
                continue

            response = getattr(provider, method_name)(**kwargs)
            status = response.get("status", "error")
            if status == "ok" and response.get("record") is not None:
                return {
                    "record": response.get("record"),
                    "status": "ok",
                    "error": response.get("error"),
                    "source": provider_name,
                    "attempted_sources": attempted_sources,
                }
            if status in {"permission_denied", "error"}:
                fallback = {
                    "record": None,
                    "status": status,
                    "error": response.get("error"),
                    "source": provider_name,
                    "attempted_sources": attempted_sources,
                }
                break
            fallback = {
                "record": None,
                "status": status,
                "error": response.get("error"),
                "source": provider_name,
                "attempted_sources": attempted_sources,
            }
        return fallback

    def _dispatch_block(self, method_name: str, **kwargs: Any) -> Dict[str, Any]:
        attempted_sources: list[str] = []
        best_failure = {
            "source_status": "not_supported",
            "source_error": None,
            "source": None,
        }
        for provider_name in self.PROVIDER_ORDER:
            attempted_sources.append(provider_name)
            provider = self.providers.get(provider_name)
            if provider is None or not hasattr(provider, method_name):
                best_failure = self._pick_failure(
                    best_failure,
                    {
                        "source_status": "not_supported",
                        "source_error": f"{method_name} not supported by {provider_name}",
                        "source": provider_name,
                    },
                )
                continue

            response = getattr(provider, method_name)(**kwargs)
            status = response.get("status", "error")
            if status in {"ok", "empty"}:
                return self._build_block(
                    records=response.get("rows", []),
                    source=provider_name,
                    source_status=status,
                    source_error=response.get("error"),
                    attempted_sources=attempted_sources,
                )
            best_failure = self._pick_failure(
                best_failure,
                {
                    "source_status": status,
                    "source_error": response.get("error"),
                    "source": provider_name,
                },
            )

        return self._build_block(
            records=[],
            source=best_failure.get("source"),
            source_status=best_failure.get("source_status", "error"),
            source_error=best_failure.get("source_error"),
            attempted_sources=attempted_sources,
        )

    def _resolve_report_rc_block(
        self,
        *,
        requested_block: Dict[str, Any],
        ts_code: str,
        requested_start_date: str,
        requested_end_date: str,
    ) -> Dict[str, Any]:
        requested_items = self._sort_and_dedupe_rows(
            requested_block["records"],
            order=(
                ("report_date", False),
                ("quarter", False),
                ("org_name", True),
                ("report_title", True),
            ),
        )
        specific_requested_items = self._filter_stock_specific_report_rc_rows(requested_items)
        if specific_requested_items:
            requested_block["records"] = specific_requested_items
            requested_block.update(
                {
                    "requested_start_date": requested_start_date,
                    "requested_end_date": requested_end_date,
                    "resolved_start_date": requested_start_date,
                    "resolved_end_date": requested_end_date,
                    "fallback_mode": "requested_window",
                }
            )
            return requested_block

        history_block = self._dispatch_block("fetch_report_rc", ts_code=ts_code)
        history_items = self._sort_and_dedupe_rows(
            history_block["records"],
            order=(
                ("report_date", False),
                ("quarter", False),
                ("org_name", True),
                ("report_title", True),
            ),
        )
        specific_history_items = self._filter_stock_specific_report_rc_rows(history_items)
        if not specific_history_items:
            requested_block["records"] = requested_items
            requested_block.update(
                {
                    "requested_start_date": requested_start_date,
                    "requested_end_date": requested_end_date,
                    "resolved_start_date": requested_start_date,
                    "resolved_end_date": requested_end_date,
                    "fallback_mode": "requested_window_no_specific_history",
                }
            )
            return requested_block

        latest_specific_date = str(specific_history_items[0].get("report_date") or "").strip()
        latest_specific_group = [
            row
            for row in specific_history_items
            if str(row.get("report_date") or "").strip() == latest_specific_date
        ]
        return self._build_block(
            records=latest_specific_group,
            source=history_block.get("source"),
            source_status=history_block.get("source_status", "ok"),
            source_error=history_block.get("source_error"),
            attempted_sources=history_block.get("attempted_sources", []),
            extra={
                "requested_start_date": requested_start_date,
                "requested_end_date": requested_end_date,
                "resolved_start_date": latest_specific_date,
                "resolved_end_date": latest_specific_date,
                "fallback_mode": "latest_stock_specific_report_date",
            },
        )

    def _collect_news_block(
        self,
        *,
        method_name: str,
        sources: Sequence[str],
        symbol: str,
        ts_code: str,
        name: str,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        attempted_sources = list(self.PROVIDER_ORDER)
        all_rows: list[Dict[str, Any]] = []
        failures: list[Dict[str, Any]] = []
        for src in sources:
            block = self._dispatch_block(
                method_name,
                src=src,
                start_date=start_date,
                end_date=end_date,
            )
            status = block["source_status"]
            if status in {"ok", "empty"}:
                all_rows.extend(block["records"])
            else:
                failures.append(block)

        filtered_rows = self._filter_rows_by_mentions(
            rows=all_rows,
            mentions=[symbol, ts_code, name],
        )
        filtered_rows = self._dedupe_rows(filtered_rows)

        if filtered_rows:
            source_status = "ok"
            source_error = None
        elif failures:
            source_status = failures[0]["source_status"]
            source_error = failures[0]["source_error"]
        else:
            source_status = "empty"
            source_error = None

        return self._build_block(
            records=filtered_rows,
            source=self.PROVIDER_ORDER[0],
            source_status=source_status,
            source_error=source_error,
            attempted_sources=attempted_sources,
            extra={"filter_rule": self._filter_rule_text()},
        )

    def _build_identity(self, record: Dict[str, Any]) -> Dict[str, Any]:
        is_cn = bool(record.get("ts_code"))
        is_us = not is_cn and bool(record.get("symbol"))
        return {
            "common": {
                "ts_code": record.get("ts_code"),
                "name": record.get("name"),
                "list_date": record.get("list_date"),
                "delist_date": record.get("delist_date"),
            },
            "cn_specific": {
                "symbol": record.get("symbol") if is_cn else None,
                "exchange": record.get("exchange") if is_cn else None,
                "list_status": record.get("list_status") if is_cn else None,
                "area": record.get("area") if is_cn else None,
                "industry": record.get("industry") if is_cn else None,
                "market": record.get("market") if is_cn else None,
            },
            "us_specific": {
                "ts_code": record.get("us_ts_code") or (record.get("symbol") if is_us else None),
                "name": record.get("us_name") or (record.get("name") if is_us else None),
                "enname": record.get("enname"),
                "classify": record.get("classify")
                or (record.get("security_type") if is_us else None),
                "list_date": record.get("us_list_date"),
                "delist_date": record.get("us_delist_date"),
            },
        }

    def _empty_identity(self) -> Dict[str, Any]:
        return {
            "common": {
                "ts_code": None,
                "name": None,
                "list_date": None,
                "delist_date": None,
            },
            "cn_specific": {
                "symbol": None,
                "exchange": None,
                "list_status": None,
                "area": None,
                "industry": None,
                "market": None,
            },
            "us_specific": {
                "ts_code": None,
                "name": None,
                "enname": None,
                "classify": None,
                "list_date": None,
                "delist_date": None,
            },
        }

    def _build_derived(
        self,
        *,
        research_report: Sequence[Dict[str, Any]],
        report_rc: Sequence[Dict[str, Any]],
        anns_d: Sequence[Dict[str, Any]],
        news: Sequence[Dict[str, Any]],
        major_news: Sequence[Dict[str, Any]],
        change_anchor: pd.Timestamp,
    ) -> Dict[str, Any]:
        catalyst_timeline = self._build_catalyst_timeline(
            anns_d=anns_d,
            news=news,
            major_news=major_news,
        )
        return {
            "coverage_snapshot": self._build_coverage_snapshot(research_report),
            "estimate_snapshot": self._build_estimate_snapshot(report_rc),
            "catalyst_timeline": catalyst_timeline,
            "change_flags": {
                "has_new_report_7d": self._has_recent_rows(
                    research_report,
                    date_fields=("trade_date",),
                    anchor=change_anchor,
                ),
                "has_new_estimate_7d": self._has_recent_rows(
                    report_rc,
                    date_fields=("report_date",),
                    anchor=change_anchor,
                ),
                "has_new_catalyst_7d": self._has_recent_rows(
                    catalyst_timeline,
                    date_fields=("event_time",),
                    anchor=change_anchor,
                ),
            },
        }

    def _empty_derived(self) -> Dict[str, Any]:
        return {
            "coverage_snapshot": {
                "report_count": 0,
                "latest_trade_date": None,
                "institution_count": 0,
                "report_type_distribution": {},
            },
            "estimate_snapshot": {
                "report_count": 0,
                "latest_report_date": None,
                "latest_records": [],
                "by_quarter": {},
                "rating_distribution": {},
            },
            "catalyst_timeline": [],
            "change_flags": {
                "has_new_report_7d": False,
                "has_new_estimate_7d": False,
                "has_new_catalyst_7d": False,
            },
        }

    def _build_coverage_snapshot(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        report_types = Counter(
            str(row.get("report_type") or "").strip()
            for row in rows
            if str(row.get("report_type") or "").strip()
        )
        institutions = {
            str(row.get("inst_csname") or "").strip()
            for row in rows
            if str(row.get("inst_csname") or "").strip()
        }
        return {
            "report_count": len(rows),
            "latest_trade_date": self._max_datetime_text(rows, ("trade_date",)),
            "institution_count": len(institutions),
            "report_type_distribution": dict(report_types),
        }

    def _build_estimate_snapshot(self, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        latest_report_date = self._max_datetime_text(rows, ("report_date",))
        latest_records = [
            row
            for row in rows
            if str(row.get("report_date") or "").strip() == str(latest_report_date or "")
        ]
        rating_distribution = Counter(
            str(row.get("rating") or "").strip()
            for row in rows
            if str(row.get("rating") or "").strip()
        )
        by_quarter: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            quarter = str(row.get("quarter") or "").strip()
            if not quarter:
                continue
            bucket = by_quarter.setdefault(
                quarter,
                {"count": 0, "latest_report_date": None, "rating_distribution": {}},
            )
            bucket["count"] += 1
            report_date = str(row.get("report_date") or "").strip() or None
            if report_date and (
                bucket["latest_report_date"] is None or report_date > bucket["latest_report_date"]
            ):
                bucket["latest_report_date"] = report_date
            rating = str(row.get("rating") or "").strip()
            if rating:
                rating_distribution_payload = bucket["rating_distribution"]
                rating_distribution_payload[rating] = rating_distribution_payload.get(rating, 0) + 1

        return {
            "report_count": len(rows),
            "latest_report_date": latest_report_date,
            "latest_records": latest_records,
            "by_quarter": by_quarter,
            "rating_distribution": dict(rating_distribution),
        }

    def _build_catalyst_timeline(
        self,
        *,
        anns_d: Sequence[Dict[str, Any]],
        news: Sequence[Dict[str, Any]],
        major_news: Sequence[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        events: list[Dict[str, Any]] = []
        for row in anns_d:
            events.append(
                {
                    "event_type": "announcement",
                    "event_time": row.get("rec_time") or row.get("ann_date"),
                    "title": row.get("title"),
                    "source_label": "anns_d",
                }
            )
        for row in news:
            events.append(
                {
                    "event_type": "news",
                    "event_time": row.get("datetime") or row.get("pub_time"),
                    "title": row.get("title"),
                    "source_label": row.get("src") or "news",
                }
            )
        for row in major_news:
            events.append(
                {
                    "event_type": "major_news",
                    "event_time": row.get("pub_time") or row.get("datetime"),
                    "title": row.get("title"),
                    "source_label": row.get("src") or "major_news",
                }
            )
        return self._sort_and_dedupe_rows(
            events, order=(("event_time", False), ("source_label", True))
        )

    def _has_recent_rows(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        date_fields: Sequence[str],
        anchor: pd.Timestamp,
    ) -> bool:
        threshold = anchor - pd.Timedelta(days=7)
        for row in rows:
            timestamp = self._extract_timestamp(row, date_fields)
            if timestamp is not None and timestamp >= threshold:
                return True
        return False

    def _resolve_window(
        self, *, start_date: Optional[str], end_date: Optional[str]
    ) -> Dict[str, Any]:
        end_ts = (
            self._parse_date(end_date) or pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        )
        start_ts = self._parse_date(start_date) or (end_ts - pd.Timedelta(days=30))
        if start_ts > end_ts:
            raise ValueError("start_date must be earlier than or equal to end_date")

        return {
            "start_date": start_ts.strftime("%Y%m%d"),
            "end_date": end_ts.strftime("%Y%m%d"),
            "news_start": start_ts.strftime("%Y-%m-%d 00:00:00"),
            "news_end": end_ts.strftime("%Y-%m-%d 23:59:59"),
            "change_anchor": end_ts.tz_localize(None) if end_ts.tzinfo is not None else end_ts,
        }

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[pd.Timestamp]:
        if not value:
            return None
        try:
            timestamp = pd.Timestamp(value)
        except Exception as exc:
            raise ValueError(f"Invalid date: {value}") from exc
        return timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp

    @staticmethod
    def _normalize_market(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"cn", "us"}:
            raise ValueError("market must be either `cn` or `us`")
        return normalized

    @staticmethod
    def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
        normalized: list[str] = []
        for symbol in symbols:
            text = str(symbol or "").strip().upper()
            if "." in text:
                text = text.split(".", 1)[0]
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _build_block(
        *,
        records: Sequence[Dict[str, Any]],
        source: Optional[str],
        source_status: str,
        source_error: Optional[str],
        attempted_sources: Sequence[str],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        block = {
            "records": list(records),
            "source": source,
            "source_status": source_status,
            "source_error": source_error,
            "attempted_sources": list(attempted_sources),
        }
        if extra:
            block.update(extra)
        return block

    def _empty_block(
        self,
        *,
        attempted_sources: Sequence[str],
        source_status: str,
        source_error: Optional[str],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._build_block(
            records=[],
            source=self.PROVIDER_ORDER[0] if self.PROVIDER_ORDER else None,
            source_status=source_status,
            source_error=source_error,
            attempted_sources=attempted_sources,
            extra=extra,
        )

    @staticmethod
    def _filter_rows_by_mentions(
        *,
        rows: Sequence[Dict[str, Any]],
        mentions: Sequence[str],
    ) -> list[Dict[str, Any]]:
        cleaned_mentions = [str(item or "").strip() for item in mentions if str(item or "").strip()]
        if not cleaned_mentions:
            return []

        filtered: list[Dict[str, Any]] = []
        for row in rows:
            haystacks = [
                str(row.get("title") or ""),
                str(row.get("content") or ""),
            ]
            joined = "\n".join(haystacks)
            if any(mention in joined for mention in cleaned_mentions):
                filtered.append(dict(row))
        return filtered

    @staticmethod
    def _filter_rule_text() -> str:
        return "title_or_content_contains_any(symbol, ts_code, name)"

    @staticmethod
    def _filter_stock_specific_report_rc_rows(
        rows: Sequence[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        filtered: list[Dict[str, Any]] = []
        for row in rows:
            report_type = str(row.get("report_type") or "").strip()
            if report_type == "非个股":
                continue
            filtered.append(dict(row))
        return filtered

    def _has_stock_specific_report_rc_rows(self, rows: Sequence[Dict[str, Any]]) -> bool:
        return bool(self._filter_stock_specific_report_rc_rows(rows))

    @staticmethod
    def _dedupe_rows(rows: Sequence[Dict[str, Any]]) -> list[Dict[str, Any]]:
        deduped: list[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            key = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(dict(row))
        return deduped

    def _sort_and_dedupe_rows(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        order: Sequence[tuple[str, bool]],
    ) -> list[Dict[str, Any]]:
        deduped = self._dedupe_rows(rows)
        if not deduped:
            return []

        dataframe = pd.DataFrame(deduped)
        sort_columns = [column for column, _ in order if column in dataframe.columns]
        if not sort_columns:
            return deduped

        ascending = [ascending for column, ascending in order if column in dataframe.columns]
        sorted_df = dataframe.sort_values(
            by=sort_columns,
            ascending=ascending,
            na_position="last",
            kind="mergesort",
        )
        return self._normalize_dataframe_records(sorted_df.reset_index(drop=True))

    @staticmethod
    def _normalize_dataframe_records(df: pd.DataFrame) -> list[Dict[str, Any]]:
        rows = df.to_dict("records")
        normalized: list[Dict[str, Any]] = []
        for row in rows:
            item: Dict[str, Any] = {}
            for key, value in row.items():
                if pd.isna(value):
                    item[key] = None
                elif isinstance(value, pd.Timestamp):
                    item[key] = value.isoformat()
                else:
                    item[key] = value
            normalized.append(item)
        return normalized

    @staticmethod
    def _pick_failure(current: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        priority = {"permission_denied": 4, "error": 3, "not_supported": 2, "empty": 1}
        if priority.get(candidate.get("source_status"), 0) >= priority.get(
            current.get("source_status"), 0
        ):
            return candidate
        return current

    @staticmethod
    def _extract_timestamp(
        row: Dict[str, Any], date_fields: Sequence[str]
    ) -> Optional[pd.Timestamp]:
        for field in date_fields:
            value = row.get(field)
            if not value:
                continue
            try:
                timestamp = pd.Timestamp(value)
            except Exception:
                continue
            return timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
        return None

    def _max_datetime_text(
        self,
        rows: Sequence[Dict[str, Any]],
        date_fields: Sequence[str],
    ) -> Optional[str]:
        max_timestamp: Optional[pd.Timestamp] = None
        max_text: Optional[str] = None
        for row in rows:
            timestamp = self._extract_timestamp(row, date_fields)
            if timestamp is None:
                continue
            if max_timestamp is None or timestamp > max_timestamp:
                max_timestamp = timestamp
                max_text = str(row.get(date_fields[0]) or timestamp.isoformat())
        return max_text


research_snapshot_service = ResearchSnapshotService()
