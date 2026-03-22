"""
本地行情仓读取服务

对 A 股优先走 SQLite 日线仓，缺失时回退到外部数据源并回写仓库。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd

from ..data_provider import data_manager, StockListService
from ..storage import MarketDataStorage, market_data_storage


class DailyMarketDataService:
    def __init__(self, warehouse: Optional[MarketDataStorage] = None):
        self.warehouse = warehouse or market_data_storage

    def get_stock_daily(
        self,
        symbol: str,
        refresh: bool = False,
    ) -> Tuple[Optional[pd.DataFrame], str, str]:
        normalized = str(symbol).strip().upper()
        market = "us" if any(ch.isalpha() for ch in normalized) else "cn"

        if market == "cn" and not refresh:
            local_df, local_name = self._load_cn_from_warehouse(normalized)
            if local_df is not None and not local_df.empty:
                return local_df, local_name or normalized, "CN_SQLiteDailyWarehouse"

        df, stock_name, data_source = data_manager.get_stock_daily(normalized)
        if market == "cn" and df is not None and not df.empty:
            self._persist_cn_to_warehouse(
                symbol=normalized,
                stock_name=stock_name,
                data_source=data_source,
                daily_df=df,
            )
        return df, stock_name, data_source

    def _load_cn_from_warehouse(self, symbol: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        daily_df = self.warehouse.load_daily_bars(symbol)
        if daily_df is None or daily_df.empty:
            return None, None
        symbol_row = self.warehouse.get_symbol_record(symbol)
        stock_name = symbol_row.get("name") if isinstance(symbol_row, dict) else None
        return daily_df, stock_name

    def _persist_cn_to_warehouse(
        self,
        symbol: str,
        stock_name: str,
        data_source: str,
        daily_df: pd.DataFrame,
    ) -> None:
        symbol_record = self._lookup_cn_symbol_record(symbol)
        if symbol_record is None:
            symbol_record = {
                "symbol": symbol,
                "ts_code": f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ",
                "name": stock_name or symbol,
                "market": "cn",
                "list_date": None,
            }
        else:
            symbol_record = dict(symbol_record)
            symbol_record["name"] = stock_name or symbol_record.get("name") or symbol

        self.warehouse.upsert_symbols([symbol_record])
        self.warehouse.upsert_daily_bars(symbol, daily_df, data_source or "CN_provider")

    @staticmethod
    def _lookup_cn_symbol_record(symbol: str) -> Optional[Dict[str, Any]]:
        candidates = StockListService.search_stocks(symbol, "A股")
        for row in candidates:
            if str(row.get("symbol") or "").strip().upper() == symbol:
                return row
        return None


daily_market_data_service = DailyMarketDataService()

