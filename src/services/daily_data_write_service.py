"""
统一行情仓写服务。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

import pandas as pd

from ..data_provider.sources.akshare import AkShareDataSource
from ..data_provider.sources.efinance import EfinanceDataSource
from ..data_provider.sources.tushare import TushareDataSource
from ..data_provider.sources.yfinance import YfinanceDataSource
from ..repositories import MarketDataRepository, market_data_repository
from .symbol_catalog_service import SymbolCatalogService, symbol_catalog_service


class DailyDataWriteService:
    """单股 / 全市场行情写入服务。"""

    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        symbol_catalog: Optional[SymbolCatalogService] = None,
        cn_daily_sources: Optional[Iterable[Any]] = None,
        us_daily_sources: Optional[Iterable[Any]] = None,
    ):
        self.repository = repository or market_data_repository
        self.symbol_catalog = symbol_catalog or symbol_catalog_service
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
                TushareDataSource.get_instance(),
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
        start_date: Optional[str] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        normalized_market = self._normalize_market(market)
        self._validate_window(days=days, years=years, start_date=start_date)
        if scope == "symbol" and not symbol:
            raise ValueError("`scope=symbol` 时必须提供 `--symbol`")

        if scope == "all":
            stocks = self.symbol_catalog.refresh_market_snapshot(normalized_market)
        else:
            resolved = self.symbol_catalog.resolve_symbol(str(symbol or "").strip().upper(), market=normalized_market)
            stocks = [resolved] if resolved else []

        mode = self._build_mode(normalized_market, scope, symbol, days, years, start_date)
        run_id = self.repository.start_sync_run(
            source=f"{normalized_market.upper()}_MULTI_SOURCE",
            mode=mode,
            total_symbols=len(stocks),
        )
        success_count = 0
        failure_count = 0
        errors: list[str] = []

        for stock in stocks:
            current_symbol = str((stock or {}).get("symbol") or "").strip().upper()
            if not current_symbol:
                continue
            item_status = "empty"
            item_source = None
            try:
                result = self.sync_symbol_daily(
                    symbol=current_symbol,
                    market=normalized_market,
                    ts_code=(stock or {}).get("ts_code"),
                    start_date=start_date,
                    days=days,
                    years=years,
                )
                if result["rows"] > 0:
                    success_count += 1
                    item_status = "success"
                    item_source = result.get("source")
                else:
                    failure_count += 1
                    errors.append(f"{current_symbol}:empty")
                    item_status = "empty"
            except Exception as exc:
                failure_count += 1
                errors.append(f"{current_symbol}:{type(exc).__name__}")
                item_status = "error"

            processed_count = success_count + failure_count
            self.repository.update_sync_run_progress(
                run_id=run_id,
                success_count=success_count,
                failure_count=failure_count,
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "run_id": run_id,
                        "market": normalized_market,
                        "scope": scope,
                        "symbol": current_symbol,
                        "processed_count": processed_count,
                        "total_symbols": len(stocks),
                        "success_count": success_count,
                        "failure_count": failure_count,
                        "item_status": item_status,
                        "source": item_source,
                    }
                )

        status = "completed" if failure_count == 0 else "partial"
        self.repository.finish_sync_run(
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
            "start_date": start_date,
            "processed_count": success_count + failure_count,
            "total_symbols": len(stocks),
            "success_count": success_count,
            "failure_count": failure_count,
            "error_summary": errors[:20],
        }

    def sync_symbol_daily(
        self,
        symbol: str,
        market: str,
        ts_code: Optional[str] = None,
        days: Optional[int] = None,
        years: Optional[int] = None,
        start_date: Optional[str] = None,
    ) -> dict:
        normalized_symbol = str(symbol).strip().upper()
        normalized_market = self._normalize_market(market)
        self._validate_window(days=days, years=years, start_date=start_date)
        symbol_record = self.symbol_catalog.resolve_symbol(normalized_symbol, market=normalized_market)
        if symbol_record:
            self.repository.upsert_symbols([symbol_record], market=normalized_market)

        selected_df: Optional[pd.DataFrame] = None
        selected_source = ""
        sources = self.cn_daily_sources if normalized_market == "cn" else self.us_daily_sources
        effective_start_date = start_date or self._compute_start_date(days=days, years=years)

        for source in sources:
            market_label = "A股" if normalized_market == "cn" else "美股"
            if not hasattr(source, "is_available") or not source.is_available(market_label):
                continue

            daily_df = self._fetch_source_daily(
                source,
                symbol=normalized_symbol,
                market=normalized_market,
                start_date=effective_start_date,
            )
            if daily_df is None or daily_df.empty:
                continue

            selected_df = self._slice_daily_window(daily_df, start_date=effective_start_date)
            if selected_df is None or selected_df.empty:
                continue

            selected_source = f"{normalized_market.upper()}_{source.SOURCE_NAME}"
            break

        if selected_df is None or selected_df.empty:
            return {"symbol": normalized_symbol, "rows": 0, "source": None}

        self.repository.upsert_daily_bars(
            symbol=normalized_symbol,
            daily_df=selected_df,
            source=selected_source,
            market=normalized_market,
            ts_code=ts_code or (symbol_record or {}).get("ts_code"),
        )
        return {"symbol": normalized_symbol, "rows": len(selected_df), "source": selected_source}

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
            df = df[df[date_col] >= pd.Timestamp(start_date)]
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
    def _validate_window(
        *,
        days: Optional[int],
        years: Optional[int],
        start_date: Optional[str],
    ) -> None:
        if sum(value is not None for value in (days, years, start_date)) > 1:
            raise ValueError("`--days`、`--years` 和 `--start-date` 只能三选一")

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
        start_date: Optional[str],
    ) -> str:
        if scope == "symbol":
            if start_date:
                return f"{market}_symbol_{symbol}_since_{start_date}"
            if years is not None:
                return f"{market}_symbol_{symbol}_{years}y"
            if days is not None:
                return f"{market}_symbol_{symbol}_{days}d"
            return f"{market}_symbol_{symbol}_30d"
        if start_date:
            return f"{market}_all_since_{start_date}"
        if years is not None:
            return f"{market}_all_{years}y"
        if days is not None:
            return f"{market}_all_{days}d"
        return f"{market}_all_30d"


daily_data_write_service = DailyDataWriteService()
