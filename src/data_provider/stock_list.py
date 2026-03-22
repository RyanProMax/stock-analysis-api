"""
兼容层：旧股票列表服务转发到 SymbolCatalogService。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..services.symbol_catalog_service import symbol_catalog_service


class StockListService:
    """兼容旧调用方的股票列表服务。"""

    @classmethod
    def get_a_stock_list(cls, use_tushare: bool = True) -> List[Dict[str, Any]]:
        return symbol_catalog_service.get_market_snapshot("cn")

    @classmethod
    def get_us_stock_list(cls, use_tushare: bool = True) -> List[Dict[str, Any]]:
        return symbol_catalog_service.get_market_snapshot("us")

    @classmethod
    def get_all_stock_list(cls) -> List[Dict[str, Any]]:
        return symbol_catalog_service.list_symbols()

    @classmethod
    def search_stocks(cls, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        return symbol_catalog_service.search_symbols(keyword, market=market)


__all__ = ["StockListService"]
