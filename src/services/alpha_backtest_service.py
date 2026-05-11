from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Optional, Sequence

import pandas as pd

from ..model.market import get_market_spec
from ..model.serialization import json_safe
from ..repositories import MarketDataRepository, market_data_repository
from .alpha_evaluation_service import AlphaEvaluationService
from .alpha_universe_service import AlphaUniverseService

BACKTEST_CONSTRAINTS = [
    "backtest_not_applied_to_runtime",
    "read_only_market_data",
    "no_broker_or_order_side_effects",
]


class AlphaBacktestService:
    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        universe_service: Optional[AlphaUniverseService] = None,
        evaluation_service: Optional[AlphaEvaluationService] = None,
    ) -> None:
        self.repository = repository or market_data_repository
        self.universe_service = universe_service or AlphaUniverseService(self.repository)
        self.evaluation_service = evaluation_service or AlphaEvaluationService(
            repository=self.repository,
            universe_service=self.universe_service,
        )

    def backtest(
        self,
        *,
        market: str = "cn",
        universe: str = "all",
        symbols: str | Sequence[str] | None = None,
        factor: str = "momentum_20d",
        start: str | None = None,
        end: str | None = None,
        top_n: int = 10,
        holding_period: int = 1,
        cost_bps: float | None = None,
        include_details: bool = False,
    ) -> dict:
        normalized_market = str(market or "cn").strip().lower()
        normalized_universe = str(universe or "all").strip().lower()
        normalized_factor = str(factor or "momentum_20d").strip()
        normalized_top_n = max(int(top_n or 10), 1)
        normalized_holding_period = max(int(holding_period or 1), 1)
        resolved_cost_bps, cost_model = self._resolve_cost_model(
            market=normalized_market,
            cost_bps=cost_bps,
        )

        built_universe = self.universe_service.build_universe(
            market=normalized_market,
            universe=normalized_universe,
            symbols=symbols,
        )
        symbols_list = [
            str(row.get("symbol") or "").strip().upper()
            for row in built_universe.symbols
            if str(row.get("symbol") or "").strip()
        ]
        if not symbols_list:
            return self._payload(
                status="empty",
                market=normalized_market,
                universe=normalized_universe,
                symbols=[],
                factor=normalized_factor,
                start=start,
                end=end,
                top_n=normalized_top_n,
                holding_period=normalized_holding_period,
                cost_bps=resolved_cost_bps,
                cost_model=cost_model,
                summary=self._empty_summary(["empty_universe"]),
                periods=[],
                include_details=include_details,
            )

        frame, data_gaps = self.evaluation_service._build_observation_frame(
            symbols=symbols_list,
            market=normalized_market,
            factor=normalized_factor,
            start=start,
            end=end,
            windows=(normalized_holding_period,),
        )
        periods = self._periods(
            frame=frame,
            holding_period=normalized_holding_period,
            top_n=normalized_top_n,
            cost_bps=resolved_cost_bps,
        )
        summary = self._summary(periods=periods, data_gaps=data_gaps)
        status = "ok"
        if not periods:
            status = "empty"
            if "empty_backtest_periods" not in data_gaps:
                data_gaps = [*data_gaps, "empty_backtest_periods"]
            summary = self._empty_summary(data_gaps)
        elif data_gaps:
            status = "partial"
        return self._payload(
            status=status,
            market=normalized_market,
            universe=normalized_universe,
            symbols=symbols_list,
            factor=normalized_factor,
            start=start,
            end=end,
            top_n=normalized_top_n,
            holding_period=normalized_holding_period,
            cost_bps=resolved_cost_bps,
            cost_model=cost_model,
            summary=summary,
            periods=periods,
            include_details=include_details,
        )

    def _periods(
        self,
        *,
        frame: pd.DataFrame,
        holding_period: int,
        top_n: int,
        cost_bps: float,
    ) -> list[dict]:
        column = f"forward_{holding_period}d"
        if frame.empty or column not in frame.columns:
            return []
        periods: list[dict] = []
        previous_symbols: set[str] | None = None
        for date, group in frame.dropna(subset=["factor", column]).groupby("date", sort=True):
            ranked = group.sort_values("factor", ascending=False).head(top_n)
            if ranked.empty:
                continue
            selected = [str(symbol) for symbol in ranked["symbol"].astype(str).tolist()]
            selected_set = set(selected)
            if previous_symbols is None:
                turnover = 1.0
                buys = len(selected_set)
                sells = 0
            else:
                overlap = len(previous_symbols & selected_set)
                turnover = 1.0 - overlap / max(len(previous_symbols), 1)
                buys = len(selected_set - previous_symbols)
                sells = len(previous_symbols - selected_set)
            gross_return = self._mean([float(value) for value in ranked[column].tolist()])
            cost_return = turnover * cost_bps / 10000.0
            net_return = None if gross_return is None else gross_return - cost_return
            periods.append(
                {
                    "date": str(date),
                    "selected_symbols": selected,
                    "gross_return": self._round(gross_return),
                    "cost_return": self._round(cost_return),
                    "net_return": self._round(net_return),
                    "turnover": self._round(turnover),
                    "orders": {"buy": buys, "sell": sells, "total": buys + sells},
                }
            )
            previous_symbols = selected_set
        return periods

    def _summary(self, *, periods: list[dict], data_gaps: list[str]) -> dict:
        net_returns = [
            float(period["net_return"])
            for period in periods
            if period.get("net_return") is not None
        ]
        gross_returns = [
            float(period["gross_return"])
            for period in periods
            if period.get("gross_return") is not None
        ]
        equity = 1.0
        equity_curve: list[float] = []
        for value in net_returns:
            equity *= 1.0 + value
            equity_curve.append(equity)
        total_return = equity - 1.0 if net_returns else None
        return {
            "periods": len(periods),
            "effective_end": str(periods[-1]["date"]) if periods else None,
            "orders_total": sum(
                int(period.get("orders", {}).get("total") or 0) for period in periods
            ),
            "gross_return_mean": self._round(self._mean(gross_returns)),
            "net_return_mean": self._round(self._mean(net_returns)),
            "total_return": self._round(total_return),
            "annualized_return": self._round(
                self._annualized_return(total_return, len(net_returns))
            ),
            "max_drawdown": self._round(self._max_drawdown(equity_curve)),
            "sharpe": self._round(self._sharpe(net_returns)),
            "turnover": self._round(
                self._mean(
                    [
                        float(period["turnover"])
                        for period in periods
                        if period.get("turnover") is not None
                    ]
                )
            ),
            "win_rate": self._round(
                sum(1 for value in net_returns if value > 0) / len(net_returns)
                if net_returns
                else None
            ),
            "data_gaps": data_gaps,
        }

    def _empty_summary(self, data_gaps: list[str]) -> dict:
        return {
            "periods": 0,
            "effective_end": None,
            "orders_total": 0,
            "gross_return_mean": None,
            "net_return_mean": None,
            "total_return": None,
            "annualized_return": None,
            "max_drawdown": None,
            "sharpe": None,
            "turnover": None,
            "win_rate": None,
            "data_gaps": data_gaps,
        }

    def _payload(
        self,
        *,
        status: str,
        market: str,
        universe: str,
        symbols: list[str],
        factor: str,
        start: str | None,
        end: str | None,
        top_n: int,
        holding_period: int,
        cost_bps: float,
        cost_model: dict,
        summary: dict,
        periods: list[dict],
        include_details: bool,
    ) -> dict:
        payload = {
            "status": status,
            "source": "alpha_backtest",
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "request": {
                "market": market,
                "universe": universe,
                "symbols": symbols,
                "factor": factor,
                "start": start,
                "end": end,
                "top_n": top_n,
                "holding_period": holding_period,
                "cost_bps": cost_bps,
            },
            "cost_model": cost_model,
            "summary": summary,
            "constraints": list(BACKTEST_CONSTRAINTS),
        }
        if include_details:
            payload["periods"] = periods
        return json_safe(payload)

    def _resolve_cost_model(
        self,
        *,
        market: str,
        cost_bps: float | None,
    ) -> tuple[float, dict]:
        if cost_bps is not None:
            normalized = float(cost_bps)
            return normalized, {"type": "fixed_bps", "bps": normalized}
        spec = get_market_spec(market)
        return spec.round_trip_cost_bps, spec.to_cost_model()

    def _mean(self, values: list[float]) -> float | None:
        finite = [float(value) for value in values if self._is_finite(value)]
        if not finite:
            return None
        return sum(finite) / len(finite)

    def _annualized_return(self, total_return: float | None, periods: int) -> float | None:
        if total_return is None or periods <= 0 or total_return <= -1:
            return None
        return (1.0 + total_return) ** (252.0 / periods) - 1.0

    def _max_drawdown(self, equity_curve: list[float]) -> float | None:
        if not equity_curve:
            return None
        peak = equity_curve[0]
        max_drawdown = 0.0
        for value in equity_curve:
            peak = max(peak, value)
            if peak:
                max_drawdown = min(max_drawdown, value / peak - 1.0)
        return max_drawdown

    def _sharpe(self, returns: list[float]) -> float | None:
        finite = [float(value) for value in returns if self._is_finite(value)]
        if len(finite) < 2:
            return None
        series = pd.Series(finite, dtype=float)
        std = series.std(ddof=1)
        if not self._is_finite(std) or std == 0:
            return None
        return float(series.mean() / std * math.sqrt(252))

    def _round(self, value) -> float | None:
        if not self._is_finite(value):
            return None
        return round(float(value), 8)

    def _is_finite(self, value) -> bool:
        if value in (None, ""):
            return False
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(parsed)
