from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

import pandas as pd

from ..repositories import MarketDataRepository, market_data_repository


@dataclass(frozen=True)
class AlphaFeatureSnapshot:
    symbol: str
    as_of: str
    factor_values: dict
    score: float | None
    reasons: list[str]
    data_quality: str
    data_gaps: list[str]


class AlphaFeatureService:
    MIN_HISTORY_BARS = 5

    def __init__(self, repository: Optional[MarketDataRepository] = None):
        self.repository = repository or market_data_repository

    def build_features(self, *, symbol: str, market: str = "cn") -> AlphaFeatureSnapshot:
        normalized_symbol = str(symbol).strip().upper()
        daily = self.repository.load_daily_bars(normalized_symbol, market=market, limit=60)
        if daily is None or daily.empty:
            return AlphaFeatureSnapshot(
                symbol=normalized_symbol,
                as_of="",
                factor_values={"bars": 0},
                score=None,
                reasons=[],
                data_quality="missing",
                data_gaps=["missing_daily_history"],
            )

        df = daily.copy().sort_values("date").reset_index(drop=True)
        as_of = str(df.iloc[-1].get("date") or "")[:10]
        closes = pd.to_numeric(df.get("close"), errors="coerce")
        volumes = pd.to_numeric(df.get("volume"), errors="coerce")
        amounts = pd.to_numeric(df.get("amount"), errors="coerce")

        factor_values = {
            "bars": int(len(df)),
            "close": self._finite_or_none(closes.iloc[-1] if len(closes) else None),
            "momentum_5d": self._window_return(closes, 5),
            "momentum_20d": self._window_return(closes, 20),
            "volatility_5d": self._window_volatility(closes, 5),
            "volume_change_5d": self._window_return(volumes, 5),
            "average_amount_5d": self._rolling_mean(amounts, 5),
            "pct_chg_latest": self._latest_optional(df, "pct_chg"),
            "turnover_rate": self._latest_optional(df, "turnover_rate"),
            "pe_ttm": self._latest_optional(df, "pe_ttm"),
            "pb": self._latest_optional(df, "pb"),
        }

        if len(df) < self.MIN_HISTORY_BARS:
            return AlphaFeatureSnapshot(
                symbol=normalized_symbol,
                as_of=as_of,
                factor_values=factor_values,
                score=None,
                reasons=[],
                data_quality="partial",
                data_gaps=["insufficient_daily_history"],
            )

        score, reasons = self._score(factor_values)
        return AlphaFeatureSnapshot(
            symbol=normalized_symbol,
            as_of=as_of,
            factor_values=factor_values,
            score=score,
            reasons=reasons,
            data_quality="ok",
            data_gaps=[],
        )

    def _score(self, factors: dict) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 50.0
        momentum_5d = factors.get("momentum_5d")
        momentum_20d = factors.get("momentum_20d")
        volatility_5d = factors.get("volatility_5d")
        volume_change_5d = factors.get("volume_change_5d")
        pe_ttm = factors.get("pe_ttm")
        pb = factors.get("pb")

        if momentum_5d is not None:
            score += momentum_5d * 100.0
            if momentum_5d > 0:
                reasons.append("positive_momentum_5d")
            elif momentum_5d < 0:
                reasons.append("negative_momentum_5d")
        if momentum_20d is not None:
            score += momentum_20d * 50.0
        if volume_change_5d is not None:
            score += min(max(volume_change_5d, -1.0), 2.0) * 5.0
            if volume_change_5d > 0.2:
                reasons.append("volume_expansion")
        if volatility_5d is not None:
            score -= volatility_5d * 20.0
            if volatility_5d > 0.05:
                reasons.append("high_short_term_volatility")
        if pe_ttm is not None and pe_ttm > 80:
            score -= 5.0
            reasons.append("valuation_rich")
        if pb is not None and pb > 10:
            score -= 3.0

        return round(score, 6), reasons

    def _window_return(self, series: pd.Series, window: int) -> float | None:
        if len(series) <= window:
            return None
        current = self._finite_or_none(series.iloc[-1])
        previous = self._finite_or_none(series.iloc[-1 - window])
        if current is None or previous in (None, 0):
            return None
        return (current - previous) / previous

    def _window_volatility(self, series: pd.Series, window: int) -> float | None:
        if len(series) < window:
            return None
        returns = series.astype(float).pct_change().tail(window)
        value = returns.std()
        return self._finite_or_none(value)

    def _rolling_mean(self, series: pd.Series, window: int) -> float | None:
        if len(series) < window:
            return None
        return self._finite_or_none(series.tail(window).mean())

    def _latest_optional(self, df: pd.DataFrame, column: str) -> float | None:
        if column not in df.columns or df.empty:
            return None
        return self._finite_or_none(df.iloc[-1].get(column))

    def _finite_or_none(self, value) -> float | None:
        if value in (None, ""):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
