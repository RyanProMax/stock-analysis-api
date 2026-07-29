from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json

from src.data_provider.market_series import (
    FredSeriesProvider,
    MarketPoint,
    MarketSeriesCandidate,
    MarketSeriesSpec,
    YahooChartProvider,
)
from src.services.daily_market_pack_service import DailyMarketPackService
from src.services.market_data_query_cli import main as market_data_query_main


class FakeProvider:
    def __init__(
        self,
        name: str,
        candidates: dict[str, MarketSeriesCandidate] | None = None,
        failures: set[str] | None = None,
    ):
        self.name = name
        self.candidates = candidates or {}
        self.failures = failures or set()
        self.calls: list[str] = []

    def fetch(self, spec: MarketSeriesSpec, cutoff_at: datetime) -> MarketSeriesCandidate:
        assert cutoff_at.tzinfo is not None
        self.calls.append(spec.symbol)
        if spec.symbol in self.failures:
            raise RuntimeError(f"{self.name} unavailable")
        return self.candidates[spec.symbol]


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _candidate(
    provider: str,
    *,
    previous_date: str,
    previous: float,
    latest_date: str,
    latest: float,
) -> MarketSeriesCandidate:
    return MarketSeriesCandidate(
        provider=provider,
        source=f"https://example.com/{provider}",
        source_label=f"{provider} close",
        points=(
            MarketPoint(date=previous_date, value=previous),
            MarketPoint(date=latest_date, value=latest),
        ),
    )


