"""
盯盘轮询服务。

为外部 Agent 提供单接口、多股票的低 token 轮询能力。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from ..analyzer.trend_analyzer import StockTrendAnalyzer
from ..data_provider.manager import data_manager
from .daily_data_read_service import daily_data_read_service


class WatchPollingService:
    BASELINE_TTL_HOURS = 24
    PRICE_JUMP_THRESHOLD = 0.02
    VOLUME_SPIKE_THRESHOLD = 1.8
    TURNOVER_SPIKE_DELTA = 0.01
    NEAR_DAY_EXTREME_THRESHOLD = 0.01
    BREAKOUT_LOOKBACK = 20
    EARNINGS_SOON_DAYS = 7
    _baseline_state: Dict[str, Dict[str, Any]] = {}

    def poll(self, symbols: List[str]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for raw_symbol in symbols:
            symbol = str(raw_symbol).strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            items.append(self._poll_symbol(symbol))

        return items

    def _poll_symbol(self, symbol: str) -> Dict[str, Any]:
        current = self._build_current_snapshot(symbol)
        previous = self._load_baseline(symbol)

        delta = self._build_delta(current, previous)
        alerts = self._build_alerts(current, previous)

        payload = deepcopy(current)
        payload["delta"] = delta
        payload["alerts"] = alerts
        payload["baseline_at"] = previous.get("computed_at") if isinstance(previous, dict) else None

        if current.get("status") != "failed":
            self._save_baseline(symbol, current)
        return payload

    def _build_current_snapshot(self, symbol: str) -> Dict[str, Any]:
        computed_at = self._now_iso()
        market = "us" if any(ch.isalpha() for ch in symbol) else "cn"

        stock_info = data_manager.get_stock_info(symbol)
        daily_df, stock_name, daily_source = daily_data_read_service.get_stock_daily(symbol)
        quote, quote_source = data_manager.get_realtime_quote(symbol)
        financial_data, financial_source = data_manager.get_financial_data(symbol)

        quote_payload = self._build_quote_payload(
            daily_df=daily_df,
            quote=quote,
            quote_source=quote_source,
            daily_source=daily_source,
            computed_at=computed_at,
        )
        technical_payload = self._build_technical_payload(daily_df=daily_df, quote_payload=quote_payload, symbol=symbol)
        fundamentals_payload = self._build_fundamentals_payload(
            financial_data=financial_data,
            quote=quote,
            quote_source=quote_source,
            financial_source=financial_source,
            market=market,
        )
        earnings_watch = self._build_earnings_watch(financial_data=financial_data)

        source_chain = self._dedupe_sources(
            {
                "provider": quote_source,
                "field": "quote",
                "result": "ok" if quote_payload.get("mode") == "realtime" else "failed",
                "mode": "realtime",
            },
            {
                "provider": daily_source,
                "field": "quote",
                "result": "ok" if quote_payload.get("mode") == "daily_fallback" else "not_used",
                "mode": "daily_fallback",
            },
            {
                "provider": financial_source or fundamentals_payload.get("source"),
                "field": "fundamentals",
                "result": "partial" if fundamentals_payload.get("partial") else "ok",
            },
        )

        missing_quote = quote_payload.get("price") is None
        missing_daily = daily_df is None or daily_df.empty
        quote_mode = quote_payload.get("mode")
        us_daily_fallback = market == "us" and quote_mode == "daily_fallback"
        status = "ok"
        partial = False
        if missing_quote and missing_daily:
            status = "failed"
            partial = True
        elif (
            missing_quote
            or us_daily_fallback
            or fundamentals_payload.get("partial")
            or earnings_watch.get("partial")
        ):
            status = "partial"
            partial = True

        return {
            "symbol": symbol,
            "name": stock_info.get("name") or stock_name or symbol,
            "market": market,
            "computed_at": computed_at,
            "source_chain": source_chain,
            "status": status,
            "partial": partial,
            "degradation": {
                "quote_mode": quote_mode,
                "quote_is_realtime": quote_mode == "realtime",
                "quote_fallback_used": quote_mode == "daily_fallback",
                "fundamentals_partial": fundamentals_payload.get("partial", False),
                "earnings_partial": earnings_watch.get("partial", False),
            },
            "quote": quote_payload,
            "fundamentals": fundamentals_payload,
            "technical": technical_payload,
            "earnings_watch": earnings_watch,
        }

    def _build_quote_payload(
        self,
        daily_df: Optional[pd.DataFrame],
        quote: Any,
        quote_source: str,
        daily_source: str,
        computed_at: str,
    ) -> Dict[str, Any]:
        if quote is not None and getattr(quote, "price", None) is not None:
            return {
                "price": self._float_or_none(getattr(quote, "price", None)),
                "change_pct": self._percent_to_ratio(getattr(quote, "change_pct", None)),
                "change_amount": self._float_or_none(getattr(quote, "change_amount", None)),
                "open": self._float_or_none(getattr(quote, "open_price", None)),
                "high": self._float_or_none(getattr(quote, "high", None)),
                "low": self._float_or_none(getattr(quote, "low", None)),
                "pre_close": self._float_or_none(getattr(quote, "pre_close", None)),
                "volume": self._float_or_none(getattr(quote, "volume", None)),
                "amount": self._float_or_none(getattr(quote, "amount", None)),
                "turnover_rate": self._percent_to_ratio(getattr(quote, "turnover_rate", None)),
                "amplitude": self._percent_to_ratio(getattr(quote, "amplitude", None)),
                "volume_ratio": self._float_or_none(getattr(quote, "volume_ratio", None)),
                "source": quote_source or getattr(getattr(quote, "source", None), "value", None),
                "as_of": computed_at,
                "mode": "realtime",
            }

        if daily_df is None or daily_df.empty:
            return {
                "price": None,
                "change_pct": None,
                "change_amount": None,
                "open": None,
                "high": None,
                "low": None,
                "pre_close": None,
                "volume": None,
                "amount": None,
                "turnover_rate": None,
                "amplitude": None,
                "volume_ratio": None,
                "source": quote_source or daily_source or None,
                "as_of": computed_at,
                "mode": "unavailable",
            }

        latest = daily_df.iloc[-1]
        previous = daily_df.iloc[-2] if len(daily_df) > 1 else latest
        price = self._float_or_none(latest.get("close"))
        previous_close = self._float_or_none(previous.get("close"))
        change_amount = None
        change_pct = None
        if price is not None and previous_close not in (None, 0):
            change_amount = price - float(previous_close)
            change_pct = change_amount / float(previous_close)

        return {
            "price": price,
            "change_pct": change_pct,
            "change_amount": change_amount,
            "open": self._float_or_none(latest.get("open")),
            "high": self._float_or_none(latest.get("high")),
            "low": self._float_or_none(latest.get("low")),
            "pre_close": previous_close,
            "volume": self._float_or_none(latest.get("volume")),
            "amount": self._float_or_none(latest.get("amount")),
            "turnover_rate": None,
            "amplitude": self._compute_amplitude(latest),
            "volume_ratio": self._compute_volume_ratio(daily_df),
            "source": daily_source or quote_source or None,
            "as_of": self._date_to_iso(latest.get("date")) or computed_at,
            "mode": "daily_fallback",
        }

    def _build_fundamentals_payload(
        self,
        financial_data: Optional[Dict[str, Any]],
        quote: Any,
        quote_source: str,
        financial_source: str,
        market: str,
    ) -> Dict[str, Any]:
        financial_data = financial_data or {}
        normalized_fields = financial_data.get("normalized_fields", {})
        raw_data = financial_data.get("raw_data", {})
        raw_info = raw_data.get("info", {}) if isinstance(raw_data, dict) else {}

        dividend_field = (
            normalized_fields.get("dividend_yield")
            if isinstance(normalized_fields, dict)
            else None
        )
        dividend_yield = None
        if isinstance(dividend_field, dict):
            dividend_yield = self._float_or_none(dividend_field.get("value"))

        market_cap = None
        if quote is not None:
            market_cap = self._float_or_none(getattr(quote, "total_mv", None))
        if market_cap is None:
            market_cap = self._float_or_none(raw_info.get("marketCap"))

        pe_ratio = self._float_or_none(
            financial_data.get("pe_ratio")
            or raw_info.get("trailingPE")
            or raw_info.get("forwardPE")
            or (getattr(quote, "pe_ratio", None) if quote is not None else None)
        )
        pb_ratio = self._float_or_none(
            financial_data.get("pb_ratio")
            or raw_info.get("priceToBook")
            or (getattr(quote, "pb_ratio", None) if quote is not None else None)
        )
        revenue_ttm = self._float_or_none(raw_info.get("totalRevenue"))

        payload = {
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "market_cap": market_cap,
            "dividend_yield": dividend_yield,
            "revenue_ttm": revenue_ttm,
            "book_value_per_share": self._extract_normalized_field_value(
                normalized_fields, "book_value_per_share"
            ),
            "source": financial_source or quote_source or ("yfinance.info" if market == "us" else None),
            "partial": any(
                value is None
                for value in [pe_ratio, pb_ratio, market_cap, dividend_yield, revenue_ttm]
            ),
        }
        return payload

    def _build_technical_payload(
        self,
        daily_df: Optional[pd.DataFrame],
        quote_payload: Dict[str, Any],
        symbol: str,
    ) -> Dict[str, Any]:
        if daily_df is None or daily_df.empty or len(daily_df) < 20:
            return {
                "trend": "unknown",
                "ma_alignment": "数据不足",
                "breakout_state": "none",
                "volume_ratio": quote_payload.get("volume_ratio"),
                "volume_ratio_state": self._volume_ratio_state(quote_payload.get("volume_ratio")),
            }

        analyzer = StockTrendAnalyzer()
        trend_result = analyzer.analyze(daily_df.copy(), symbol)
        current_price = quote_payload.get("price")
        breakout_state = self._detect_breakout_state(daily_df, current_price)
        volume_ratio = quote_payload.get("volume_ratio")
        if volume_ratio is None:
            volume_ratio = self._float_or_none(trend_result.volume_ratio_5d)

        return {
            "trend": trend_result.trend_status.value,
            "ma_alignment": trend_result.ma_alignment,
            "breakout_state": breakout_state,
            "volume_ratio": volume_ratio,
            "volume_ratio_state": self._volume_ratio_state(volume_ratio),
        }

    def _build_earnings_watch(self, financial_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        next_earnings_date = self._extract_next_earnings_date(financial_data)
        proximity_days = None
        partial = next_earnings_date is None

        if next_earnings_date is not None:
            today = datetime.now(timezone.utc).date()
            delta_days = (datetime.fromisoformat(next_earnings_date).date() - today).days
            if delta_days >= 0:
                proximity_days = delta_days
            else:
                next_earnings_date = None

        return {
            "next_earnings_date": next_earnings_date,
            "earnings_proximity_days": proximity_days,
            "partial": partial or next_earnings_date is None,
        }

    def _build_delta(
        self,
        current: Dict[str, Any],
        previous: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not previous:
            return {
                "status": "initial",
                "changed_fields": [],
                "price_move_pct_since_last_poll": None,
                "volume_ratio_change": None,
                "turnover_rate_change": None,
                "trend_changed": False,
            }

        changed_fields: List[str] = []

        current_price = self._float_or_none(current.get("quote", {}).get("price"))
        previous_price = self._float_or_none(previous.get("quote", {}).get("price"))
        price_move = None
        if current_price is not None and previous_price not in (None, 0):
            price_move = (current_price - float(previous_price)) / float(previous_price)
            if abs(price_move) > 0:
                changed_fields.append("price")

        current_volume_ratio = self._float_or_none(current.get("technical", {}).get("volume_ratio"))
        previous_volume_ratio = self._float_or_none(previous.get("technical", {}).get("volume_ratio"))
        volume_ratio_change = None
        if current_volume_ratio is not None and previous_volume_ratio is not None:
            volume_ratio_change = current_volume_ratio - previous_volume_ratio
            if abs(volume_ratio_change) > 0:
                changed_fields.append("volume_ratio")

        current_turnover = self._float_or_none(current.get("quote", {}).get("turnover_rate"))
        previous_turnover = self._float_or_none(previous.get("quote", {}).get("turnover_rate"))
        turnover_rate_change = None
        if current_turnover is not None and previous_turnover is not None:
            turnover_rate_change = current_turnover - previous_turnover
            if abs(turnover_rate_change) > 0:
                changed_fields.append("turnover_rate")

        current_trend = current.get("technical", {}).get("trend")
        previous_trend = previous.get("technical", {}).get("trend")
        current_breakout = current.get("technical", {}).get("breakout_state")
        previous_breakout = previous.get("technical", {}).get("breakout_state")
        trend_changed = current_trend != previous_trend or current_breakout != previous_breakout
        if trend_changed:
            changed_fields.append("technical_state")

        status = "updated" if changed_fields else "unchanged"
        return {
            "status": status,
            "changed_fields": changed_fields,
            "price_move_pct_since_last_poll": price_move,
            "volume_ratio_change": volume_ratio_change,
            "turnover_rate_change": turnover_rate_change,
            "trend_changed": trend_changed,
        }

    def _build_alerts(
        self,
        current: Dict[str, Any],
        previous: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        symbol = current.get("symbol")
        as_of = current.get("computed_at")
        price = self._float_or_none(current.get("quote", {}).get("price"))
        high = self._float_or_none(current.get("quote", {}).get("high"))
        low = self._float_or_none(current.get("quote", {}).get("low"))
        volume_ratio = self._float_or_none(current.get("technical", {}).get("volume_ratio"))
        turnover_rate = self._float_or_none(current.get("quote", {}).get("turnover_rate"))
        breakout_state = current.get("technical", {}).get("breakout_state")
        earnings_days = current.get("earnings_watch", {}).get("earnings_proximity_days")

        if previous:
            previous_price = self._float_or_none(previous.get("quote", {}).get("price"))
            if price is not None and previous_price not in (None, 0):
                move = (price - float(previous_price)) / float(previous_price)
                if move >= self.PRICE_JUMP_THRESHOLD:
                    alerts.append(
                        self._build_alert(
                            code="price_jump_up",
                            severity="high",
                            summary="价格相对上一轮快速上行",
                            evidence={"price_move_pct_since_last_poll": move, "price": price},
                            symbol=symbol,
                            as_of=as_of,
                        )
                    )
                elif move <= -self.PRICE_JUMP_THRESHOLD:
                    alerts.append(
                        self._build_alert(
                            code="price_jump_down",
                            severity="high",
                            summary="价格相对上一轮快速下行",
                            evidence={"price_move_pct_since_last_poll": move, "price": price},
                            symbol=symbol,
                            as_of=as_of,
                        )
                    )

            previous_turnover = self._float_or_none(previous.get("quote", {}).get("turnover_rate"))
            if (
                turnover_rate is not None
                and previous_turnover is not None
                and turnover_rate - previous_turnover >= self.TURNOVER_SPIKE_DELTA
            ):
                alerts.append(
                    self._build_alert(
                        code="turnover_spike",
                        severity="medium",
                        summary="换手率较上一轮明显抬升",
                        evidence={
                            "turnover_rate": turnover_rate,
                            "turnover_rate_change": turnover_rate - previous_turnover,
                        },
                        symbol=symbol,
                        as_of=as_of,
                    )
                )

            previous_breakout = previous.get("technical", {}).get("breakout_state")
            if breakout_state == "up" and previous_breakout != "up":
                alerts.append(
                    self._build_alert(
                        code="breakout_up",
                        severity="medium",
                        summary="突破状态切换为向上突破",
                        evidence={"breakout_state": breakout_state},
                        symbol=symbol,
                        as_of=as_of,
                    )
                )
            if breakout_state == "down" and previous_breakout != "down":
                alerts.append(
                    self._build_alert(
                        code="breakout_down",
                        severity="medium",
                        summary="突破状态切换为向下破位",
                        evidence={"breakout_state": breakout_state},
                        symbol=symbol,
                        as_of=as_of,
                    )
                )

        if volume_ratio is not None and volume_ratio >= self.VOLUME_SPIKE_THRESHOLD:
            alerts.append(
                self._build_alert(
                    code="volume_spike",
                    severity="medium",
                    summary="量比达到放量阈值",
                    evidence={"volume_ratio": volume_ratio},
                    symbol=symbol,
                    as_of=as_of,
                )
            )

        if price is not None and high not in (None, 0):
            if abs(high - price) / float(high) <= self.NEAR_DAY_EXTREME_THRESHOLD:
                alerts.append(
                    self._build_alert(
                        code="near_day_high",
                        severity="low",
                        summary="价格接近当日高点",
                        evidence={"price": price, "day_high": high},
                        symbol=symbol,
                        as_of=as_of,
                    )
                )
        if price is not None and low not in (None, 0):
            if abs(price - low) / float(price) <= self.NEAR_DAY_EXTREME_THRESHOLD:
                alerts.append(
                    self._build_alert(
                        code="near_day_low",
                        severity="low",
                        summary="价格接近当日低点",
                        evidence={"price": price, "day_low": low},
                        symbol=symbol,
                        as_of=as_of,
                    )
                )

        if isinstance(earnings_days, int) and 0 <= earnings_days <= self.EARNINGS_SOON_DAYS:
            alerts.append(
                self._build_alert(
                    code="earnings_soon",
                    severity="medium",
                    summary="财报日期已进入近 7 天窗口",
                    evidence={
                        "next_earnings_date": current.get("earnings_watch", {}).get("next_earnings_date"),
                        "earnings_proximity_days": earnings_days,
                    },
                    symbol=symbol,
                    as_of=as_of,
                )
            )

        return alerts

    def _load_baseline(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = str(symbol).strip().upper()
        wrapped = self._baseline_state.get(normalized)
        if not isinstance(wrapped, dict):
            return None

        saved_at_raw = wrapped.get("saved_at")
        payload = wrapped.get("payload")
        if not saved_at_raw or not isinstance(payload, dict):
            return None

        try:
            saved_at = datetime.fromisoformat(str(saved_at_raw))
        except Exception:
            return None
        if saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) - saved_at.astimezone(timezone.utc) > timedelta(
            hours=self.BASELINE_TTL_HOURS
        ):
            self._baseline_state.pop(normalized, None)
            return None
        return payload

    def _save_baseline(self, symbol: str, current: Dict[str, Any]) -> None:
        normalized = str(symbol).strip().upper()
        self._baseline_state[normalized] = {
            "saved_at": self._now_iso(),
            "payload": deepcopy(current),
        }

    @staticmethod
    def _build_alert(
        code: str,
        severity: str,
        summary: str,
        evidence: Dict[str, Any],
        symbol: str,
        as_of: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "summary": summary,
            "evidence": evidence,
            "symbol": symbol,
            "as_of": as_of,
        }

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _percent_to_ratio(value: Any) -> Optional[float]:
        numeric = WatchPollingService._float_or_none(value)
        if numeric is None:
            return None
        return numeric / 100.0

    @staticmethod
    def _date_to_iso(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            return pd.Timestamp(value).isoformat()
        except Exception:
            return None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _dedupe_sources(*values: Any) -> List[Any]:
        sources: List[Any] = []
        seen_strings: set[str] = set()
        seen_structured: set[tuple[str, str, str, str]] = set()
        for value in values:
            if isinstance(value, str):
                text = value.strip()
                if text and text not in seen_strings:
                    seen_strings.add(text)
                    sources.append(text)
            elif isinstance(value, dict):
                key = (
                    str(value.get("provider") or ""),
                    str(value.get("field") or ""),
                    str(value.get("result") or ""),
                    str(value.get("mode") or ""),
                )
                if any(key) and key not in seen_structured:
                    seen_structured.add(key)
                    sources.append(value)
        return sources

    @staticmethod
    def _extract_normalized_field_value(
        normalized_fields: Any, field_name: str
    ) -> Optional[float]:
        if not isinstance(normalized_fields, dict):
            return None
        payload = normalized_fields.get(field_name)
        if not isinstance(payload, dict):
            return None
        return WatchPollingService._float_or_none(payload.get("value"))

    @staticmethod
    def _compute_amplitude(row: pd.Series) -> Optional[float]:
        high = WatchPollingService._float_or_none(row.get("high"))
        low = WatchPollingService._float_or_none(row.get("low"))
        pre_close = WatchPollingService._float_or_none(row.get("close"))
        if high is None or low is None or pre_close in (None, 0):
            return None
        return (high - low) / float(pre_close)

    @staticmethod
    def _compute_volume_ratio(df: pd.DataFrame) -> Optional[float]:
        if df is None or df.empty or len(df) < 6 or "volume" not in df.columns:
            return None
        latest_volume = WatchPollingService._float_or_none(df.iloc[-1].get("volume"))
        avg_volume = WatchPollingService._float_or_none(df.iloc[-6:-1]["volume"].mean())
        if latest_volume is None or avg_volume in (None, 0):
            return None
        return latest_volume / float(avg_volume)

    def _detect_breakout_state(
        self,
        daily_df: pd.DataFrame,
        current_price: Optional[float],
    ) -> str:
        if daily_df is None or daily_df.empty or len(daily_df) <= self.BREAKOUT_LOOKBACK:
            return "none"

        price = current_price
        if price is None:
            price = self._float_or_none(daily_df.iloc[-1].get("close"))
        if price is None:
            return "none"

        lookback_df = daily_df.iloc[-(self.BREAKOUT_LOOKBACK + 1):-1]
        recent_high = self._float_or_none(lookback_df["high"].max()) if "high" in lookback_df.columns else None
        recent_low = self._float_or_none(lookback_df["low"].min()) if "low" in lookback_df.columns else None

        if recent_high not in (None, 0) and price > float(recent_high):
            return "up"
        if recent_low is not None and price < float(recent_low):
            return "down"
        return "none"

    @staticmethod
    def _volume_ratio_state(volume_ratio: Optional[float]) -> str:
        if volume_ratio is None:
            return "unknown"
        if volume_ratio >= 1.8:
            return "spike"
        if volume_ratio >= 1.2:
            return "elevated"
        if volume_ratio < 0.8:
            return "light"
        return "normal"

    @staticmethod
    def _extract_next_earnings_date(financial_data: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(financial_data, dict):
            return None
        raw_data = financial_data.get("raw_data", {})
        if not isinstance(raw_data, dict):
            return None
        info = raw_data.get("info", {})
        if not isinstance(info, dict):
            info = {}

        candidates: List[Any] = [
            info.get("earningsTimestamp"),
            info.get("earningsTimestampStart"),
            info.get("earningsTimestampEnd"),
            info.get("earningsDate"),
            raw_data.get("calendar"),
            raw_data.get("earnings_dates"),
        ]

        parsed_candidates: List[datetime] = []
        for candidate in candidates:
            parsed_candidates.extend(WatchPollingService._parse_earnings_candidates(candidate))

        if not parsed_candidates:
            return None

        today = datetime.now(timezone.utc).date()
        future_candidates = sorted(ts for ts in parsed_candidates if ts.date() >= today)
        if future_candidates:
            return future_candidates[0].isoformat()

        return sorted(parsed_candidates)[0].isoformat()

    @staticmethod
    def _parse_earnings_candidates(candidate: Any) -> List[datetime]:
        parsed: List[datetime] = []
        if candidate is None:
            return parsed

        if isinstance(candidate, dict):
            for key, value in candidate.items():
                if "earnings" not in str(key).lower():
                    continue
                parsed.extend(WatchPollingService._parse_earnings_candidates(value))
            return parsed

        if isinstance(candidate, (list, tuple, set, pd.Index, pd.Series)):
            for item in candidate:
                parsed.extend(WatchPollingService._parse_earnings_candidates(item))
            return parsed

        if isinstance(candidate, (int, float)):
            try:
                return [datetime.fromtimestamp(float(candidate), tz=timezone.utc)]
            except Exception:
                return []

        try:
            ts = pd.Timestamp(candidate)
        except Exception:
            return []

        if pd.isna(ts):
            return []
        if ts.tzinfo is None:
            ts = ts.tz_localize(timezone.utc)
        else:
            ts = ts.tz_convert(timezone.utc)
        return [ts.to_pydatetime()]


watch_polling_service = WatchPollingService()
