"""
本地行情仓读取服务

对 A 股 / 美股优先走 SQLite 日线仓，缺失或过旧时回退到外部数据源并回写仓库。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from ..data_provider import data_manager, StockListService
from ..storage import MarketDataStorage, market_data_storage


class DailyMarketDataService:
    FRESHNESS_DAYS = 7
    REFRESH_BACKTRACK_DAYS = 30
    COLD_START_DAYS = 400

    def __init__(self, warehouse: Optional[MarketDataStorage] = None):
        self.warehouse = warehouse or market_data_storage

    def get_stock_daily(
        self,
        symbol: str,
    ) -> Tuple[Optional[pd.DataFrame], str, str]:
        normalized = str(symbol).strip().upper()
        market = "us" if any(ch.isalpha() for ch in normalized) else "cn"

        local_df, local_name, latest_trade_date = self._load_from_warehouse(normalized, market)
        if local_df is not None and not local_df.empty and self._is_fresh(latest_trade_date):
            return local_df, local_name or normalized, f"{market.upper()}_SQLiteDailyWarehouse"

        fetched_df, stock_name, data_source = data_manager.get_stock_daily(normalized)
        if fetched_df is None or fetched_df.empty:
            return local_df, (local_name or stock_name or normalized), data_source

        persist_df = self._slice_persist_window(fetched_df, latest_trade_date)
        if persist_df is not None and not persist_df.empty:
            self._persist_to_warehouse(
                symbol=normalized,
                market=market,
                stock_name=stock_name,
                data_source=data_source,
                daily_df=persist_df,
            )

        return fetched_df, stock_name or local_name or normalized, data_source

    def _load_from_warehouse(
        self,
        symbol: str,
        market: str,
    ) -> Tuple[Optional[pd.DataFrame], Optional[str], Optional[str]]:
        daily_df = self.warehouse.load_daily_bars(symbol, market=market)
        latest_trade_date = self.warehouse.get_latest_trade_date(symbol, market=market)
        if daily_df is None or daily_df.empty:
            return None, None, latest_trade_date
        symbol_row = self.warehouse.get_symbol_record(symbol, market=market)
        stock_name = symbol_row.get("name") if isinstance(symbol_row, dict) else None
        return daily_df, stock_name, latest_trade_date

    def _persist_to_warehouse(
        self,
        symbol: str,
        market: str,
        stock_name: str,
        data_source: str,
        daily_df: pd.DataFrame,
    ) -> None:
        symbol_record = self._lookup_symbol_record(symbol, market)
        if symbol_record is None:
            symbol_record = {
                "symbol": symbol,
                "ts_code": self._default_ts_code(symbol, market),
                "name": stock_name or symbol,
                "market": "美股" if market == "us" else "A股",
                "exchange": "NASDAQ" if market == "us" else None,
                "list_date": None,
            }
        else:
            symbol_record = dict(symbol_record)
            symbol_record["name"] = stock_name or symbol_record.get("name") or symbol

        self.warehouse.upsert_symbols([symbol_record], market=market)
        self.warehouse.upsert_daily_bars(
            symbol=symbol,
            market=market,
            daily_df=daily_df,
            source=data_source or f"{market.upper()}_provider",
            ts_code=symbol_record.get("ts_code"),
        )

    @staticmethod
    def _lookup_symbol_record(symbol: str, market: str) -> Optional[Dict[str, Any]]:
        market_label = "美股" if market == "us" else "A股"
        candidates = StockListService.search_stocks(symbol, market_label)
        for row in candidates:
            if str(row.get("symbol") or "").strip().upper() == symbol:
                return row
        return None

    def _slice_persist_window(
        self,
        daily_df: pd.DataFrame,
        latest_trade_date: Optional[str],
    ) -> pd.DataFrame:
        if daily_df is None or daily_df.empty:
            return daily_df

        df = daily_df.copy()
        date_col = "trade_date" if "trade_date" in df.columns else "date"
        if date_col not in df.columns:
            return df

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).sort_values(date_col, ascending=True).reset_index(drop=True)
        if df.empty:
            return df

        if latest_trade_date:
            start = pd.Timestamp(latest_trade_date) - timedelta(days=self.REFRESH_BACKTRACK_DAYS)
        else:
            start = df[date_col].max() - timedelta(days=self.COLD_START_DAYS)
        return df[df[date_col] >= start].reset_index(drop=True)

    def _is_fresh(self, latest_trade_date: Optional[str]) -> bool:
        if not latest_trade_date:
            return False
        try:
            latest = pd.Timestamp(latest_trade_date)
        except Exception:
            return False
        return latest >= pd.Timestamp(
            datetime.now(timezone.utc).date() - timedelta(days=self.FRESHNESS_DAYS)
        )

    @staticmethod
    def _default_ts_code(symbol: str, market: str) -> str:
        if market == "us":
            return f"{symbol}.US"
        return f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ"


daily_market_data_service = DailyMarketDataService()