def _strict_json(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(value)

    return json.loads(raw, parse_constant=reject_constant)


def test_daily_pack_uses_freshest_us_candidate_and_exposes_machine_fields():
    spec = MarketSeriesSpec(
        symbol="SPX",
        name="S&P 500",
        region="US",
        kind="index",
        identifiers={"fred": "SP500", "yahoo_finance": "^GSPC"},
    )
    fred = FakeProvider(
        "fred",
        {
            "SPX": _candidate(
                "fred",
                previous_date="2026-07-24",
                previous=6400,
                latest_date="2026-07-27",
                latest=6420,
            )
        },
    )
    yahoo = FakeProvider(
        "yahoo_finance",
        {
            "SPX": _candidate(
                "yahoo_finance",
                previous_date="2026-07-27",
                previous=6420,
                latest_date="2026-07-28",
                latest=6484.2,
            )
        },
    )
    service = DailyMarketPackService(
        providers={"fred": fred, "yahoo_finance": yahoo},
        series=[spec],
    )

    payload = service.collect(cutoff_at=datetime(2026, 7, 29, tzinfo=timezone.utc))

    assert payload["status"] == "ok"
    assert payload["request"]["persistence"] == "none"
    item = payload["data"]["markets"][0]
    assert item["provider"] == "yahoo_finance"
    assert item["as_of"] == "2026-07-28"
    assert item["latest_value"] == 6484.2
    assert item["previous_value"] == 6420
    assert item["change_ratio"] == 0.01
    assert item["display_change"] == "+1.00%"
    assert [attempt["status"] for attempt in item["provider_attempts"]] == ["ok", "ok"]


def test_cn_provider_falls_back_in_order_without_calling_later_sources():
    spec = MarketSeriesSpec(
        symbol="SSE",
        name="上证指数",
        region="CN",
        kind="index",
        identifiers={
            "tencent": "sh000001",
            "eastmoney": "1.000001",
            "yahoo_finance": "000001.SS",
        },
    )
    tencent = FakeProvider("tencent", failures={"SSE"})
    eastmoney = FakeProvider(
        "eastmoney",
        {
            "SSE": _candidate(
                "eastmoney",
                previous_date="2026-07-27",
                previous=3500,
                latest_date="2026-07-28",
                latest=3535,
            )
        },
    )
    yahoo = FakeProvider("yahoo_finance", failures={"SSE"})
    service = DailyMarketPackService(
        providers={
            "tencent": tencent,
            "eastmoney": eastmoney,
            "yahoo_finance": yahoo,
        },
        series=[spec],
    )

    payload = service.collect(cutoff_at=datetime(2026, 7, 29, tzinfo=timezone.utc))

    assert payload["status"] == "ok"
    assert payload["data"]["markets"][0]["provider"] == "eastmoney"
    assert tencent.calls == ["SSE"]
    assert eastmoney.calls == ["SSE"]
    assert yahoo.calls == []
    assert [
        attempt["status"] for attempt in payload["data"]["markets"][0]["provider_attempts"]
    ] == ["failed", "ok"]


def test_partial_pack_keeps_structured_provider_failures():
    us_spec = MarketSeriesSpec(
        symbol="SPX",
        name="S&P 500",
        region="US",
        kind="index",
        identifiers={"fred": "SP500", "yahoo_finance": "^GSPC"},
    )
    cn_spec = MarketSeriesSpec(
        symbol="SSE",
        name="上证指数",
        region="CN",
        kind="index",
        identifiers={"tencent": "sh000001"},
    )
    fred = FakeProvider(
        "fred",
        {
            "SPX": _candidate(
                "fred",
                previous_date="2026-07-27",
                previous=6400,
                latest_date="2026-07-28",
                latest=6410,
            )
        },
    )
    service = DailyMarketPackService(
        providers={
            "fred": fred,
            "yahoo_finance": FakeProvider("yahoo_finance", failures={"SPX"}),
            "tencent": FakeProvider("tencent", failures={"SSE"}),
        },
        series=[us_spec, cn_spec],
    )

    payload = service.collect(cutoff_at=datetime(2026, 7, 29, tzinfo=timezone.utc))

    assert payload["status"] == "partial"
    assert payload["summary"] == {"requested": 2, "succeeded": 1, "failed": 1}
    failure = payload["data"]["failures"][0]
    assert failure["symbol"] == "SSE"
    assert failure["status"] == "failed"
    assert failure["provider_attempts"][0]["provider"] == "tencent"


def test_cli_emits_strict_json_without_starting_http_service():
    spec = MarketSeriesSpec(
        symbol="DGS10",
        name="美国 10Y",
        region="US",
        kind="yield",
        identifiers={"fred": "DGS10"},
    )
    service = DailyMarketPackService(
        providers={
            "fred": FakeProvider(
                "fred",
                {
                    "DGS10": _candidate(
                        "fred",
                        previous_date="2026-07-27",
                        previous=4.20,
                        latest_date="2026-07-28",
                        latest=4.24,
                    )
                },
            )
        },
        series=[spec],
    )
    writer = StringIO()

    exit_code = market_data_query_main(
        [
            "daily-pack",
            "--cutoff-at",
            "2026-07-29T01:00:00Z",
            "--persistence",
            "none",
        ],
        writer=writer,
        service=service,
    )

    assert exit_code == 0
    payload = _strict_json(writer.getvalue())
    assert payload["schema_version"] == "market-data-query.v1"
    assert payload["data"]["markets"][0]["display_value"] == "4.24%"
    assert payload["data"]["markets"][0]["display_change"] == "+4 bp"


def test_yahoo_provider_excludes_a_daily_row_before_the_market_close_cutoff():
    timestamps = [
        datetime(2026, 7, 27, 13, 30, tzinfo=timezone.utc).timestamp(),
        datetime(2026, 7, 28, 13, 30, tzinfo=timezone.utc).timestamp(),
        datetime(2026, 7, 29, 13, 30, tzinfo=timezone.utc).timestamp(),
    ]
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [{"close": [4.20, 4.24, 4.30]}],
                    },
                }
            ]
        }
    }
    provider = YahooChartProvider(
        get=lambda *_args, **_kwargs: FakeResponse(payload),
    )
    spec = MarketSeriesSpec(
        symbol="DGS10",
        name="美国 10Y",
        region="US",
        kind="yield",
        identifiers={"yahoo_finance": "^TNX"},
    )

    candidate = provider.fetch(
        spec,
        datetime(2026, 7, 29, 13, 0, tzinfo=timezone.utc),
    )

    assert [point.date for point in candidate.points] == ["2026-07-27", "2026-07-28"]
    assert candidate.points[-1].value == 4.24


def test_fred_provider_excludes_the_cutoff_date():
    provider = FredSeriesProvider(
        get_text=lambda *_args, **_kwargs: (
            "DATE,DGS10\n" "2026-07-27,4.65\n" "2026-07-28,4.64\n" "2026-07-29,4.62\n"
        )
    )
    spec = MarketSeriesSpec(
        symbol="DGS10",
        name="美国 10Y",
        region="US",
        kind="yield",
        identifiers={"fred": "DGS10"},
    )

    candidate = provider.fetch(
        spec,
        datetime(2026, 7, 29, 13, 0, tzinfo=timezone.utc),
    )

    assert [point.date for point in candidate.points] == ["2026-07-27", "2026-07-28"]
    assert candidate.points[-1].value == 4.64
