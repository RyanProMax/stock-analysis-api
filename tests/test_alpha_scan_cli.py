from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.services.alpha_scan_cli import main as alpha_scan_cli_main
from src.services.alpha_scan_service import AlphaScanService


def _daily_rows(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range(end="2026-05-08", periods=len(closes), freq="D")
    volumes = volumes or [1000 + idx * 10 for idx in range(len(closes))]
    rows = []
    previous = None
    for date, close, volume in zip(dates, closes, volumes):
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "pre_close": previous,
                "volume": volume,
                "amount": close * volume,
                "turnover_rate": 1.0,
                "pe_ttm": 20.0,
                "pb": 2.0,
            }
        )
        previous = close
    return pd.DataFrame(rows)


def _repository(tmp_path) -> MarketDataRepository:
    return MarketDataRepository(str(tmp_path / "market.sqlite"))


def _run_cli(service: AlphaScanService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = alpha_scan_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_alpha_scan_ranks_candidates_from_local_daily_warehouse(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [
            {"symbol": "300001", "name": "强势科技", "market": "创业板"},
            {"symbol": "300002", "name": "弱势科技", "market": "创业板"},
        ],
        market="cn",
    )
    repository.upsert_daily_bars(
        "300001",
        _daily_rows([10, 10.2, 10.4, 10.8, 11.2, 11.8, 12.4, 13.1, 13.8, 14.6]),
        "test",
        market="cn",
    )
    repository.upsert_daily_bars(
        "300002",
        _daily_rows([20, 19.8, 19.6, 19.4, 19.2, 19.0, 18.8, 18.7, 18.6, 18.5]),
        "test",
        market="cn",
    )
    service = AlphaScanService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--symbols",
        "300001,300002",
        "--top",
        "2",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "alpha_scan"
    assert payload["summary"]["scanned"] == 2
    assert payload["summary"]["candidates"] == 2
    assert [item["symbol"] for item in payload["items"]] == ["300001", "300002"]
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][0]["score"] > payload["items"][1]["score"]
    assert "positive_momentum_5d" in payload["items"][0]["reasons"]
    json.dumps(payload, allow_nan=False)


def test_alpha_scan_empty_universe_returns_empty_status(tmp_path):
    service = AlphaScanService(repository=_repository(tmp_path))

    exit_code, payload = _run_cli(service, "--market", "cn", "--universe", "etf")

    assert exit_code == 0
    assert payload["status"] == "empty"
    assert payload["summary"]["scanned"] == 0
    assert payload["items"] == []


def test_alpha_scan_universe_all_filters_to_local_daily_coverage(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [
            {"symbol": "US.AAPL", "name": "Apple", "market": "美股", "exchange": "NASDAQ"},
            {"symbol": "US.EMPTY", "name": "No Daily", "market": "美股", "exchange": "NASDAQ"},
        ],
        market="us",
    )
    repository.upsert_daily_bars(
        "US.AAPL",
        _daily_rows([180, 181, 182, 183, 185, 187, 188, 190, 191, 193]),
        "US_FutuOpenD",
        market="us",
        ts_code="US.AAPL",
    )
    service = AlphaScanService(repository=repository)

    exit_code, payload = _run_cli(service, "--market", "us", "--universe", "all", "--top", "5")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["request"]["symbols"] == ["US.AAPL"]
    assert payload["summary"]["scanned"] == 1
    assert [item["symbol"] for item in payload["items"]] == ["US.AAPL"]


def test_alpha_scan_explicit_symbols_can_report_missing_daily_history(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [
            {"symbol": "US.AAPL", "name": "Apple", "market": "美股", "exchange": "NASDAQ"},
            {"symbol": "US.EMPTY", "name": "No Daily", "market": "美股", "exchange": "NASDAQ"},
        ],
        market="us",
    )
    repository.upsert_daily_bars(
        "US.AAPL",
        _daily_rows([180, 181, 182, 183, 185, 187, 188, 190, 191, 193]),
        "US_FutuOpenD",
        market="us",
        ts_code="US.AAPL",
    )
    service = AlphaScanService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "us",
        "--symbols",
        "US.AAPL,US.EMPTY",
        "--top",
        "5",
    )

    assert exit_code == 0
    assert payload["status"] == "partial"
    assert payload["summary"]["scanned"] == 2
    assert payload["summary"]["failed"] == 1
    assert [item["symbol"] for item in payload["items"]] == ["US.AAPL", "US.EMPTY"]
    assert payload["items"][1]["data_quality"] == "missing"
    assert "missing_daily_history" in payload["items"][1]["data_gaps"]


def test_alpha_scan_marks_insufficient_history_as_partial_without_score(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [{"symbol": "300003", "name": "新股", "market": "创业板"}],
        market="cn",
    )
    repository.upsert_daily_bars(
        "300003",
        _daily_rows([10.0, 10.1]),
        "test",
        market="cn",
    )
    service = AlphaScanService(repository=repository)

    exit_code, payload = _run_cli(service, "--market", "cn", "--symbols", "300003")

    assert exit_code == 0
    assert payload["status"] == "partial"
    assert payload["summary"]["partial"] == 1
    assert payload["items"][0]["score"] is None
    assert payload["items"][0]["data_quality"] == "partial"
    assert "insufficient_daily_history" in payload["items"][0]["data_gaps"]
    json.dumps(payload, allow_nan=False)


def test_alpha_scan_accepts_hk_symbols_from_local_daily_warehouse(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [
            {"symbol": "HK.00700", "name": "Tencent", "market": "港股", "exchange": "HKEX"},
            {"symbol": "HK.09988", "name": "Alibaba", "market": "港股", "exchange": "HKEX"},
        ],
        market="hk",
    )
    repository.upsert_daily_bars(
        "HK.00700",
        _daily_rows([300, 305, 310, 320, 335, 350, 365, 380, 395, 410]),
        "HK_FutuOpenD",
        market="hk",
        ts_code="HK.00700",
    )
    repository.upsert_daily_bars(
        "HK.09988",
        _daily_rows([100, 101, 100, 99, 98, 98, 97, 96, 96, 95]),
        "HK_FutuOpenD",
        market="hk",
        ts_code="HK.09988",
    )
    service = AlphaScanService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "hk",
        "--symbols",
        "HK.00700,HK.09988",
        "--top",
        "2",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["request"]["market"] == "hk"
    assert [item["symbol"] for item in payload["items"]] == ["HK.00700", "HK.09988"]
    assert payload["items"][0]["score"] > payload["items"][1]["score"]
