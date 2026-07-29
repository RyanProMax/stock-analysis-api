"""Stateless daily market-series providers.

These adapters fetch and normalize external series points. They deliberately do
not know about SQLite, report formatting, or provider fallback policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
import subprocess
import threading
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

UTC = timezone.utc
SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 StockAnalysisAPI/1.0",
}
FRED_CURL_LOCK = threading.Lock()


@dataclass(frozen=True)
class MarketPoint:
    date: str
    value: float


@dataclass(frozen=True)
class MarketSeriesSpec:
    symbol: str
    name: str
    region: str
    kind: str
    identifiers: Mapping[str, str]
    provider_scales: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketSeriesCandidate:
    provider: str
    source: str
    source_label: str
    points: tuple[MarketPoint, ...]


class MarketSeriesProvider(Protocol):
    name: str

    def fetch(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
    ) -> MarketSeriesCandidate: ...


GetRequest = Callable[..., Any]
TextRequest = Callable[..., str]


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("cutoff_at must include a timezone")
    return value.astimezone(UTC)


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _last_two(points: list[MarketPoint], label: str) -> tuple[MarketPoint, ...]:
    unique = {point.date: point for point in points}
    ordered = [unique[key] for key in sorted(unique)]
    if len(ordered) < 2:
        raise ValueError(f"{label}: fewer than two complete daily points")
    return tuple(ordered[-2:])


def _curl_text(
    url: str,
    *,
    params: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout: float,
) -> str:
    request_url = f"{url}?{urlencode(params)}"
    command = [
        "curl",
        "-L",
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        str(max(1, math.ceil(timeout))),
    ]
    for name, value in headers.items():
        command.extend(["--header", f"{name}: {value}"])
    command.append(request_url)
    with FRED_CURL_LOCK:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
    return result.stdout


class FredSeriesProvider:
    name = "fred"

    def __init__(
        self,
        get_text: TextRequest = _curl_text,
        timeout_seconds: float = 20.0,
    ):
        self._get_text = get_text
        self._timeout_seconds = timeout_seconds

    def fetch(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
    ) -> MarketSeriesCandidate:
        series_id = spec.identifiers.get(self.name)
        if not series_id:
            raise ValueError(f"{spec.symbol}: FRED identifier is not configured")

        cutoff_utc = _ensure_utc(cutoff_at)
        start = (cutoff_utc - timedelta(days=16)).date().isoformat()
        end = cutoff_utc.date().isoformat()
        csv = self._get_text(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={"id": series_id, "cosd": start, "coed": end},
            headers={},
            timeout=self._timeout_seconds,
        )

        points: list[MarketPoint] = []
        for line in csv.strip().splitlines()[1:]:
            date, _, raw_value = line.partition(",")
            value = _finite_float(raw_value)
            if date < end and value is not None:
                points.append(MarketPoint(date=date, value=value))

        return MarketSeriesCandidate(
            provider=self.name,
            source=f"https://fred.stlouisfed.org/series/{series_id}",
            source_label="FRED 日收盘",
            points=_last_two(points, series_id),
        )


class YahooChartProvider:
    name = "yahoo_finance"

    def __init__(self, get: GetRequest = requests.get, timeout_seconds: float = 20.0):
        self._get = get
        self._timeout_seconds = timeout_seconds

    def fetch(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
    ) -> MarketSeriesCandidate:
        ticker = spec.identifiers.get(self.name)
        if not ticker:
            raise ValueError(f"{spec.symbol}: Yahoo identifier is not configured")

        cutoff_utc = _ensure_utc(cutoff_at)
        params = {
            "period1": int((cutoff_utc - timedelta(days=32)).timestamp()),
            "period2": int(cutoff_utc.timestamp()),
            "interval": "1d",
        }
        errors: list[str] = []
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            url = f"https://{host}/v8/finance/chart/{requests.utils.quote(ticker, safe='')}"
            try:
                response = self._get(
                    url,
                    params=params,
                    headers=DEFAULT_HEADERS,
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                result = (payload.get("chart", {}).get("result") or [None])[0] or {}
                timestamps = result.get("timestamp") or []
                closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
                scale = float(spec.provider_scales.get(self.name, 1.0))
                market_timezone = SHANGHAI if spec.region == "CN" else NEW_YORK
                market_close_hour = 15 if spec.region == "CN" else 16
                points = []
                for index, raw_timestamp in enumerate(timestamps):
                    timestamp = _finite_float(raw_timestamp)
                    close = _finite_float(closes[index] if index < len(closes) else None)
                    if timestamp is None or close is None:
                        continue
                    market_date = datetime.fromtimestamp(timestamp, market_timezone).date()
                    completed_at = datetime.combine(
                        market_date,
                        datetime.min.time().replace(hour=market_close_hour),
                        tzinfo=market_timezone,
                    )
                    if completed_at.astimezone(UTC) > cutoff_utc:
                        continue
                    points.append(
                        MarketPoint(
                            date=market_date.isoformat(),
                            value=close * scale,
                        )
                    )
                return MarketSeriesCandidate(
                    provider=self.name,
                    source=f"{url}?{urlencode(params)}",
                    source_label="Yahoo Finance 日收盘",
                    points=_last_two(points, ticker),
                )
            except Exception as exc:
                errors.append(f"{host}: {type(exc).__name__}: {exc}")
        raise RuntimeError("; ".join(errors))


class TencentKlineProvider:
    name = "tencent"

    def __init__(self, get: GetRequest = requests.get, timeout_seconds: float = 20.0):
        self._get = get
        self._timeout_seconds = timeout_seconds

    def fetch(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
    ) -> MarketSeriesCandidate:
        ticker = spec.identifiers.get(self.name)
        if not ticker:
            raise ValueError(f"{spec.symbol}: Tencent identifier is not configured")

        cutoff_utc = _ensure_utc(cutoff_at)
        start = (cutoff_utc - timedelta(days=20)).date().isoformat()
        end = cutoff_utc.date().isoformat()
        params = {"param": f"{ticker},day,{start},{end},40,qfq"}
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        response = self._get(
            url,
            params=params,
            headers={
                **DEFAULT_HEADERS,
                "Referer": "https://gu.qq.com/",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", {}).get(ticker, {}).get("day") or []
        points = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 3:
                continue
            date = str(row[0])
            close = _finite_float(row[2])
            try:
                completed_at = datetime.fromisoformat(f"{date}T15:00:00").replace(tzinfo=SHANGHAI)
            except ValueError:
                continue
            if close is not None and completed_at.astimezone(UTC) <= cutoff_utc:
                points.append(MarketPoint(date=date, value=close))

        return MarketSeriesCandidate(
            provider=self.name,
            source=f"{url}?{urlencode(params)}",
            source_label="腾讯证券日收盘",
            points=_last_two(points, ticker),
        )


class EastmoneyKlineProvider:
    name = "eastmoney"

    def __init__(self, get: GetRequest = requests.get, timeout_seconds: float = 20.0):
        self._get = get
        self._timeout_seconds = timeout_seconds

    def fetch(
        self,
        spec: MarketSeriesSpec,
        cutoff_at: datetime,
    ) -> MarketSeriesCandidate:
        secid = spec.identifiers.get(self.name)
        if not secid:
            raise ValueError(f"{spec.symbol}: Eastmoney identifier is not configured")

        cutoff_utc = _ensure_utc(cutoff_at)
        start = (cutoff_utc - timedelta(days=20)).date().strftime("%Y%m%d")
        end = cutoff_utc.date().strftime("%Y%m%d")
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "beg": start,
            "end": end,
        }
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        response = self._get(
            url,
            params=params,
            headers={
                **DEFAULT_HEADERS,
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        rows = response.json().get("data", {}).get("klines") or []
        points = []
        for row in rows:
            columns = str(row).split(",")
            if len(columns) < 3:
                continue
            date = columns[0]
            close = _finite_float(columns[2])
            try:
                completed_at = datetime.fromisoformat(f"{date}T15:00:00").replace(tzinfo=SHANGHAI)
            except ValueError:
                continue
            if close is not None and completed_at.astimezone(UTC) <= cutoff_utc:
                points.append(MarketPoint(date=date, value=close))

        return MarketSeriesCandidate(
            provider=self.name,
            source=f"{url}?{urlencode(params)}",
            source_label="东方财富日收盘",
            points=_last_two(points, secid),
        )
