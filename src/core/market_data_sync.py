"""
A 股日线 SQLite 仓同步服务
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import pandas as pd

from ..data_provider import StockListService
from ..data_provider.sources.akshare import AkShareDataSource
from ..data_provider.sources.efinance import EfinanceDataSource
from ..data_provider.sources.tushare import TushareDataSource
from ..storage import MarketDataStorage, market_data_storage


class DailyWarehouseSyncService:
    def __init__(
        self,
        warehouse: Optional[MarketDataStorage] = None,
        cn_sources: Optional[Iterable[Any]] = None,
    ):
        self.warehouse = warehouse or market_data_storage
        self.cn_sources = list(
            cn_sources
            or [
                TushareDataSource.get_instance(),
                AkShareDataSource.get_instance(),
                EfinanceDataSource.get_instance(),
            ]
        )

    def sync_a_share_symbols(self, refresh: bool = False) -> int:
        stocks = StockListService.get_a_stock_list(refresh=refresh)
        return self.warehouse.upsert_symbols(stocks)

    def backfill_a_share_history(self, years: int = 10, refresh_symbols: bool = False) -> dict:
        stocks = StockListService.get_a_stock_list(refresh=refresh_symbols)
        return self._sync_a_share(stocks, mode=f"backfill_{years}y", years=years)

    def refresh_recent_a_share_daily(self, days: int = 30, refresh_symbols: bool = False) -> dict:
        stocks = StockListService.get_a_stock_list(refresh=refresh_symbols)
        return self._sync_a_share(stocks, mode=f"refresh_{days}d", days=days)

    def _sync_a_share(
        self,
        stocks: list[dict],
        mode: str,
        years: Optional[int] = None,
        days: Optional[int] = None,
    ) -> dict:
        self.warehouse.upsert_symbols(stocks)
        run_id = self.warehouse.start_sync_run(
            source="A_SHARE_MULTI_SOURCE",
            mode=mode,
            total_symbols=len(stocks),
        )
        success_count = 0
        failure_count = 0
        errors: list[str] = []

        for stock in stocks:
            symbol = str(stock.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            try:
                result = self._sync_single_symbol(symbol, years=years, days=days)
                if result["rows"] > 0:
                    success_count += 1
                else:
                    failure_count += 1
                    errors.append(f"{symbol}:empty")
            except Exception as exc:
                failure_count += 1
                errors.append(f"{symbol}:{type(exc).__name__}")

        status = "completed" if failure_count == 0 else "partial"
        self.warehouse.finish_sync_run(
            run_id=run_id,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            error_summary="; ".join(errors[:20]) if errors else None,
        )
        return {
            "run_id": run_id,
            "mode": mode,
            "success_count": success_count,
            "failure_count": failure_count,
            "error_summary": errors[:20],
        }

    def _sync_single_symbol(
        self,
        symbol: str,
        years: Optional[int] = None,
        days: Optional[int] = None,
    ) -> dict:
        selected_df: Optional[pd.DataFrame] = None
        selected_source = ""

        for source in self.cn_sources:
            if not hasattr(source, "get_daily_data") or not source.is_available("A股"):
                continue
            daily_df = source.get_daily_data(symbol)
            if daily_df is None or daily_df.empty:
                continue
            selected_df = self._slice_daily_window(daily_df, years=years, days=days)
            if selected_df is None or selected_df.empty:
                continue
            selected_source = f"CN_{source.SOURCE_NAME}"
            break

        if selected_df is None or selected_df.empty:
            return {"symbol": symbol, "rows": 0, "source": None}

        self.warehouse.upsert_daily_bars(symbol, selected_df, selected_source)
        return {"symbol": symbol, "rows": len(selected_df), "source": selected_source}

    @staticmethod
    def _slice_daily_window(
        daily_df: pd.DataFrame,
        years: Optional[int] = None,
        days: Optional[int] = None,
    ) -> pd.DataFrame:
        if daily_df is None or daily_df.empty or "date" not in daily_df.columns:
            return daily_df

        df = daily_df.copy()
        df["date"] = pd.to_datetime(df["date"])
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

        if years is not None and years > 0:
            start = now_naive - timedelta(days=years * 365)
            df = df[df["date"] >= pd.Timestamp(start)]
        if days is not None and days > 0:
            start = now_naive - timedelta(days=days)
            df = df[df["date"] >= pd.Timestamp(start)]

        return df.sort_values("date", ascending=True).reset_index(drop=True)


daily_warehouse_sync_service = DailyWarehouseSyncService()
