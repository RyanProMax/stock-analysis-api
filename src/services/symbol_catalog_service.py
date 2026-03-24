"""
股票主数据目录服务。

统一维护 cn/us symbols 的冷启动、搜索、快照刷新和单股 metadata 补齐。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from ..data_provider.sources.akshare import AkShareDataSource
from ..data_provider.sources.efinance import EfinanceDataSource
from ..data_provider.sources.nasdaq import NasdaqDataSource
from ..data_provider.sources.tushare import TushareDataSource
from ..repositories import MarketDataRepository, market_data_repository


logger = logging.getLogger(__name__)


class SymbolCatalogService:
    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        cn_sources: Optional[Iterable[Any]] = None,
        us_sources: Optional[Iterable[Any]] = None,
    ):
        self.repository = repository or market_data_repository
        self.cn_sources = list(
            cn_sources
            or [
                TushareDataSource.get_instance(),
                EfinanceDataSource.get_instance(),
                AkShareDataSource.get_instance(),
            ]
        )
        self.us_sources = list(
            us_sources
            or [
                TushareDataSource.get_instance(),
                NasdaqDataSource.get_instance(),
            ]
        )

    def list_symbols(
        self,
        market: Optional[str] = None,
        limit: Optional[int] = None,
        refresh_if_empty: bool = True,
    ) -> List[Dict[str, Any]]:
        normalized_market = self._normalize_market(market) if market else None
        cached = self.repository.list_symbols(market=normalized_market, limit=limit)
        if cached or not refresh_if_empty:
            if cached:
                logger.debug(
                    "symbol store hit market=%s count=%s limit=%s",
                    normalized_market or "all",
                    len(cached),
                    limit,
                )
            return cached

        if normalized_market == "cn":
            refreshed = self.refresh_market_snapshot("cn")
            return refreshed[:limit] if limit is not None and limit >= 0 else refreshed
        if normalized_market == "us":
            refreshed = self.refresh_market_snapshot("us")
            return refreshed[:limit] if limit is not None and limit >= 0 else refreshed

        self.refresh_market_snapshot("cn")
        self.refresh_market_snapshot("us")
        return self.repository.list_symbols(limit=limit)

    def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        normalized_market = self._normalize_market(market) if market else None
        results = self.repository.search_symbols(keyword, market=normalized_market)
        if results:
            logger.debug(
                "symbol store hit market=%s keyword=%s count=%s",
                normalized_market or "all",
                keyword,
                len(results),
            )
            return results

        if normalized_market:
            self.refresh_market_snapshot(normalized_market)
        else:
            self.refresh_market_snapshot("cn")
            self.refresh_market_snapshot("us")
        return self.repository.search_symbols(keyword, market=normalized_market)

    def get_market_snapshot(self, market: str) -> List[Dict[str, Any]]:
        return self.list_symbols(market=market, refresh_if_empty=True)

    def refresh_market_snapshot(self, market: str) -> List[Dict[str, Any]]:
        result = self.refresh_market_snapshot_result(market)
        return result["rows"]

    def refresh_market_snapshot_result(self, market: str) -> Dict[str, Any]:
        normalized_market = self._normalize_market(market)
        logger.info("symbol snapshot refresh start market=%s", normalized_market)
        fetch_result = self._fetch_market_snapshot(normalized_market)
        if not fetch_result["success"]:
            logger.warning(
                "symbol snapshot refresh failed market=%s reason=%s source=%s",
                normalized_market,
                fetch_result.get("reason") or "unknown",
                fetch_result.get("source") or "",
            )
            return {
                **fetch_result,
                "rows": self.repository.list_symbols(market=normalized_market),
            }

        fetched = fetch_result["rows"]
        if fetched:
            self.repository.replace_symbols(fetched, market=normalized_market)
        rows = self.repository.list_symbols(market=normalized_market)
        logger.info(
            "symbol snapshot refresh completed market=%s count=%s source=%s partial=%s",
            normalized_market,
            len(rows),
            fetch_result.get("source") or "",
            fetch_result.get("partial", False),
        )
        return {
            **fetch_result,
            "rows": rows,
        }

    def fetch_live_market_snapshot(self, market: str) -> List[Dict[str, Any]]:
        normalized_market = self._normalize_market(market)
        result = self._fetch_market_snapshot(normalized_market)
        return result["rows"] if result["success"] else []

    def resolve_symbol(self, symbol: str, market: Optional[str] = None) -> Optional[Dict[str, Any]]:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            return None

        normalized_market = self._normalize_market(market or normalized_symbol)
        row = self.repository.get_symbol_record(normalized_symbol, market=normalized_market)
        if row is not None:
            if (
                normalized_market == "cn"
                and row.get("market") != "ETF"
                and self._needs_symbol_enrichment(row, normalized_symbol)
            ):
                enriched = TushareDataSource.fetch_cn_stock_basic(normalized_symbol)
                if enriched:
                    merged = dict(row)
                    merged.update({k: v for k, v in enriched.items() if v not in (None, "")})
                    self.repository.upsert_symbols([merged], market=normalized_market)
                    return self.repository.get_symbol_record(normalized_symbol, market=normalized_market)
            return row

        matches = self.search_symbols(normalized_symbol, "美股" if normalized_market == "us" else "A股")
        for candidate in matches:
            if str(candidate.get("symbol") or "").strip().upper() == normalized_symbol:
                return candidate

        if normalized_market == "cn":
            tushare_row = TushareDataSource.fetch_cn_stock_basic(normalized_symbol)
            if tushare_row:
                self.repository.upsert_symbols([tushare_row], market="cn")
                return self.repository.get_symbol_record(normalized_symbol, market="cn")

        fallback = {
            "symbol": normalized_symbol,
            "ts_code": self._default_ts_code(normalized_symbol, normalized_market),
            "name": normalized_symbol,
            "area": "美国" if normalized_market == "us" else None,
            "industry": None,
            "market": "美股" if normalized_market == "us" else "A股",
            "exchange": "NASDAQ" if normalized_market == "us" else None,
            "list_date": None,
        }
        self.repository.upsert_symbols([fallback], market=normalized_market)
        return self.repository.get_symbol_record(normalized_symbol, market=normalized_market)

    def get_stock_info(self, symbol: str) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "").strip().upper()
        market = self._normalize_market(normalized_symbol)
        row = self.resolve_symbol(normalized_symbol, market=market)
        if row is None:
            return {"name": normalized_symbol, "industry": ""}
        return {
            "name": row.get("name") or normalized_symbol,
            "industry": row.get("industry") or "",
            "market": market,
        }

    def _fetch_market_snapshot(self, market: str) -> Dict[str, Any]:
        if market == "cn":
            return self._fetch_cn_market_snapshot()

        rows, source_name = self._fetch_rows_from_sources(
            self.us_sources,
            market_label="美股",
            getter_name="get_us_stocks",
        )
        return {
            "success": bool(rows),
            "rows": rows,
            "source": source_name,
            "partial": False,
            "reason": None if rows else "us_snapshot_unavailable",
        }

    def _fetch_cn_market_snapshot(self) -> Dict[str, Any]:
        stock_rows, stock_source = self._fetch_rows_from_sources(
            self.cn_sources,
            market_label="A股",
            getter_name="get_a_stocks",
        )
        if not stock_rows:
            return {
                "success": False,
                "rows": [],
                "source": stock_source,
                "partial": False,
                "reason": "cn_equity_snapshot_unavailable",
            }

        etf_rows, etf_source, etf_success = self._fetch_cn_etf_rows()
        merged_rows = self._merge_cn_snapshot_rows(stock_rows, etf_rows)
        sources = [source for source in (stock_source, etf_source) if source]
        if not etf_success:
            logger.warning(
                "symbol snapshot refresh partial market=cn reason=cn_etf_snapshot_unavailable source=%s",
                etf_source or "Tushare",
            )
        return {
            "success": True,
            "rows": merged_rows,
            "source": ",".join(sources),
            "partial": not etf_success,
            "reason": None,
        }

    def _fetch_cn_etf_rows(self) -> tuple[List[Dict[str, Any]], str, bool]:
        tushare_source = next(
            (
                source
                for source in self.cn_sources
                if getattr(source, "SOURCE_NAME", "") == TushareDataSource.SOURCE_NAME
                and hasattr(source, "get_cn_etfs")
            ),
            None,
        )
        if tushare_source is None:
            return [], "", False
        if hasattr(tushare_source, "is_available") and not tushare_source.is_available("A股"):
            return [], getattr(tushare_source, "SOURCE_NAME", ""), False

        rows = tushare_source.get_cn_etfs()
        return rows, getattr(tushare_source, "SOURCE_NAME", ""), bool(rows)

    @staticmethod
    def _merge_cn_snapshot_rows(
        stock_rows: List[Dict[str, Any]],
        etf_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for row in stock_rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol:
                merged[symbol] = dict(row)
        for row in etf_rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol and symbol not in merged:
                merged[symbol] = dict(row)
        return list(merged.values())

    @staticmethod
    def _fetch_rows_from_sources(
        sources: Iterable[Any],
        *,
        market_label: str,
        getter_name: str,
    ) -> tuple[List[Dict[str, Any]], str]:
        for source in sources:
            if not hasattr(source, "is_available") or not source.is_available(market_label):
                continue
            getter = getattr(source, getter_name, None)
            if getter is None:
                continue
            rows = getter()
            if rows:
                return rows, getattr(source, "SOURCE_NAME", "")
        return [], ""

    @staticmethod
    def _needs_symbol_enrichment(row: Dict[str, Any], symbol: str) -> bool:
        name = str(row.get("name") or "").strip().upper()
        return not name or name == symbol

    @staticmethod
    def _normalize_market(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"us", "美股", "nasdaq", "nyse", "amex"}:
            return "us"
        return "cn"

    @staticmethod
    def _default_ts_code(symbol: str, market: str) -> str:
        if market == "us":
            return f"{symbol}.US"
        if symbol.startswith(("4", "8", "92")):
            return f"{symbol}.BJ"
        return f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ"


symbol_catalog_service = SymbolCatalogService()
