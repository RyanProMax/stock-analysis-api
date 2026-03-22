"""
统一行情仓同步服务
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import pandas as pd

from ..data_provider import StockListService
from ..data_provider.sources.akshare import AkShareDataSource
from ..data_provider.sources.efinance import EfinanceDataSource
from ..data_provider.sources.nasdaq import NasdaqDataSource
from ..data_provider.sources.tushare import TushareDataSource
from ..data_provider.sources.yfinance import YfinanceDataSource
from ..storage import MarketDataStorage, market_data_storage


class DailyWarehouseSyncService:
    """单股 / 全市场行情同步服务。"""

    def __init__(
        self,
        warehouse: Optional[MarketDataStorage] = None,
        cn_daily_sources: Optional[Iterable[Any]] = None,
        us_daily_sources: Optional[Iterable[Any]] = None,
    ):
        self.warehouse = warehouse or market_data_storage
        self.cn_daily_sources = list(
            cn_daily_sources
            or [
                TushareDataSource.get_instance(),
                AkShareDataSource.get_instance(),
                EfinanceDataSource.get_instance(),
            ]
        )
        self.us_daily_sources = list(
            us_daily_sources
            or [
                YfinanceDataSource.get_instance(),
                AkShareDataSource.get_instance(),
            ]
        )

    def sync_market_data(
        self,
        market: str,
        scope: str,
        symbol: Optional[str] = None,
        days: Optional[int] = None,
        years: Optional[int] = None,
    ) -> dict:
        normalized_market = self._normalize_market(market)
        if days and years:
            raise ValueError("`--days` 和 `--years` 只能二选一")
        if scope == "symbol" and not symbol:
            raise ValueError("`scope=symbol` 时必须提供 `--symbol`")

        stocks = self._resolve_stocks(normalized_market, scope, symbol)
        self.warehouse.upsert_symbols(stocks, market=normalized_market)

        mode = self._build_mode(normalized_market, scope, symbol, days, years)
        run_id = self.warehouse.start_sync_run(
            source=f"{normalized_market.upper()}_MULTI_SOURCE",
            mode=mode,
            total_symbols=len(stocks),
        )
        success_count = 0
        failure_count = 0
        errors: list[str] = []

        for stock in stocks:
            current_symbol = str(stock.get("symbol") or "").strip().upper()
            if not current_symbol:
                continue
            try:
                result = self._sync_single_symbol(
                    symbol=current_symbol,
                    market=normalized_market,
                    ts_code=stock.get("ts_code"),
                    days=days,
                    years=years,
                )
                if result["rows"] > 0:
                    success_count += 1
                else:
                    failure_count += 1
                    errors.append(f"{current_symbol}:empty")
            except Exception as exc:
                failure_count += 1
                errors.append(f"{current_symbol}:{type(exc).__name__}")

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
            "market": normalized_market,
            "scope": scope,
            "symbol": symbol.upper() if symbol else None,
            "days": days,
            "years": years,
            "success_count": success_count,
            "failure_count": failure_count,
            "error_summary": errors[:20],
        }

    def _resolve_stocks(self, market: str, scope: str, symbol: Optional[str]) -> list[dict]:
        if scope == "all":
            return (
                StockListService.get_a_stock_list()
                if market == "cn"
                else StockListService.get_us_stock_list()
            )

        normalized_symbol = str(symbol or "").strip().upper()
        candidates = StockListService.search_stocks(
            normalized_symbol,
            "A股" if market == "cn" else "美股",
        )
        for row in candidates:
            if str(row.get("symbol") or "").strip().upper() == normalized_symbol:
                if market == "cn" and self._needs_symbol_enrichment(row, normalized_symbol):
                    tushare_row = TushareDataSource.fetch_cn_stock_basic(normalized_symbol)
                    if tushare_row is not None:
                        enriched = dict(row)
                        enriched.update({k: v for k, v in tushare_row.items() if v not in (None, "")})
                        return [enriched]
                return [row]

        if market == "cn":
            tushare_row = TushareDataSource.fetch_cn_stock_basic(normalized_symbol)
            if tushare_row is not None:
                return [tushare_row]

        return [
            {
                "symbol": normalized_symbol,
                "ts_code": self._default_ts_code(normalized_symbol, market),
                "name": normalized_symbol,
                "area": "美国" if market == "us" else None,
                "industry": None,
                "market": "美股" if market == "us" else "A股",
                "exchange": "NASDAQ" if market == "us" else None,
                "list_date": None,
            }
        ]

    @staticmethod
    def _needs_symbol_enrichment(row: dict, symbol: str) -> bool:
        name = str(row.get("name") or "").strip().upper()
        if not name:
            return True
        if name == symbol:
            return True
        return False

    def _sync_single_symbol(
        self,
        symbol: str,
        market: str,
        ts_code: Optional[str] = None,
        days: Optional[int] = None,
        years: Optional[int] = None,
    ) -> dict:
        selected_df: Optional[pd.DataFrame] = None
        selected_source = ""
        sources = self.cn_daily_sources if market == "cn" else self.us_daily_sources
        start_date = self._compute_start_date(days=days, years=years)

        for source in sources:
            if not hasattr(source, "is_available"):
                continue
            market_label = "A股" if market == "cn" else "美股"
            if not source.is_available(market_label):
                continue

            daily_df = self._fetch_source_daily(source, symbol=symbol, market=market, start_date=start_date)
            if daily_df is None or daily_df.empty:
                continue

            selected_df = self._slice_daily_window(daily_df, start_date=start_date)
            if selected_df is None or selected_df.empty:
                continue

            selected_source = f"{market.upper()}_{source.SOURCE_NAME}"
            break

        if selected_df is None or selected_df.empty:
            return {"symbol": symbol, "rows": 0, "source": None}

        self.warehouse.upsert_daily_bars(
            symbol=symbol,
            daily_df=selected_df,
            source=selected_source,
            market=market,
            ts_code=ts_code,
        )
        return {"symbol": symbol, "rows": len(selected_df), "source": selected_source}

    def _fetch_source_daily(
        self,
        source: Any,
        symbol: str,
        market: str,
        start_date: Optional[str],
    ) -> Optional[pd.DataFrame]:
        if isinstance(source, TushareDataSource):
            return TushareDataSource.fetch_daily_with_extras(
                symbol=symbol,
                market=market,
                start_date=start_date,
            )

        daily_df = source.get_daily_data(symbol)
        if daily_df is None or daily_df.empty:
            return None
        df = daily_df.copy()
        for column in ("ma5", "ma10", "ma20"):
            if column in df.columns:
                df.drop(columns=[column], inplace=True)
        return df

    @staticmethod
    def _slice_daily_window(
        daily_df: pd.DataFrame,
        start_date: Optional[str],
    ) -> pd.DataFrame:
        if daily_df is None or daily_df.empty:
            return daily_df

        df = daily_df.copy()
        date_col = "trade_date" if "trade_date" in df.columns else "date"
        if date_col not in df.columns:
            return df

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        if start_date:
            start = pd.Timestamp(start_date)
            df = df[df[date_col] >= start]

        return df.sort_values(date_col, ascending=True).reset_index(drop=True)

    @staticmethod
    def _compute_start_date(days: Optional[int], years: Optional[int]) -> Optional[str]:
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if years is not None and years > 0:
            return (now_naive - timedelta(days=years * 365)).strftime("%Y-%m-%d")
        if days is not None and days > 0:
            return (now_naive - timedelta(days=days)).strftime("%Y-%m-%d")
        return None

    @staticmethod
    def _normalize_market(market: str) -> str:
        return "us" if str(market).strip().lower() == "us" else "cn"

    @staticmethod
    def _build_mode(
        market: str,
        scope: str,
        symbol: Optional[str],
        days: Optional[int],
        years: Optional[int],
    ) -> str:
        if scope == "symbol":
            if years is not None:
                return f"{market}_symbol_{symbol}_{years}y"
            if days is not None:
                return f"{market}_symbol_{symbol}_{days}d"
            return f"{market}_symbol_{symbol}_30d"
        if years is not None:
            return f"{market}_all_{years}y"
        if days is not None:
            return f"{market}_all_{days}d"
        return f"{market}_all_30d"

    @staticmethod
    def _default_ts_code(symbol: str, market: str) -> str:
        if market == "us":
            return f"{symbol}.US"
        return f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ"


daily_warehouse_sync_service = DailyWarehouseSyncService()
