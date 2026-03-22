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

        effective_start_date = start_date or self._compute_start_date(days=days, years=years)
        requested_end_date = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        target_start_trade_date, target_latest_trade_date = self._resolve_trade_window(
            normalized_market,
            effective_start_date,
            requested_end_date,
        )
        mode = self._build_mode(normalized_market, scope, symbol, days, years, start_date)
        latest_run = self.repository.get_latest_sync_run(mode)

        if scope == "all":
            live_snapshot = self.symbol_catalog.fetch_live_market_snapshot(normalized_market)
            universe_source = f"{normalized_market.upper()}_TushareListedSnapshot"
            current_snapshot = self.repository.list_symbols(market=normalized_market)
            live_symbols = {str(row.get("symbol") or "").strip().upper() for row in live_snapshot}
            current_symbols = {str(row.get("symbol") or "").strip().upper() for row in current_snapshot}
            if live_snapshot and live_symbols != current_symbols:
                self.repository.replace_symbols(live_snapshot, market=normalized_market)
            stocks = self.repository.list_symbols(market=normalized_market)
        else:
            universe_source = "symbol_request"
            resolved = self.symbol_catalog.resolve_symbol(str(symbol or "").strip().upper(), market=normalized_market)
            stocks = [resolved] if resolved else []
            if resolved:
                self.repository.upsert_symbols([resolved], market=normalized_market)

        self.repository.backfill_symbol_daily_coverage(normalized_market)
        if scope == "all":
            stocks = self.repository.list_symbols(market=normalized_market)
        else:
            symbol_row = self.repository.get_symbol_record(
                str(symbol or "").strip().upper(),
                market=normalized_market,
            )
            stocks = [symbol_row] if symbol_row else []

        state_before = self._summarize_sync_state(
            normalized_market,
            start_trade_date=target_start_trade_date or effective_start_date,
            target_latest_trade_date=target_latest_trade_date,
        )
        incomplete_symbols = set(
            self.repository.list_symbols_missing_standardized_daily_fields(
                normalized_market,
                start_trade_date=target_start_trade_date or effective_start_date,
            )
        )
        stock_symbols = {
            str((stock or {}).get("symbol") or "").strip().upper()
            for stock in stocks
            if str((stock or {}).get("symbol") or "").strip()
        }
        incomplete_symbols &= stock_symbols

        if (
            normalized_market == "cn"
            and scope == "all"
            and incomplete_symbols
            and state_before.get("is_data_current")
        ):
            run_id = self.repository.start_sync_run(
                source="CN_Tushare_daily_basic",
                mode=mode,
                market=normalized_market,
                scope=scope,
                symbol=None,
                requested_start_date=effective_start_date,
                requested_end_date=requested_end_date,
                requested_days=days,
                requested_years=years,
                universe_source=universe_source,
                total_symbols=len(incomplete_symbols),
            )
            batch_result = self._backfill_cn_daily_basic_only(
                run_id=run_id,
                symbols=incomplete_symbols,
                start_trade_date=target_start_trade_date or effective_start_date,
                target_latest_trade_date=target_latest_trade_date or requested_end_date,
                total_universe_symbols=len(stocks),
                progress_callback=progress_callback,
            )
            state_after = self._summarize_sync_state(
                normalized_market,
                start_trade_date=target_start_trade_date or effective_start_date,
                target_latest_trade_date=target_latest_trade_date,
            )
            status = "completed" if batch_result["failure_count"] == 0 else "partial"
            self.repository.finish_sync_run(
                run_id=run_id,
                status=status,
                processed_count=batch_result["processed_count"],
                skipped_count=batch_result["skipped_count"],
                success_count=batch_result["success_count"],
                failure_count=batch_result["failure_count"],
                rows_written=batch_result["rows_written"],
                error_summary=batch_result["error_summary"],
                error_details=batch_result["error_details"],
                state_snapshot=state_after,
            )
            return {
                "run_id": run_id,
                "market": normalized_market,
                "scope": scope,
                "symbol": None,
                "days": days,
                "years": years,
                "start_date": effective_start_date,
                "processed_count": batch_result["processed_count"],
                "total_symbols": len(incomplete_symbols),
                "skipped_count": batch_result["skipped_count"],
                "success_count": batch_result["success_count"],
                "failure_count": batch_result["failure_count"],
                "rows_written": batch_result["rows_written"],
                "status": status,
                "error_summary": batch_result["error_summary_list"],
            }

        candidates = self._build_sync_candidates(
            stocks,
            market=normalized_market,
            start_trade_date=target_start_trade_date or effective_start_date,
            target_latest_trade_date=target_latest_trade_date,
        )
        skipped_count = max(len(stocks) - len(candidates), 0)

        if self._should_skip_run(
            latest_run=latest_run,
            state_before=state_before,
            candidates=candidates,
        ):
            run_id = self.repository.start_sync_run(
                source=f"{normalized_market.upper()}_MULTI_SOURCE",
                mode=mode,
                market=normalized_market,
                scope=scope,
                symbol=symbol.upper() if symbol else None,
                requested_start_date=effective_start_date,
                requested_end_date=requested_end_date,
                requested_days=days,
                requested_years=years,
                universe_source=universe_source,
                total_symbols=0,
            )
            state_after = self._summarize_sync_state(
                normalized_market,
                start_trade_date=target_start_trade_date or effective_start_date,
                target_latest_trade_date=target_latest_trade_date,
            )
            self.repository.finish_sync_run(
                run_id=run_id,
                status="skipped",
                processed_count=0,
                skipped_count=len(stocks),
                success_count=0,
                failure_count=0,
                rows_written=0,
                error_summary=None,
                error_details={"reason": "data_current", "latest_run_id": latest_run.get("id") if latest_run else None},
                state_snapshot=state_after,
            )
            return {
                "run_id": run_id,
                "market": normalized_market,
                "scope": scope,
                "symbol": symbol.upper() if symbol else None,
                "days": days,
                "years": years,
                "start_date": effective_start_date,
                "processed_count": 0,
                "total_symbols": 0,
                "skipped_count": len(stocks),
                "success_count": 0,
                "failure_count": 0,
                "rows_written": 0,
                "status": "skipped",
                "error_summary": [],
            }

        run_id = self.repository.start_sync_run(
            source=f"{normalized_market.upper()}_MULTI_SOURCE",
            mode=mode,
            market=normalized_market,
            scope=scope,
            symbol=symbol.upper() if symbol else None,
            requested_start_date=effective_start_date,
            requested_end_date=requested_end_date,
            requested_days=days,
            requested_years=years,
            universe_source=universe_source,
            total_symbols=len(candidates),
        )
        success_count = 0
        failure_count = 0
        rows_written = 0
        errors: list[str] = []
        error_details: list[dict[str, Any]] = []

        for stock in candidates:
            current_symbol = str((stock or {}).get("symbol") or "").strip().upper()
            if not current_symbol:
                continue
            item_status = "empty"
            item_source = None
            item_rows = 0
            try:
                result = self.sync_symbol_daily(
                    symbol=current_symbol,
                    market=normalized_market,
                    ts_code=(stock or {}).get("ts_code"),
                    start_date=effective_start_date,
                )
                item_rows = int(result.get("rows") or 0)
                rows_written += item_rows
                if item_rows > 0:
                    success_count += 1
                    item_status = "success"
                    item_source = result.get("source")
                else:
                    failure_count += 1
                    errors.append(f"{current_symbol}:empty")
                    error_details.append({"symbol": current_symbol, "status": "empty"})
                    item_status = "empty"
            except Exception as exc:
                failure_count += 1
                errors.append(f"{current_symbol}:{type(exc).__name__}")
                error_details.append(
                    {
                        "symbol": current_symbol,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                item_status = "error"

            processed_count = success_count + failure_count
            self.repository.update_sync_run_progress(
                run_id=run_id,
                processed_count=processed_count,
                skipped_count=skipped_count,
                success_count=success_count,
                failure_count=failure_count,
                rows_written=rows_written,
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "run_id": run_id,
                        "market": normalized_market,
                        "scope": scope,
                        "symbol": current_symbol,
                        "processed_count": processed_count,
                        "total_symbols": len(candidates),
                        "skipped_count": skipped_count,
                        "success_count": success_count,
                        "failure_count": failure_count,
                        "rows_written": rows_written,
                        "item_status": item_status,
                        "source": item_source,
                        "item_rows": item_rows,
                    }
                )

        state_after = self._summarize_sync_state(
            normalized_market,
            start_trade_date=target_start_trade_date or effective_start_date,
            target_latest_trade_date=target_latest_trade_date,
        )
        status = "completed" if failure_count == 0 else "partial"
        processed_count = success_count + failure_count
        self.repository.finish_sync_run(
            run_id=run_id,
            status=status,
            processed_count=processed_count,
            skipped_count=skipped_count,
            success_count=success_count,
            failure_count=failure_count,
            rows_written=rows_written,
            error_summary="; ".join(errors[:20]) if errors else None,
            error_details=error_details[:100] if error_details else None,
            state_snapshot=state_after,
        )
        return {
            "run_id": run_id,
            "market": normalized_market,
            "scope": scope,
            "symbol": symbol.upper() if symbol else None,
            "days": days,
            "years": years,
            "start_date": effective_start_date,
            "processed_count": processed_count,
            "total_symbols": len(candidates),
            "skipped_count": skipped_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "rows_written": rows_written,
            "status": status,
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

        inserted_rows = self.repository.upsert_daily_bars(
            symbol=normalized_symbol,
            daily_df=selected_df,
            source=selected_source,
            market=normalized_market,
            ts_code=ts_code or (symbol_record or {}).get("ts_code"),
        )
        return {"symbol": normalized_symbol, "rows": inserted_rows, "source": selected_source}

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

    def _build_sync_candidates(
        self,
        stocks: list[dict],
        *,
        market: str,
        start_trade_date: Optional[str],
        target_latest_trade_date: Optional[str],
    ) -> list[dict]:
        if not stocks:
            return []

        latest_trade_cutoff = self._compute_stale_cutoff(target_latest_trade_date)
        incomplete_symbols = set(
            self.repository.list_symbols_missing_standardized_daily_fields(
                market,
                start_trade_date=start_trade_date,
            )
        )

        candidate_map: dict[str, dict] = {}
        precise_check_stocks: list[dict] = []
        summary_stale_rows: list[dict[str, str]] = []

        for stock in stocks:
            current_symbol = str((stock or {}).get("symbol") or "").strip().upper()
            if not current_symbol:
                continue
            if current_symbol in incomplete_symbols:
                candidate_map[current_symbol] = stock
                continue

            daily_start_date = self._normalize_trade_date_text((stock or {}).get("daily_start_date"))
            daily_end_date = self._normalize_trade_date_text((stock or {}).get("daily_end_date"))

            if (
                daily_start_date is not None
                and start_trade_date
                and daily_start_date > start_trade_date
            ):
                candidate_map[current_symbol] = stock
                continue
            if (
                daily_end_date is not None
                and latest_trade_cutoff
                and daily_end_date < latest_trade_cutoff
            ):
                summary_stale_rows.append(
                    {"symbol": current_symbol, "latest_trade_date": daily_end_date}
                )
                continue
            precise_check_stocks.append(stock)

        summary_exempt_symbols = self._find_suspension_exempt_symbols(
            market=market,
            stale_rows=summary_stale_rows,
            target_latest_trade_date=target_latest_trade_date,
        )
        summary_stale_symbols = {row["symbol"] for row in summary_stale_rows}
        for stock in stocks:
            current_symbol = str((stock or {}).get("symbol") or "").strip().upper()
            if (
                current_symbol
                and current_symbol in summary_stale_symbols
                and current_symbol not in summary_exempt_symbols
            ):
                candidate_map[current_symbol] = stock

        precise_check_symbols = [
            str((stock or {}).get("symbol") or "").strip().upper()
            for stock in precise_check_stocks
            if str((stock or {}).get("symbol") or "").strip()
        ]
        date_ranges = self.repository.get_symbol_date_ranges(market, symbols=precise_check_symbols)
        exact_stale_rows: list[dict[str, str]] = []

        for stock in precise_check_stocks:
            current_symbol = str((stock or {}).get("symbol") or "").strip().upper()
            if not current_symbol or current_symbol in candidate_map:
                continue

            symbol_range = date_ranges.get(current_symbol)
            if symbol_range is None:
                candidate_map[current_symbol] = stock
                continue

            if start_trade_date and (
                symbol_range.get("min_trade_date") is None
                or symbol_range["min_trade_date"] > start_trade_date
            ):
                candidate_map[current_symbol] = stock
                continue
            if latest_trade_cutoff and (
                symbol_range.get("max_trade_date") is None
                or symbol_range["max_trade_date"] < latest_trade_cutoff
            ):
                exact_stale_rows.append(
                    {
                        "symbol": current_symbol,
                        "latest_trade_date": symbol_range.get("max_trade_date"),
                    }
                )

        exact_exempt_symbols = self._find_suspension_exempt_symbols(
            market=market,
            stale_rows=exact_stale_rows,
            target_latest_trade_date=target_latest_trade_date,
        )
        exact_stale_symbols = {row["symbol"] for row in exact_stale_rows}
        for stock in precise_check_stocks:
            current_symbol = str((stock or {}).get("symbol") or "").strip().upper()
            if (
                current_symbol
                and current_symbol in exact_stale_symbols
                and current_symbol not in exact_exempt_symbols
            ):
                candidate_map[current_symbol] = stock

        return list(candidate_map.values())

    def _backfill_cn_daily_basic_only(
        self,
        *,
        run_id: int,
        symbols: set[str],
        start_trade_date: Optional[str],
        target_latest_trade_date: Optional[str],
        total_universe_symbols: int,
        progress_callback: Optional[Callable[[dict], None]],
    ) -> dict:
        target_symbols = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        if not target_symbols:
            return {
                "processed_count": 0,
                "skipped_count": total_universe_symbols,
                "success_count": 0,
                "failure_count": 0,
                "rows_written": 0,
                "error_summary": None,
                "error_summary_list": [],
                "error_details": None,
            }

        open_dates = TushareDataSource.list_cn_open_trade_dates(
            start_date=start_trade_date,
            end_date=target_latest_trade_date,
        )
        touched_symbols: set[str] = set()
        rows_written = 0

        for trade_date in open_dates:
            daily_basic_df = TushareDataSource.fetch_cn_daily_basic_by_trade_date(trade_date)
            if daily_basic_df is None or daily_basic_df.empty:
                continue

            batch_df = daily_basic_df.copy()
            batch_df["symbol"] = (
                batch_df["ts_code"]
                .astype(str)
                .str.split(".")
                .str[0]
                .str.strip()
                .str.upper()
            )
            batch_df = batch_df[batch_df["symbol"].isin(target_symbols)]
            if batch_df.empty:
                continue

            rows_written += self.repository.bulk_update_cn_daily_basic(batch_df)
            touched_symbols.update(batch_df["symbol"].dropna().astype(str).str.upper().tolist())

            processed_count = len(touched_symbols)
            skipped_count = max(total_universe_symbols - processed_count, 0)
            self.repository.update_sync_run_progress(
                run_id=run_id,
                processed_count=processed_count,
                skipped_count=skipped_count,
                success_count=processed_count,
                failure_count=0,
                rows_written=rows_written,
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "run_id": run_id,
                        "market": "cn",
                        "scope": "all",
                        "symbol": f"daily_basic:{trade_date}",
                        "processed_count": processed_count,
                        "total_symbols": len(target_symbols),
                        "skipped_count": skipped_count,
                        "success_count": processed_count,
                        "failure_count": 0,
                        "rows_written": rows_written,
                        "item_status": "batch_backfill",
                        "source": "CN_Tushare_daily_basic",
                        "item_rows": len(batch_df),
                    }
                )

        remaining_symbols = sorted(target_symbols - touched_symbols)
        error_details = None
        error_summary = None
        error_summary_list: list[str] = []
        if remaining_symbols:
            error_summary_list = [f"{symbol}:daily_basic_missing" for symbol in remaining_symbols[:20]]
            error_summary = "; ".join(error_summary_list)
            error_details = [
                {"symbol": symbol, "status": "daily_basic_missing"}
                for symbol in remaining_symbols[:100]
            ]

        processed_count = len(target_symbols)
        success_count = len(touched_symbols)
        failure_count = len(remaining_symbols)
        skipped_count = max(total_universe_symbols - processed_count, 0)
        return {
            "processed_count": processed_count,
            "skipped_count": skipped_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "rows_written": rows_written,
            "error_summary": error_summary,
            "error_summary_list": error_summary_list,
            "error_details": error_details,
        }

    def _summarize_sync_state(
        self,
        market: str,
        *,
        start_trade_date: Optional[str],
        target_latest_trade_date: Optional[str],
    ) -> dict:
        state = self.repository.summarize_market_sync_state(
            market,
            start_trade_date=start_trade_date,
            target_latest_trade_date=target_latest_trade_date,
        )
        if market != "cn" or not target_latest_trade_date:
            return state

        stale_cutoff = self._compute_stale_cutoff(target_latest_trade_date)
        if not stale_cutoff:
            return state

        stale_rows = self.repository.list_stale_symbols(market, stale_cutoff=stale_cutoff)
        if not stale_rows:
            return state

        exempt_symbols = self._find_suspension_exempt_symbols(
            market=market,
            stale_rows=stale_rows,
            target_latest_trade_date=target_latest_trade_date,
        )
        if not exempt_symbols:
            return state

        adjusted_state = dict(state)
        adjusted_state["stale_symbol_count"] = sum(
            1 for row in stale_rows if row["symbol"] not in exempt_symbols
        )
        coverage_start_date = adjusted_state.get("coverage_start_date")
        coverage_end_date = adjusted_state.get("coverage_end_date")
        coverage_is_current = (
            target_latest_trade_date is None
            or coverage_end_date == target_latest_trade_date
            or adjusted_state["stale_symbol_count"] == 0
        )
        has_required_history = True
        if start_trade_date:
            has_required_history = (
                coverage_start_date is not None and coverage_start_date <= start_trade_date
            )
        adjusted_state["is_data_current"] = (
            int(adjusted_state.get("symbol_snapshot_count") or 0) > 0
            and has_required_history
            and int(adjusted_state.get("missing_symbol_count") or 0) == 0
            and int(adjusted_state.get("stale_symbol_count") or 0) == 0
            and coverage_is_current
        )
        return adjusted_state

    def _find_suspension_exempt_symbols(
        self,
        *,
        market: str,
        stale_rows: list[dict[str, str]],
        target_latest_trade_date: Optional[str],
    ) -> set[str]:
        if market != "cn" or not target_latest_trade_date or not stale_rows:
            return set()

        exempt_symbols: set[str] = set()
        for row in stale_rows:
            current_symbol = str(row.get("symbol") or "").strip().upper()
            latest_trade_date = self._normalize_trade_date_text(row.get("latest_trade_date"))
            if not current_symbol or not latest_trade_date:
                continue
            try:
                suspend_start_date = (
                    pd.Timestamp(latest_trade_date) + pd.Timedelta(days=1)
                ).strftime("%Y-%m-%d")
            except Exception:
                continue
            if suspend_start_date > target_latest_trade_date:
                continue
            suspend_dates = TushareDataSource.fetch_cn_suspend_dates(
                current_symbol,
                start_date=suspend_start_date,
                end_date=target_latest_trade_date,
            )
            if suspend_dates:
                exempt_symbols.add(current_symbol)
        return exempt_symbols

    @staticmethod
    def _normalize_trade_date_text(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        try:
            return pd.Timestamp(value).strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _should_skip_run(
        *,
        latest_run: Optional[dict],
        state_before: dict,
        candidates: list[dict],
    ) -> bool:
        if not candidates:
            if not state_before.get("is_data_current"):
                return False
            if latest_run is None:
                return True
            return latest_run.get("status") in {"completed", "partial", "skipped"} and bool(
                latest_run.get("is_data_current")
            )

        if latest_run is None or latest_run.get("status") != "completed" or int(latest_run.get("failure_count") or 0) != 0:
            return False

        stable_keys = (
            "target_latest_trade_date",
            "coverage_start_date",
            "coverage_end_date",
            "covered_symbol_count",
            "missing_symbol_count",
            "stale_symbol_count",
            "daily_row_count",
        )
        if any(latest_run.get(key) != state_before.get(key) for key in stable_keys):
            return False
        return int(latest_run.get("processed_count") or 0) == len(candidates)

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

    def _resolve_trade_window(
        self,
        market: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        if market != "cn":
            return start_date, None
        if not any(isinstance(source, TushareDataSource) for source in self.cn_daily_sources):
            return start_date, None
        first_open_date, latest_open_date = TushareDataSource.get_cn_trade_window(
            start_date=start_date,
            end_date=end_date,
        )
        return first_open_date or start_date, latest_open_date

    def _compute_stale_cutoff(self, target_latest_trade_date: Optional[str]) -> Optional[str]:
        if not target_latest_trade_date:
            return None
        try:
            return (
                pd.Timestamp(target_latest_trade_date) - pd.Timedelta(days=self.repository.STALE_GRACE_DAYS)
            ).strftime("%Y-%m-%d")
        except Exception:
            return target_latest_trade_date

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
