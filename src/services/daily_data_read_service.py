"""
本地行情仓读服务。

优先读取 SQLite 日线仓，缺失或过旧时触发写服务补数并回写。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import pandas as pd

from ..data_provider.base import BaseStockDataSource
from ..data_provider.manager import data_manager
from ..repositories import MarketDataRepository, market_data_repository
from .symbol_catalog_service import SymbolCatalogService, symbol_catalog_service


class DailyDataReadService:
    FRESHNESS_DAYS = 7
    REFRESH_BACKTRACK_DAYS = 30
    COLD_START_DAYS = 400

    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        symbol_catalog: Optional[SymbolCatalogService] = None,
        write_service: Optional["DailyDataWriteService"] = None,
    ):
        self.repository = repository or market_data_repository
        self.symbol_catalog = symbol_catalog or symbol_catalog_service
        self.write_service = write_service

    def get_stock_daily(self, symbol: str) -> Tuple[Optional[pd.DataFrame], str, str]:
        normalized = str(symbol).strip().upper()
        market = "us" if any(ch.isalpha() for ch in normalized) else "cn"

        local_df, local_name, latest_trade_date = self._load_from_repository(normalized, market)
        if local_df is not None and not local_df.empty and self._is_fresh(latest_trade_date):
            return local_df, local_name or normalized, f"{market.upper()}_SQLiteDailyWarehouse"

        write_service = self._get_write_service()
        if latest_trade_date:
            start_date = (
                pd.Timestamp(latest_trade_date) - timedelta(days=self.REFRESH_BACKTRACK_DAYS)
            ).strftime("%Y-%m-%d")
        else:
            start_date = (
                datetime.now(timezone.utc).date() - timedelta(days=self.COLD_START_DAYS)
            ).strftime("%Y-%m-%d")

        write_result = write_service.sync_symbol_daily(
            symbol=normalized,
            market=market,
            start_date=start_date,
        )

        refreshed_df, refreshed_name, _ = self._load_from_repository(normalized, market)
        if refreshed_df is not None and not refreshed_df.empty:
            source = write_result.get("source") or f"{market.upper()}_SQLiteDailyWarehouse"
            return refreshed_df, refreshed_name or local_name or normalized, source

        fetched_df, stock_name, data_source = data_manager.get_stock_daily(normalized)
        if fetched_df is None or fetched_df.empty:
            return local_df, (local_name or stock_name or normalized), data_source

        persist_df = self._slice_persist_window(fetched_df, latest_trade_date)
        if persist_df is not None and not persist_df.empty:
            symbol_record = self.symbol_catalog.resolve_symbol(normalized, market=market)
            self.repository.upsert_daily_bars(
                symbol=normalized,
                market=market,
                daily_df=persist_df,
                source=data_source or f"{market.upper()}_provider",
                ts_code=(symbol_record or {}).get("ts_code"),
            )

        normalized_df = self._normalize_for_consumers(fetched_df)
        return normalized_df, stock_name or local_name or normalized, data_source

    def _load_from_repository(
        self,
        symbol: str,
        market: str,
    ) -> Tuple[Optional[pd.DataFrame], Optional[str], Optional[str]]:
        daily_df = self.repository.load_daily_bars(symbol, market=market)
        latest_trade_date = self.repository.get_latest_trade_date(symbol, market=market)
        if daily_df is None or daily_df.empty:
            return None, None, latest_trade_date

        symbol_row = self.repository.get_symbol_record(symbol, market=market)
        stock_name = symbol_row.get("name") if isinstance(symbol_row, dict) else None
        return self._normalize_for_consumers(daily_df), stock_name, latest_trade_date

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

        df[date_col] = BaseStockDataSource._normalize_datetime_series(df[date_col])
        df = df.dropna(subset=[date_col]).sort_values(date_col, ascending=True).reset_index(drop=True)
        if df.empty:
            return df

        if latest_trade_date:
            start = pd.Timestamp(latest_trade_date) - timedelta(days=self.REFRESH_BACKTRACK_DAYS)
        else:
            start = df[date_col].max() - timedelta(days=self.COLD_START_DAYS)
        return df[df[date_col] >= start].reset_index(drop=True)

    def _normalize_for_consumers(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        if daily_df is None or daily_df.empty:
            return daily_df

        normalized = BaseStockDataSource._clean_daily(daily_df.copy())
        return BaseStockDataSource._calculate_indicators(normalized)

    def _get_write_service(self) -> "DailyDataWriteService":
        if self.write_service is None:
            from .daily_data_write_service import daily_data_write_service

            self.write_service = daily_data_write_service
        return self.write_service

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


daily_data_read_service = DailyDataReadService()
