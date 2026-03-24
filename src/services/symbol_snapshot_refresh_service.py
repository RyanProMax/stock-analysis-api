"""
每日 symbols 快照刷新协调服务。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Lock, Thread
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from ..data_provider.sources.tushare import TushareDataSource
from ..repositories import MarketDataRepository, market_data_repository
from .symbol_catalog_service import SymbolCatalogService, symbol_catalog_service


logger = logging.getLogger(__name__)


class SymbolSnapshotRefreshService:
    EXCLUDED_PATH_PREFIXES = ("/docs", "/redoc")
    EXCLUDED_PATHS = {"/openapi.json"}
    MARKET_TIMEZONES = {
        "cn": ZoneInfo("Asia/Shanghai"),
        "us": ZoneInfo("America/New_York"),
    }
    US_BENCHMARK_SYMBOL = "SPY"

    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        symbol_catalog: Optional[SymbolCatalogService] = None,
    ):
        self.repository = repository or market_data_repository
        self.symbol_catalog = symbol_catalog or symbol_catalog_service
        self._lock = Lock()
        self._state: Dict[str, Dict[str, Any]] = {
            "cn": {
                "last_checked_date": None,
                "last_success_at": None,
                "last_error": None,
                "in_flight": False,
            },
            "us": {
                "last_checked_date": None,
                "last_success_at": None,
                "last_error": None,
                "in_flight": False,
            },
        }

    def notify_request(self, path: str) -> None:
        normalized_path = str(path or "").split("?", 1)[0]
        if self._should_skip_path(normalized_path):
            return

        for market in ("cn", "us"):
            self._maybe_schedule_market_refresh(market=market, trigger_path=normalized_path)

    def _maybe_schedule_market_refresh(self, *, market: str, trigger_path: str) -> None:
        market_date = self._market_today(market)
        with self._lock:
            state = self._state[market]
            if state["in_flight"] or state["last_checked_date"] == market_date:
                return
            state["in_flight"] = True
        self._spawn_refresh_thread(
            market=market,
            trigger_path=trigger_path,
            market_date=market_date,
        )

    def _spawn_refresh_thread(self, *, market: str, trigger_path: str, market_date: str) -> None:
        Thread(
            target=self._run_market_refresh,
            kwargs={
                "market": market,
                "trigger_path": trigger_path,
                "market_date": market_date,
            },
            daemon=True,
        ).start()

    def _run_market_refresh(self, *, market: str, trigger_path: str, market_date: str) -> None:
        success = False
        error_text = None
        open_check = {"is_open": None, "used_fallback": False}
        try:
            snapshot_meta = self.repository.get_symbol_snapshot_meta(market)
            if self._snapshot_updated_today(
                snapshot_meta=snapshot_meta,
                market=market,
                market_date=market_date,
            ):
                logger.info(
                    "symbol snapshot refresh completed market=%s trigger=%s reason=store_current is_open=%s fallback=%s count=%s",
                    market,
                    trigger_path,
                    open_check["is_open"],
                    open_check["used_fallback"],
                    snapshot_meta.get("symbol_count", 0),
                )
                success = True
                return

            open_check = self._is_market_open_today(market=market, market_date=market_date)
            if open_check["is_open"] is None:
                error_text = "market_open_check_failed"
                logger.warning(
                    "symbol snapshot refresh failed market=%s trigger=%s reason=%s is_open=%s fallback=%s",
                    market,
                    trigger_path,
                    error_text,
                    open_check["is_open"],
                    open_check["used_fallback"],
                )
                return

            if not open_check["is_open"]:
                logger.info(
                    "symbol snapshot refresh skipped market=%s trigger=%s reason=market_closed is_open=%s fallback=%s",
                    market,
                    trigger_path,
                    open_check["is_open"],
                    open_check["used_fallback"],
                )
                success = True
                return

            refresh_result = self.symbol_catalog.refresh_market_snapshot_result(market)
            if not refresh_result.get("success"):
                error_text = str(refresh_result.get("reason") or "snapshot_refresh_failed")
                logger.warning(
                    "symbol snapshot refresh failed market=%s trigger=%s reason=%s is_open=%s fallback=%s source=%s",
                    market,
                    trigger_path,
                    error_text,
                    open_check["is_open"],
                    open_check["used_fallback"],
                    refresh_result.get("source") or "",
                )
                return

            logger.info(
                "symbol snapshot refresh completed market=%s trigger=%s is_open=%s fallback=%s count=%s source=%s partial=%s",
                market,
                trigger_path,
                open_check["is_open"],
                open_check["used_fallback"],
                len(refresh_result.get("rows") or []),
                refresh_result.get("source") or "",
                refresh_result.get("partial", False),
            )
            success = True
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "symbol snapshot refresh failed market=%s trigger=%s error_type=%s error=%s is_open=%s fallback=%s",
                market,
                trigger_path,
                type(exc).__name__,
                exc,
                open_check["is_open"],
                open_check["used_fallback"],
            )
        finally:
            with self._lock:
                state = self._state[market]
                state["in_flight"] = False
                if success:
                    state["last_checked_date"] = market_date
                    state["last_success_at"] = self._now_iso()
                    state["last_error"] = None
                else:
                    state["last_error"] = error_text

    def _is_market_open_today(self, *, market: str, market_date: str) -> Dict[str, Any]:
        if market == "cn":
            is_open = TushareDataSource.is_cn_market_open_on(market_date)
            return {"is_open": is_open, "used_fallback": False}

        is_open, used_fallback = self._is_us_market_open_today(market_date)
        return {"is_open": is_open, "used_fallback": used_fallback}

    def _is_us_market_open_today(self, market_date: str) -> tuple[Optional[bool], bool]:
        ny_tz = self.MARKET_TIMEZONES["us"]
        weekday = pd.Timestamp(market_date).tz_localize(ny_tz).weekday()
        if weekday >= 5:
            return False, False

        try:
            import yfinance as yf

            ticker = yf.Ticker(self.US_BENCHMARK_SYMBOL)
            intraday = ticker.history(
                start=market_date,
                end=(pd.Timestamp(market_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                interval="1m",
                prepost=True,
            )
            if intraday is not None and not intraday.empty:
                index = pd.DatetimeIndex(intraday.index)
                if index.tz is None:
                    index = index.tz_localize(ny_tz)
                else:
                    index = index.tz_convert(ny_tz)
                if any(ts.strftime("%Y-%m-%d") == market_date for ts in index):
                    return True, False

            history_metadata = getattr(ticker, "history_metadata", None) or {}
            current_period = (
                history_metadata.get("currentTradingPeriod")
                if isinstance(history_metadata, dict)
                else None
            )
            regular = current_period.get("regular") if isinstance(current_period, dict) else None
            if isinstance(regular, dict):
                for key in ("start", "end"):
                    current = self._coerce_exchange_datetime(regular.get(key), ny_tz)
                    if current is not None and current.strftime("%Y-%m-%d") == market_date:
                        return True, False
        except Exception:
            pass

        return True, True

    @staticmethod
    def _coerce_exchange_datetime(value: Any, tz: ZoneInfo) -> Optional[datetime]:
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(float(value), tz=tz)
            parsed = pd.Timestamp(value)
            if pd.isna(parsed):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.tz_localize(tz)
            else:
                parsed = parsed.tz_convert(tz)
            return parsed.to_pydatetime()
        except Exception:
            return None

    def _snapshot_updated_today(
        self,
        *,
        snapshot_meta: Dict[str, Any],
        market: str,
        market_date: str,
    ) -> bool:
        if int(snapshot_meta.get("symbol_count") or 0) <= 0:
            return False
        min_updated_at = snapshot_meta.get("min_updated_at")
        max_updated_at = snapshot_meta.get("max_updated_at")
        if not min_updated_at or not max_updated_at:
            return False
        return (
            self._updated_at_market_date(min_updated_at, market) == market_date
            and self._updated_at_market_date(max_updated_at, market) == market_date
        )

    def _updated_at_market_date(self, updated_at: str, market: str) -> Optional[str]:
        try:
            parsed = pd.Timestamp(updated_at)
        except Exception:
            return None
        market_tz = self.MARKET_TIMEZONES[market]
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize(ZoneInfo("UTC"))
        else:
            parsed = parsed.tz_convert(ZoneInfo("UTC"))
        return parsed.tz_convert(market_tz).strftime("%Y-%m-%d")

    def _market_today(self, market: str) -> str:
        return datetime.now(self.MARKET_TIMEZONES[market]).strftime("%Y-%m-%d")

    @classmethod
    def _should_skip_path(cls, path: str) -> bool:
        return path in cls.EXCLUDED_PATHS or any(
            path.startswith(prefix) for prefix in cls.EXCLUDED_PATH_PREFIXES
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


symbol_snapshot_refresh_service = SymbolSnapshotRefreshService()
