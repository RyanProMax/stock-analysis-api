"""
股票主数据目录服务。

统一维护 cn/us symbols 的冷启动、搜索、快照刷新和单股 metadata 补齐。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..data_provider.sources.akshare import AkShareDataSource
from ..data_provider.sources.efinance import EfinanceDataSource
from ..data_provider.sources.nasdaq import NasdaqDataSource
from ..data_provider.sources.tushare import TushareDataSource
from ..repositories import MarketDataRepository, market_data_repository


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
        normalized_market = self._normalize_market(market)
        fetched = self._fetch_market_snapshot(normalized_market)
        if fetched:
            self.repository.replace_symbols(fetched, market=normalized_market)
        return self.repository.list_symbols(market=normalized_market)

    def fetch_live_market_snapshot(self, market: str) -> List[Dict[str, Any]]:
        normalized_market = self._normalize_market(market)
        return self._fetch_market_snapshot(normalized_market)

    def resolve_symbol(self, symbol: str, market: Optional[str] = None) -> Optional[Dict[str, Any]]:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            return None

        normalized_market = self._normalize_market(market or normalized_symbol)
        row = self.repository.get_symbol_record(normalized_symbol, market=normalized_market)
        if row is not None:
            if normalized_market == "cn" and self._needs_symbol_enrichment(row, normalized_symbol):
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

    def _fetch_market_snapshot(self, market: str) -> List[Dict[str, Any]]:
        market_label = "美股" if market == "us" else "A股"
        sources = self.us_sources if market == "us" else self.cn_sources
        getter_name = "get_us_stocks" if market == "us" else "get_a_stocks"

        for source in sources:
            if not hasattr(source, "is_available") or not source.is_available(market_label):
                continue
            getter = getattr(source, getter_name, None)
            if getter is None:
                continue
            rows = getter()
            if rows:
                return rows
        return []

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
