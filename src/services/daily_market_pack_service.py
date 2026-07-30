"""One-shot, no-persistence market pack for scheduled daily reports."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import math
from typing import Any, Iterable, Mapping

from ..data_provider.market_series import (
    EastmoneyKlineProvider,
    FredSeriesProvider,
    MarketSeriesCandidate,
    MarketSeriesProvider,
    MarketSeriesSpec,
    TencentKlineProvider,
    YahooChartProvider,
)

SCHEMA_VERSION = "market-data-query.v1"
SOURCE = "market_data_query"

DAILY_MARKET_SERIES = (
    MarketSeriesSpec(
        symbol="SPX",
        name="S&P 500",
        region="US",
        kind="index",
        identifiers={"fred": "SP500", "yahoo_finance": "^GSPC"},
    ),
    MarketSeriesSpec(
        symbol="IXIC",
        name="NASDAQ",
        region="US",
        kind="index",
        identifiers={"fred": "NASDAQCOM", "yahoo_finance": "^IXIC"},
    ),
    MarketSeriesSpec(
        symbol="DJI",
        name="DOW",
        region="US",
        kind="index",
        identifiers={"fred": "DJIA", "yahoo_finance": "^DJI"},
    ),
    MarketSeriesSpec(
        symbol="DGS10",
        name="美国 10Y",
        region="US",
        kind="yield",
        identifiers={"fred": "DGS10", "yahoo_finance": "^TNX"},
    ),
    MarketSeriesSpec(
        symbol="SSE",
        name="上证指数",
        region="CN",
        kind="index",
        identifiers={
            "tencent": "sh000001",
            "eastmoney": "1.000001",
            "yahoo_finance": "000001.SS",
        },
    ),
    MarketSeriesSpec(
        symbol="SZSE",
        name="深证成指",
        region="CN",
        kind="index",
        identifiers={
            "tencent": "sz399001",
            "eastmoney": "0.399001",
            "yahoo_finance": "399001.SZ",
        },
    ),
    MarketSeriesSpec(
        symbol="CSI300",
        name="沪深 300",
        region="CN",
        kind="index",
        identifiers={
            "tencent": "sh000300",
            "eastmoney": "1.000300",
            "yahoo_finance": "000300.SS",
        },
    ),
    MarketSeriesSpec(
        symbol="CSI500",
        name="中证 500",
        region="CN",
        kind="index",
        identifiers={
            "tencent": "sh000905",
            "eastmoney": "1.000905",
            "yahoo_finance": "000905.SS",
        },
    ),
    MarketSeriesSpec(
        symbol="CHINEXT",
        name="创业板指",
        region="CN",
        kind="index",
        identifiers={
            "tencent": "sz399006",
            "eastmoney": "0.399006",
            "yahoo_finance": "399006.SZ",
        },
    ),
    MarketSeriesSpec(
        symbol="STAR50",
        name="科创 50",
        region="CN",
        kind="index",
        identifiers={
            "tencent": "sh000688",
            "eastmoney": "1.000688",
            "yahoo_finance": "000688.SS",
        },
    ),
)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {message}"[:500]


class DailyMarketPackService:
    def __init__(
        self,
        providers: Mapping[str, MarketSeriesProvider] | None = None,
        series: Iterable[MarketSeriesSpec] = DAILY_MARKET_SERIES,
    ):
        self.providers: Mapping[str, MarketSeriesProvider] = providers or {
            "fred": FredSeriesProvider(),
            "yahoo_finance": YahooChartProvider(),
            "tencent": TencentKlineProvider(),
            "eastmoney": EastmoneyKlineProvider(),
        }
        self.series = tuple(series)

    def collect(self, *, cutoff_at: datetime) -> dict[str, Any]:
        if cutoff_at.tzinfo is None:
            raise ValueError("cutoff_at must include a timezone")
        cutoff_utc = cutoff_at.astimezone(timezone.utc)

        markets_by_symbol: dict[str, dict[str, Any]] = {}
        failures_by_symbol: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(len(self.series), 6)) as executor:
            futures = {
                executor.submit(self._collect_one, spec, cutoff_utc): spec
                for spec in self.series
            }
            for future in as_completed(futures):
                spec = futures[future]
                try:
                    markets_by_symbol[spec.symbol] = future.result()
                except MarketSeriesUnavailable as exc:
                    failures_by_symbol[spec.symbol] = {
                        "symbol": spec.symbol,
                        "name": spec.name,
                        "region": spec.region,
                        "kind": spec.kind,
                        "status": "failed",
                        "error": str(exc),
                        "provider_attempts": exc.provider_attempts,
                    }

        markets = [
            markets_by_symbol[spec.symbol]
            for spec in self.series
            if spec.symbol in markets_by_symbol
        ]
        failures = [
            failures_by_symbol[spec.symbol]
            for spec in self.series
            if spec.symbol in failures_by_symbol
        ]
        succeeded = len(markets)
        failed = len(failures)
        status = "ok" if failed == 0 else "partial" if succeeded else "failed"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "source": SOURCE,
            "computed_at": _iso_utc(datetime.now(timezone.utc)),
            "request": {
                "operation": "daily_market_pack",
                "cutoff_at": _iso_utc(cutoff_utc),
                "persistence": "none",
            },
            "summary": {
                "requested": len(self.series),
                "succeeded": succeeded,
                "failed": failed,
            },
            "data": {
                "markets": markets,
                "failures": failures,
            },
        }

    def _collect_one(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
    ) -> dict[str, Any]:
        if spec.region == "US":
            candidate, attempts = self._collect_freshest(
                spec,
                cutoff_at,
                ("fred", "yahoo_finance"),
            )
        else:
            candidate, attempts = self._collect_first(
                spec,
                cutoff_at,
                ("tencent", "eastmoney", "yahoo_finance"),
            )
        return self._format_item(spec, candidate, attempts)

    def _collect_freshest(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
        provider_names: tuple[str, ...],
    ) -> tuple[MarketSeriesCandidate, list[dict[str, Any]]]:
        attempts_by_name: dict[str, dict[str, Any]] = {}
        candidates: list[MarketSeriesCandidate] = []
        available = [
            (name, self.providers[name])
            for name in provider_names
            if name in self.providers and spec.identifiers.get(name)
        ]
        with ThreadPoolExecutor(max_workers=max(len(available), 1)) as executor:
            futures = {
                executor.submit(provider.fetch, spec, cutoff_at): name
                for name, provider in available
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    candidate = future.result()
                    candidates.append(candidate)
                    attempts_by_name[name] = {
                        "provider": name,
                        "status": "ok",
                        "as_of": candidate.points[-1].date,
                    }
                except Exception as exc:
                    attempts_by_name[name] = {
                        "provider": name,
                        "status": "failed",
                        "error": _safe_error(exc),
                    }
        attempts = [
            attempts_by_name.get(
                name,
                {
                    "provider": name,
                    "status": "not_supported",
                    "error": "identifier or provider is not configured",
                },
            )
            for name in provider_names
        ]
        if not candidates:
            raise MarketSeriesUnavailable(spec.symbol, attempts)
        provider_priority = {name: index for index, name in enumerate(provider_names)}
        return (
            max(
                candidates,
                key=lambda candidate: (
                    candidate.points[-1].date,
                    -provider_priority[candidate.provider],
                ),
            ),
            attempts,
        )

    def _collect_first(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
        provider_names: tuple[str, ...],
    ) -> tuple[MarketSeriesCandidate, list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        for name in provider_names:
            provider = self.providers.get(name)
            if provider is None or not spec.identifiers.get(name):
                attempts.append(
                    {
                        "provider": name,
                        "status": "not_supported",
                        "error": "identifier or provider is not configured",
                    }
                )
                continue
            try:
                candidate = provider.fetch(spec, cutoff_at)
                attempts.append(
                    {
                        "provider": name,
                        "status": "ok",
                        "as_of": candidate.points[-1].date,
                    }
                )
                return candidate, attempts
            except Exception as exc:
                attempts.append(
                    {
                        "provider": name,
                        "status": "failed",
                        "error": _safe_error(exc),
                    }
                )
        raise MarketSeriesUnavailable(spec.symbol, attempts)

    @staticmethod
    def _format_item(
        spec: MarketSeriesSpec,
        candidate: MarketSeriesCandidate,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        previous, latest = candidate.points[-2:]
        change_value = round(latest.value - previous.value, 10)
        direction = (
            "flat"
            if math.isclose(change_value, 0.0, abs_tol=0.0001)
            else "up" if change_value > 0 else "down"
        )
        change_ratio = (
            round(change_value / previous.value, 10) if previous.value else None
        )
        unit = "percent" if spec.kind == "yield" else "points"
        display_value = (
            f"{latest.value:.2f}%" if spec.kind == "yield" else f"{latest.value:,.2f}"
        )
        if spec.kind == "yield":
            basis_points = change_value * 100
            display_change = f"{basis_points:+.0f} bp"
        else:
            display_change = (
                f"{change_ratio * 100:+.2f}%" if change_ratio is not None else "—"
            )
        return {
            "symbol": spec.symbol,
            "name": spec.name,
            "region": spec.region,
            "kind": spec.kind,
            "unit": unit,
            "latest_value": latest.value,
            "previous_value": previous.value,
            "change_value": change_value,
            "change_ratio": change_ratio,
            "display_value": display_value,
            "display_change": display_change,
            "direction": direction,
            "as_of": latest.date,
            "provider": candidate.provider,
            "source": candidate.source,
            "source_label": candidate.source_label,
            "provider_attempts": attempts,
        }


class MarketSeriesUnavailable(RuntimeError):
    def __init__(self, symbol: str, provider_attempts: list[dict[str, Any]]):
        self.provider_attempts = provider_attempts
        failed = [
            f"{item['provider']}={item.get('error', item['status'])}"
            for item in provider_attempts
        ]
        super().__init__(
            f"{symbol}: no complete provider candidate; {'; '.join(failed)}"
        )


daily_market_pack_service = DailyMarketPackService()
