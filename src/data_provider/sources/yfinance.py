"""
yfinance 数据源

使用 yfinance 获取美股股票列表、日线数据、财务数据与实时行情
"""

import logging
import re
from typing import List, Dict, Any, Optional
import pandas as pd

from ..base import BaseStockDataSource
from ..fundamental_adapter import (
    build_dividend_payload_from_series,
    enrich_dividend_payload_with_yield,
)
from ..realtime_types import UnifiedRealtimeQuote, RealtimeSource
from ...model.contracts import (
    build_standard_field,
    format_ratio_as_percent,
)


logger = logging.getLogger(__name__)


class YfinanceDataSource(BaseStockDataSource):
    """yfinance 数据源"""

    SOURCE_NAME: str = "yfinance"
    priority: int = 0  # 美股优先级最高

    # 列名映射
    US_YFINANCE_MAP = {
        "Date": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }

    def fetch_a_stocks(self) -> List[Dict[str, Any]]:
        """yfinance 不支持 A 股列表"""
        return []

    def fetch_us_stocks(self) -> List[Dict[str, Any]]:
        """yfinance 不提供股票列表接口"""
        return []

    def is_available(self, market: str) -> bool:
        """yfinance 仅支持美股"""
        return market == "美股"

    # ==================== 日线数据实现 ====================

    def _fetch_raw_daily(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取原始日线数据"""
        try:
            import yfinance as yf

            df = yf.Ticker(symbol).history(period="2y", auto_adjust=False)
            if df is not None and not df.empty:
                df = df.reset_index()
                return df
        except Exception as e:
            print(f"⚠️ yfinance 获取日线失败 [{symbol}]: {e}")
        return None

    def _normalize_daily(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """标准化日线数据"""
        df = df.copy()

        # 列名映射
        if self.US_YFINANCE_MAP:
            df.rename(columns=self.US_YFINANCE_MAP, inplace=True)

        # 统一小写
        df.columns = [c.lower() for c in df.columns]

        return df

    # ==================== 实时行情 ====================

    def get_realtime_quote(self, symbol: str) -> Optional[UnifiedRealtimeQuote]:
        """获取美股实时行情，优先 fast_info，失败后回退到最近 2 日 history。"""
        normalized = str(symbol).strip().upper()
        if not self._is_us_stock_symbol(normalized):
            return None

        try:
            import yfinance as yf

            ticker = yf.Ticker(normalized)

            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")

                price = self._safe_float(
                    getattr(info, "lastPrice", None) or getattr(info, "last_price", None)
                )
                pre_close = self._safe_float(
                    getattr(info, "previousClose", None) or getattr(info, "previous_close", None)
                )
                open_price = self._safe_float(getattr(info, "open", None))
                high = self._safe_float(
                    getattr(info, "dayHigh", None) or getattr(info, "day_high", None)
                )
                low = self._safe_float(
                    getattr(info, "dayLow", None) or getattr(info, "day_low", None)
                )
                volume = self._safe_int(
                    getattr(info, "lastVolume", None) or getattr(info, "last_volume", None)
                )
                market_cap = self._safe_float(
                    getattr(info, "marketCap", None) or getattr(info, "market_cap", None)
                )
            except Exception:
                history = ticker.history(period="2d")
                if history is None or history.empty:
                    return None

                latest = history.iloc[-1]
                previous = history.iloc[-2] if len(history) > 1 else latest

                price = self._safe_float(latest.get("Close"))
                pre_close = self._safe_float(previous.get("Close"))
                open_price = self._safe_float(latest.get("Open"))
                high = self._safe_float(latest.get("High"))
                low = self._safe_float(latest.get("Low"))
                volume = self._safe_int(latest.get("Volume"))
                market_cap = None

            change_amount = None
            change_pct = None
            if price is not None and pre_close not in (None, 0):
                change_amount = price - float(pre_close)
                change_pct = (change_amount / float(pre_close)) * 100.0

            amplitude = None
            if high is not None and low is not None and pre_close not in (None, 0):
                amplitude = ((high - low) / float(pre_close)) * 100.0

            return UnifiedRealtimeQuote(
                code=normalized,
                name="",
                source=RealtimeSource.YFINANCE,
                price=price,
                change_pct=round(change_pct, 4) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 4) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=pre_close,
                total_mv=market_cap,
            )
        except Exception as e:
            logger.warning(f"yfinance 获取美股实时行情失败 [{normalized}]: {e}")
            return None

    # ==================== 财务数据 ====================

    @classmethod
    def get_us_financial_data(cls, symbol: str) -> tuple[Optional[dict], dict]:
        """
        使用 yfinance 获取美股财务数据

        Args:
            symbol: 美股代码（如 AAPL）

        Returns:
            (财务数据字典, 原始数据字典)
            注：当前仅返回原始 info，不做字段提取
        """
        financial_data = {}
        raw_data = {}

        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info and isinstance(info, dict):
                raw_data["info"] = info
                calendar = cls._extract_calendar_payload(ticker)
                if calendar:
                    raw_data["calendar"] = calendar
                earnings_dates = cls._extract_earnings_dates_payload(ticker)
                if earnings_dates:
                    raw_data["earnings_dates"] = earnings_dates
                normalized_fields = cls._build_normalized_fields(ticker, info)
                if normalized_fields:
                    raw_data["normalized_fields"] = normalized_fields
                    financial_data["normalized_fields"] = normalized_fields
                financial_data["raw_data"] = raw_data
        except Exception as e:
            print(f"⚠️ yfinance 获取美股财务数据失败 [{symbol}]: {e}")

        return financial_data if financial_data else None, raw_data

    @classmethod
    def _extract_calendar_payload(cls, ticker: Any) -> Optional[Dict[str, Any]]:
        try:
            calendar = ticker.calendar
        except Exception:
            return None

        if calendar is None:
            return None
        if isinstance(calendar, dict):
            return dict(calendar)
        if isinstance(calendar, pd.DataFrame):
            if calendar.empty:
                return None
            if len(calendar.index) == 1:
                return calendar.iloc[0].to_dict()
            return {
                str(index): row.dropna().to_dict()
                for index, row in calendar.iterrows()
                if hasattr(row, "dropna")
            }
        if hasattr(calendar, "to_dict"):
            try:
                payload = calendar.to_dict()
                return payload if isinstance(payload, dict) else None
            except Exception:
                return None
        return None

    @classmethod
    def _extract_earnings_dates_payload(cls, ticker: Any) -> Optional[List[str]]:
        try:
            earnings_dates = ticker.earnings_dates
        except Exception:
            return None

        if earnings_dates is None or getattr(earnings_dates, "empty", False):
            return None
        if isinstance(earnings_dates, pd.DataFrame):
            values = []
            for idx in earnings_dates.index.tolist():
                try:
                    values.append(pd.Timestamp(idx).isoformat())
                except Exception:
                    continue
            return values or None
        return None

    @classmethod
    def _build_normalized_fields(cls, ticker: Any, info: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        as_of = None

        try:
            dividends = ticker.dividends
        except Exception:
            dividends = None

        dividend_payload = enrich_dividend_payload_with_yield(
            build_dividend_payload_from_series(dividends),
            price,
        )
        ttm_dividend_yield_pct = dividend_payload.get("ttm_dividend_yield_pct")
        if dividend_payload:
            normalized["dividend_metrics"] = dividend_payload
        if ttm_dividend_yield_pct is not None:
            dividend_yield = float(ttm_dividend_yield_pct) / 100.0
            normalized["dividend_yield"] = build_standard_field(
                "dividend_yield",
                value=dividend_yield,
                display_value=format_ratio_as_percent(dividend_yield, decimals=2),
                as_of=dividend_payload.get("as_of"),
                notes=[
                    f"ttm_cash_dividend_per_share={dividend_payload.get('ttm_cash_dividend_per_share')}",
                    dividend_payload.get("yield_formula", ""),
                ],
            )

        payout_ratio = info.get("payoutRatio")
        if payout_ratio is not None:
            try:
                payout_value = float(payout_ratio)
            except (TypeError, ValueError):
                payout_value = None
            if payout_value is not None:
                normalized["payout_ratio"] = build_standard_field(
                    "payout_ratio",
                    value=payout_value,
                    display_value=format_ratio_as_percent(payout_value, decimals=2),
                    as_of=as_of,
                )

        book_value = info.get("bookValue")
        if book_value is not None:
            try:
                book_value_num = float(book_value)
            except (TypeError, ValueError):
                book_value_num = None
            if book_value_num is not None:
                normalized["book_value_per_share"] = build_standard_field(
                    "book_value_per_share",
                    value=book_value_num,
                    display_value=f"{book_value_num:.2f}",
                    as_of=as_of,
                )

        ratio_fields = {
            "held_percent_insiders": info.get("heldPercentInsiders"),
            "held_percent_institutions": info.get("heldPercentInstitutions"),
            "shares_percent_shares_out": info.get("sharesPercentSharesOut"),
        }
        for canonical_field, raw_value in ratio_fields.items():
            if raw_value is None:
                continue
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                continue
            normalized[canonical_field] = build_standard_field(
                canonical_field,
                value=numeric,
                display_value=format_ratio_as_percent(numeric, decimals=2),
                as_of=as_of,
            )

        return normalized

    @staticmethod
    def _is_us_stock_symbol(symbol: str) -> bool:
        text = str(symbol).strip().upper()
        return bool(re.match(r"^[A-Z][A-Z0-9]{0,4}(?:[.-][A-Z])?$", text))

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            if value is None or pd.isna(value):
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None
