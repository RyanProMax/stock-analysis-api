from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from typing import Any, Dict, Mapping, Optional, Sequence

import pandas as pd

from ..data_provider.sources.tushare import TushareDataSource


class ResearchSnapshotService:
    PROVIDER_ORDER = ("tushare",)
    CORE_BLOCKS = ("research_report", "report_rc")
    OPTIONAL_BLOCKS = ("anns_d", "news", "major_news")
    NEWS_SOURCES = ("cls", "sina", "wallstreetcn", "10jqka")
    MAJOR_NEWS_SOURCES = ("新浪财经", "财联社", "中证网", "第一财经")

    def __init__(self, providers: Optional[Mapping[str, Any]] = None):
        self.providers = dict(providers or {"tushare": TushareDataSource})

    def poll_snapshot(
        self,
        *,
        market: str = "cn",
        symbols: Sequence[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_market = self._normalize_market(market)
        normalized_symbols = self._normalize_symbols(symbols)
        computed_at = datetime.now(timezone.utc).isoformat()
        window = self._resolve_window(start_date=start_date, end_date=end_date)
        attempted_sources = list(self.PROVIDER_ORDER)

        if normalized_market == "us":
            items = [
                self._build_not_implemented_item(
                    requested_symbol=symbol,
                    attempted_sources=attempted_sources,
                )
                for symbol in normalized_symbols
            ]
            return {
                "status": "not_implemented",
                "computed_at": computed_at,
                "source": self.PROVIDER_ORDER[0],
                "market": normalized_market,
                "strategy": "tushare_first_research_snapshot_v1",
                "request": {
                    "market": normalized_market,
                    "symbols": normalized_symbols,
                    "start_date": window["start_date"],
                    "end_date": window["end_date"],
                },
                "items": items,
            }

        items = [
            self._build_cn_item(
                requested_symbol=symbol,
                start_date=window["start_date"],
                end_date=window["end_date"],
                news_start=window["news_start"],
                news_end=window["news_end"],
                change_anchor=window["change_anchor"],
            )
            for symbol in normalized_symbols
        ]
        overall_status = (
            "ok" if items and all(item["status"] == "ok" for item in items) else "partial"
        )
        if not items:
            overall_status = "ok"

        return {
            "status": overall_status,
            "computed_at": computed_at,
            "source": self.PROVIDER_ORDER[0],
            "market": normalized_market,
            "strategy": "tushare_first_research_snapshot_v1",
            "request": {
                "market": normalized_market,
                "symbols": normalized_symbols,
                "start_date": window["start_date"],
                "end_date": window["end_date"],
            },
            "items": items,
        }

    def _build_cn_item(
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
            report_rc_requested["items"],
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
            report_rc["items"],
            order=(
                ("report_date", False),
                ("quarter", False),
                ("org_name", True),
                ("report_title", True),
            ),
        )
        report_rc["items"] = report_rc_items

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
            research_report["items"],
            order=(
                ("trade_date", False),
                ("inst_csname", True),
                ("title", True),
            ),
        )
        anns_d_items = self._sort_and_dedupe_rows(
            anns_d["items"],
            order=(
                ("ann_date", False),
                ("rec_time", False),
                ("title", True),
            ),
        )
        news_items = self._sort_and_dedupe_rows(
            news["items"],
            order=(("datetime", False), ("pub_time", False), ("src", True)),
        )
        major_news_items = self._sort_and_dedupe_rows(
            major_news["items"],
            order=(("pub_time", False), ("datetime", False), ("src", True)),
        )

        research_report["items"] = research_items
        report_rc["items"] = report_rc_items
        anns_d["items"] = anns_d_items
        news["items"] = news_items
        major_news["items"] = major_news_items

        core_statuses = [
            research_report["source_meta"]["source_status"],
            report_rc["source_meta"]["source_status"],
        ]
        optional_statuses = [
            anns_d["source_meta"]["source_status"],
            news["source_meta"]["source_status"],
            major_news["source_meta"]["source_status"],
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

        capabilities = self._build_capabilities(
            research_report=research_report,
            report_rc=report_rc,
            anns_d=anns_d,
            news=news,
            major_news=major_news,
        )

        return {
            "requested_symbol": requested_symbol,
            "status": item_status,
            "error": error,
            "info": info,
            "capabilities": capabilities,
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
            "capabilities": self._empty_capabilities(
                attempted_sources=attempted_sources,
                source_status="error",
            ),
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
            "capabilities": self._empty_capabilities(
                attempted_sources=attempted_sources,
                source_status="not_supported",
            ),
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
            "capabilities": self._empty_capabilities(
                attempted_sources=attempted_sources,
                source_status="not_supported",
            ),
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
            "status": "not_supported",
            "error": None,
            "source": None,
            "rows": [],
        }
        for provider_name in self.PROVIDER_ORDER:
            attempted_sources.append(provider_name)
            provider = self.providers.get(provider_name)
            if provider is None or not hasattr(provider, method_name):
                best_failure = self._pick_failure(
                    best_failure,
                    {
                        "status": "not_supported",
                        "error": f"{method_name} not supported by {provider_name}",
                        "source": provider_name,
                        "rows": [],
                    },
                )
                continue

            response = getattr(provider, method_name)(**kwargs)
            status = response.get("status", "error")
            if status in {"ok", "empty"}:
                return {
                    "items": response.get("rows", []),
                    "source_meta": self._build_source_meta(
                        source=provider_name,
                        source_status=status,
                        source_error=response.get("error"),
                        attempted_sources=attempted_sources,
                    ),
                }
            best_failure = self._pick_failure(
                best_failure,
                {
                    "status": status,
                    "error": response.get("error"),
                    "source": provider_name,
                    "rows": [],
                },
            )

        return {
            "items": [],
            "source_meta": self._build_source_meta(
                source=best_failure.get("source"),
                source_status=best_failure.get("status", "error"),
                source_error=best_failure.get("error"),
                attempted_sources=attempted_sources,
            ),
        }

    def _resolve_report_rc_block(
        self,
        *,
        requested_block: Dict[str, Any],
        ts_code: str,
        requested_start_date: str,
        requested_end_date: str,
    ) -> Dict[str, Any]:
        requested_items = self._sort_and_dedupe_rows(
            requested_block["items"],
            order=(
                ("report_date", False),
                ("quarter", False),
                ("org_name", True),
                ("report_title", True),
            ),
        )
        specific_requested_items = self._filter_stock_specific_report_rc_rows(requested_items)
        if specific_requested_items:
            requested_block["items"] = specific_requested_items
            requested_block["source_meta"].update(
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
            history_block["items"],
            order=(
                ("report_date", False),
                ("quarter", False),
                ("org_name", True),
                ("report_title", True),
            ),
        )
        specific_history_items = self._filter_stock_specific_report_rc_rows(history_items)
        if not specific_history_items:
            requested_block["items"] = requested_items
            requested_block["source_meta"].update(
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
        return {
            "items": latest_specific_group,
            "source_meta": self._build_source_meta(
                source=history_block["source_meta"].get("source"),
                source_status=history_block["source_meta"].get("source_status", "ok"),
                source_error=history_block["source_meta"].get("source_error"),
                attempted_sources=history_block["source_meta"].get("attempted_sources", []),
                extra={
                    "requested_start_date": requested_start_date,
                    "requested_end_date": requested_end_date,
                    "resolved_start_date": latest_specific_date,
                    "resolved_end_date": latest_specific_date,
                    "fallback_mode": "latest_stock_specific_report_date",
                },
            ),
        }

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
            status = block["source_meta"]["source_status"]
            if status in {"ok", "empty"}:
                all_rows.extend(block["items"])
            else:
                failures.append(block["source_meta"])

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

        return {
            "items": filtered_rows,
            "source_meta": self._build_source_meta(
                source=self.PROVIDER_ORDER[0],
                source_status=source_status,
                source_error=source_error,
                attempted_sources=attempted_sources,
                extra={"filter_rule": self._filter_rule_text()},
            ),
        }

    def _build_identity(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "common": {
                "ts_code": record.get("ts_code"),
                "name": record.get("name"),
                "list_date": record.get("list_date"),
                "delist_date": record.get("delist_date"),
            },
            "cn_specific": {
                "symbol": record.get("symbol"),
                "exchange": record.get("exchange"),
                "list_status": record.get("list_status"),
                "area": record.get("area"),
                "industry": record.get("industry"),
                "market": record.get("market"),
            },
            "us_specific": {
                "ts_code": record.get("us_ts_code"),
                "name": record.get("us_name"),
                "enname": record.get("enname"),
                "classify": record.get("classify"),
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

    def _build_capabilities(self, **blocks: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for block_name, block in blocks.items():
            status = block["source_meta"]["source_status"]
            payload[block_name] = {
                "available": status in {"ok", "empty"},
                "status": status,
            }
        return payload

    def _empty_capabilities(
        self,
        *,
        attempted_sources: Sequence[str],
        source_status: str,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for block_name in (*self.CORE_BLOCKS, *self.OPTIONAL_BLOCKS):
            payload[block_name] = {
                "available": False,
                "status": source_status,
                "attempted_sources": list(attempted_sources),
            }
        return payload

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
    def _build_source_meta(
        *,
        source: Optional[str],
        source_status: str,
        source_error: Optional[str],
        attempted_sources: Sequence[str],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = {
            "source": source,
            "source_status": source_status,
            "source_error": source_error,
            "attempted_sources": list(attempted_sources),
        }
        if extra:
            meta.update(extra)
        return meta

    def _empty_block(
        self,
        *,
        attempted_sources: Sequence[str],
        source_status: str,
        source_error: Optional[str],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "items": [],
            "source_meta": self._build_source_meta(
                source=self.PROVIDER_ORDER[0] if self.PROVIDER_ORDER else None,
                source_status=source_status,
                source_error=source_error,
                attempted_sources=attempted_sources,
                extra=extra,
            ),
        }

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
        if priority.get(candidate.get("status"), 0) >= priority.get(current.get("status"), 0):
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
