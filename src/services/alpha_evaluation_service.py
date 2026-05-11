from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Optional, Sequence

import pandas as pd

from ..model.alpha import AlphaEvaluation
from ..model.market import get_market_spec
from ..model.serialization import json_safe
from ..repositories import MarketDataRepository, market_data_repository
from .alpha_universe_service import AlphaUniverseService


class AlphaEvaluationService:
    DEFAULT_FORWARD_WINDOWS = (1, 5, 20)
    SUPPORTED_FACTORS = {
        "momentum_5d",
        "momentum_20d",
        "volatility_5d",
        "volume_change_5d",
        "turnover_rate",
        "pe_ttm",
        "pb",
        "pct_chg",
    }

    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        universe_service: Optional[AlphaUniverseService] = None,
    ):
        self.repository = repository or market_data_repository
        self.universe_service = universe_service or AlphaUniverseService(self.repository)

    def evaluate(
        self,
        *,
        market: str = "cn",
        universe: str = "all",
        symbols: str | Sequence[str] | None = None,
        factor: str = "momentum_20d",
        start: str | None = None,
        end: str | None = None,
        forward_windows: Sequence[int] | None = None,
        quantiles: int = 5,
        cost_bps: float | None = None,
    ) -> dict:
        normalized_market = str(market or "cn").strip().lower()
        normalized_universe = str(universe or "all").strip().lower()
        normalized_factor = str(factor or "").strip()
        if not normalized_factor:
            raise ValueError("factor is required")
        if normalized_factor not in self.SUPPORTED_FACTORS:
            raise ValueError(f"unsupported factor: {normalized_factor}")
        windows = self._normalize_forward_windows(forward_windows)
        normalized_quantiles = max(int(quantiles or 5), 2)
        normalized_cost_bps, cost_model = self._resolve_cost_model(
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
            evaluation = self._empty_evaluation(
                factor=normalized_factor,
                as_of=end or self._today(),
                windows=windows,
                cost_bps=normalized_cost_bps,
                cost_model=cost_model,
                status="empty",
                data_gaps=["empty_universe"],
            )
            return self._payload(
                status="empty",
                market=normalized_market,
                universe=normalized_universe,
                symbols=[],
                factor=normalized_factor,
                start=start,
                end=end,
                windows=windows,
                quantiles=normalized_quantiles,
                cost_bps=normalized_cost_bps,
                evaluation=evaluation,
                observations=0,
                data_gaps=["empty_universe"],
                effective_end=None,
            )

        frame, data_gaps = self._build_observation_frame(
            symbols=symbols_list,
            market=normalized_market,
            factor=normalized_factor,
            start=start,
            end=end,
            windows=windows,
        )
        metrics = self._compute_metrics(
            frame=frame,
            windows=windows,
            quantiles=normalized_quantiles,
            cost_bps=normalized_cost_bps,
        )
        sample_split = self._sample_split(frame)
        status = "ok"
        if data_gaps or frame.empty:
            status = "partial"
        effective_end = self._frame_as_of(frame)
        as_of = effective_end or end or self._today()
        evaluation = AlphaEvaluation(
            evaluation_id=f"alpha-eval-{as_of}-{normalized_factor}",
            candidate_id=f"factor:{normalized_factor}",
            method="factor_forward_returns",
            as_of=as_of,
            forward_windows=list(windows),
            metrics=metrics,
            sample_split=sample_split,
            cost_model=cost_model,
            data_gaps=data_gaps,
            status=status,
        ).to_dict()
        return self._payload(
            status=status,
            market=normalized_market,
            universe=normalized_universe,
            symbols=symbols_list,
            factor=normalized_factor,
            start=start,
            end=end,
            windows=windows,
            quantiles=normalized_quantiles,
            cost_bps=normalized_cost_bps,
            evaluation=evaluation,
            observations=int(len(frame)),
            data_gaps=data_gaps,
            effective_end=effective_end,
        )

    def _build_observation_frame(
        self,
        *,
        symbols: list[str],
        market: str,
        factor: str,
        start: str | None,
        end: str | None,
        windows: tuple[int, ...],
    ) -> tuple[pd.DataFrame, list[str]]:
        frames: list[pd.DataFrame] = []
        data_gaps: list[str] = []
        for symbol in symbols:
            daily = self.repository.load_daily_bars(symbol, market=market)
            if daily is None or daily.empty:
                data_gaps.append(f"symbol:{symbol}:missing_daily_history")
                continue
            symbol_frame, symbol_gaps = self._symbol_observations(
                daily=daily,
                symbol=symbol,
                factor=factor,
                start=start,
                end=end,
                windows=windows,
            )
            data_gaps.extend(symbol_gaps)
            if not symbol_frame.empty:
                frames.append(symbol_frame)
        if not frames:
            columns = ["date", "symbol", "factor"] + [f"forward_{window}d" for window in windows]
            return pd.DataFrame(columns=columns), self._dedupe_gaps(data_gaps)
        return pd.concat(frames, ignore_index=True), self._dedupe_gaps(data_gaps)

    def _symbol_observations(
        self,
        *,
        daily: pd.DataFrame,
        symbol: str,
        factor: str,
        start: str | None,
        end: str | None,
        windows: tuple[int, ...],
    ) -> tuple[pd.DataFrame, list[str]]:
        df = daily.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        if df.empty:
            return pd.DataFrame(), [f"symbol:{symbol}:missing_daily_history"]

        closes = pd.to_numeric(df.get("close"), errors="coerce")
        df["factor"] = self._factor_series(df, factor)
        for window in windows:
            df[f"forward_{window}d"] = closes.shift(-window) / closes - 1.0

        effective_end = self._effective_end(df, requested_end=end, windows=windows)
        mask = pd.Series(True, index=df.index)
        if start:
            mask &= df["date"] >= pd.to_datetime(start)
        if effective_end is not None:
            mask &= df["date"] <= effective_end
        selected = df.loc[mask].copy()
        selected["symbol"] = symbol
        selected["date"] = selected["date"].dt.strftime("%Y-%m-%d")

        gaps: list[str] = []
        finite_factor = selected["factor"].map(self._is_finite)
        if not bool(finite_factor.any()):
            gaps.append(f"symbol:{symbol}:missing_factor:{factor}")
        selected = selected.loc[finite_factor].copy()
        for window in windows:
            column = f"forward_{window}d"
            if column not in selected.columns:
                gaps.append(f"window:{window}d:missing_forward_return")
                continue
            finite_forward = selected[column].map(self._is_finite)
            if not bool(finite_forward.any()):
                gaps.append(f"window:{window}d:missing_forward_return")
            elif int((~finite_forward).sum()) > 0:
                gaps.append(
                    f"window:{window}d:partial_missing_forward_return:{int((~finite_forward).sum())}"
                )

        columns = ["date", "symbol", "factor"] + [f"forward_{window}d" for window in windows]
        return selected[columns].reset_index(drop=True), gaps

    def _effective_end(
        self,
        df: pd.DataFrame,
        *,
        requested_end: str | None,
        windows: tuple[int, ...],
    ) -> pd.Timestamp | None:
        if df.empty or "date" not in df:
            return pd.to_datetime(requested_end) if requested_end else None
        requested = pd.to_datetime(requested_end) if requested_end else None
        max_window = max(windows) if windows else 0
        if max_window <= 0 or len(df) <= max_window:
            return requested
        last_mature = df["date"].iloc[len(df) - max_window - 1]
        if requested is None:
            return last_mature
        return min(requested, last_mature)

    def _factor_series(self, df: pd.DataFrame, factor: str) -> pd.Series:
        closes = pd.to_numeric(df.get("close"), errors="coerce")
        volumes = pd.to_numeric(df.get("volume"), errors="coerce")
        if factor == "momentum_5d":
            return closes / closes.shift(5) - 1.0
        if factor == "momentum_20d":
            return closes / closes.shift(20) - 1.0
        if factor == "volatility_5d":
            return closes.pct_change().rolling(5).std()
        if factor == "volume_change_5d":
            return volumes / volumes.shift(5) - 1.0
        if factor in {"turnover_rate", "pe_ttm", "pb", "pct_chg"}:
            return pd.to_numeric(df.get(factor), errors="coerce")
        raise ValueError(f"unsupported factor: {factor}")

    def _compute_metrics(
        self,
        *,
        frame: pd.DataFrame,
        windows: tuple[int, ...],
        quantiles: int,
        cost_bps: float,
    ) -> dict:
        rank_ic_by_window: dict[str, dict] = {}
        ic_by_window: dict[str, dict] = {}
        quantile_returns_by_window: dict[str, dict] = {}
        quantile_spread_by_window: dict[str, float | None] = {}
        all_rank_ic: list[float] = []
        primary_window = windows[0]

        for window in windows:
            column = f"forward_{window}d"
            valid = (
                frame.dropna(subset=["factor", column])
                if column in frame.columns
                else frame.iloc[0:0]
            )
            rank_values = self._daily_correlations(valid, column=column, method="spearman")
            ic_values = self._daily_correlations(valid, column=column, method="pearson")
            all_rank_ic.extend(rank_values)
            rank_ic_by_window[str(window)] = {
                "mean": self._mean(rank_values),
                "tstat": self._tstat(rank_values),
                "count": len(rank_values),
            }
            ic_by_window[str(window)] = {
                "mean": self._mean(ic_values),
                "tstat": self._tstat(ic_values),
                "count": len(ic_values),
            }
            qframe = self._with_quantiles(valid, quantiles=quantiles)
            quantile_returns = self._quantile_returns(qframe, column=column)
            quantile_returns_by_window[str(window)] = quantile_returns
            quantile_spread_by_window[str(window)] = self._quantile_spread(quantile_returns)

        primary_spread = quantile_spread_by_window.get(str(primary_window))
        round_trip_cost = 2.0 * cost_bps / 10000.0
        return json_safe(
            {
                "rank_ic_mean": self._mean(all_rank_ic),
                "rank_ic_tstat": self._tstat(all_rank_ic),
                "rank_ic_by_window": rank_ic_by_window,
                "ic_by_window": ic_by_window,
                "quantile_returns_by_window": quantile_returns_by_window,
                "quantile_spread": primary_spread,
                "quantile_spread_by_window": quantile_spread_by_window,
                "cost_adjusted_quantile_spread": (
                    self._round(primary_spread - round_trip_cost)
                    if primary_spread is not None
                    else None
                ),
                "turnover": self._turnover(frame, quantiles=quantiles),
            }
        )

    def _daily_correlations(self, frame: pd.DataFrame, *, column: str, method: str) -> list[float]:
        values: list[float] = []
        if frame.empty:
            return values
        for _, group in frame.groupby("date"):
            if len(group) < 2 or group["factor"].nunique(dropna=True) < 2:
                continue
            correlation = group["factor"].corr(group[column], method=method)
            if self._is_finite(correlation):
                values.append(float(correlation))
        return values

    def _with_quantiles(self, frame: pd.DataFrame, *, quantiles: int) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        if frame.empty:
            return frame.copy()
        for _, group in frame.groupby("date"):
            usable_quantiles = min(quantiles, int(group["factor"].nunique(dropna=True)), len(group))
            if usable_quantiles < 2:
                continue
            current = group.copy()
            try:
                ranked = current["factor"].rank(method="first")
                current["quantile"] = pd.qcut(
                    ranked,
                    q=usable_quantiles,
                    labels=list(range(1, usable_quantiles + 1)),
                ).astype(int)
            except ValueError:
                continue
            parts.append(current)
        if not parts:
            result = frame.iloc[0:0].copy()
            result["quantile"] = None
            return result
        return pd.concat(parts, ignore_index=True)

    def _quantile_returns(self, frame: pd.DataFrame, *, column: str) -> dict[str, float]:
        if frame.empty or "quantile" not in frame.columns:
            return {}
        valid = frame.dropna(subset=["quantile", column])
        if valid.empty:
            return {}
        grouped = valid.groupby("quantile")[column].mean()
        return {str(int(quantile)): self._round(value) for quantile, value in grouped.items()}

    def _quantile_spread(self, quantile_returns: dict[str, float]) -> float | None:
        if len(quantile_returns) < 2:
            return None
        keys = sorted(int(key) for key in quantile_returns)
        low = quantile_returns.get(str(keys[0]))
        high = quantile_returns.get(str(keys[-1]))
        if low is None or high is None:
            return None
        return self._round(high - low)

    def _turnover(self, frame: pd.DataFrame, *, quantiles: int) -> float | None:
        qframe = self._with_quantiles(frame.dropna(subset=["factor"]), quantiles=quantiles)
        if qframe.empty or "quantile" not in qframe.columns:
            return None
        previous: set[str] | None = None
        values: list[float] = []
        for _, group in qframe.groupby("date", sort=True):
            top_quantile = group["quantile"].max()
            current = set(group.loc[group["quantile"] == top_quantile, "symbol"].astype(str))
            if previous:
                values.append(1.0 - len(previous & current) / max(len(previous), 1))
            previous = current
        return self._mean(values)

    def _sample_split(self, frame: pd.DataFrame) -> dict[str, dict]:
        dates = (
            sorted(str(date) for date in frame["date"].dropna().unique()) if "date" in frame else []
        )
        if not dates:
            return {
                "train": {"start": None, "end": None, "observations": 0},
                "validation": {"start": None, "end": None, "observations": 0},
                "out_of_sample": {"start": None, "end": None, "observations": 0},
            }

        train_end = max(1, math.ceil(len(dates) * 0.6))
        validation_end = max(train_end, math.ceil(len(dates) * 0.8))
        sections = {
            "train": dates[:train_end],
            "validation": dates[train_end:validation_end],
            "out_of_sample": dates[validation_end:],
        }
        return {
            name: {
                "start": values[0] if values else None,
                "end": values[-1] if values else None,
                "observations": int(frame[frame["date"].isin(values)].shape[0]) if values else 0,
            }
            for name, values in sections.items()
        }

    def _empty_evaluation(
        self,
        *,
        factor: str,
        as_of: str,
        windows: tuple[int, ...],
        cost_bps: float,
        cost_model: dict,
        status: str,
        data_gaps: list[str],
    ) -> dict:
        return AlphaEvaluation(
            evaluation_id=f"alpha-eval-{as_of}-{factor}",
            candidate_id=f"factor:{factor}",
            method="factor_forward_returns",
            as_of=as_of,
            forward_windows=list(windows),
            metrics={
                "rank_ic_mean": None,
                "rank_ic_tstat": None,
                "rank_ic_by_window": {},
                "ic_by_window": {},
                "quantile_returns_by_window": {},
                "quantile_spread": None,
                "quantile_spread_by_window": {},
                "cost_adjusted_quantile_spread": None,
                "turnover": None,
            },
            sample_split=self._sample_split(pd.DataFrame(columns=["date"])),
            cost_model=cost_model,
            data_gaps=data_gaps,
            status=status,
        ).to_dict()

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
        windows: tuple[int, ...],
        quantiles: int,
        cost_bps: float,
        evaluation: dict,
        observations: int,
        data_gaps: list[str],
        effective_end: str | None,
    ) -> dict:
        return json_safe(
            {
                "status": status,
                "source": "alpha_evaluate",
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "request": {
                    "market": market,
                    "universe": universe,
                    "symbols": symbols,
                    "factor": factor,
                    "start": start,
                    "end": end,
                    "forward_windows": list(windows),
                    "quantiles": quantiles,
                    "cost_bps": cost_bps,
                },
                "summary": {
                    "symbols": len(symbols),
                    "observations": observations,
                    "effective_end": effective_end,
                    "data_gaps": data_gaps,
                },
                "evaluation": evaluation,
            }
        )

    def _normalize_forward_windows(self, windows: Sequence[int] | None) -> tuple[int, ...]:
        raw = windows or self.DEFAULT_FORWARD_WINDOWS
        normalized = tuple(sorted({int(window) for window in raw if int(window) > 0}))
        if not normalized:
            raise ValueError("forward_windows must not be empty")
        return normalized

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

    def _dedupe_gaps(self, gaps: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for gap in gaps:
            if gap in seen:
                continue
            seen.add(gap)
            deduped.append(gap)
        return deduped

    def _frame_as_of(self, frame: pd.DataFrame) -> str | None:
        if frame.empty or "date" not in frame.columns:
            return None
        return str(frame["date"].max())

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _mean(self, values: list[float]) -> float | None:
        finite = [float(value) for value in values if self._is_finite(value)]
        if not finite:
            return None
        return self._round(sum(finite) / len(finite))

    def _tstat(self, values: list[float]) -> float | None:
        finite = [float(value) for value in values if self._is_finite(value)]
        if len(finite) < 2:
            return None
        series = pd.Series(finite, dtype=float)
        std = series.std(ddof=1)
        if not self._is_finite(std) or std == 0:
            return None
        return self._round(series.mean() / (std / math.sqrt(len(series))))

    def _round(self, value) -> float | None:
        if not self._is_finite(value):
            return None
        return round(float(value), 8)

    def _is_finite(self, value) -> bool:
        if value in (None, ""):
            return False
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False
