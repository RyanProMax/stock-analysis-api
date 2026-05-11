from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.services.alpha_backtest_cli import main as alpha_backtest_cli_main
from src.services.alpha_backtest_service import AlphaBacktestService


def _daily_rows(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range(end="2026-05-12", periods=len(closes), freq="D")
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


def _seed_market(repository: MarketDataRepository, *, market: str = "cn") -> None:
    if market == "hk":
        symbols = [
            {"symbol": "HK.00700", "name": "Tencent", "market": "港股", "exchange": "HKEX"},
            {"symbol": "HK.09988", "name": "Alibaba", "market": "港股", "exchange": "HKEX"},
            {"symbol": "HK.03690", "name": "Meituan", "market": "港股", "exchange": "HKEX"},
        ]
        codes = ["HK.00700", "HK.09988", "HK.03690"]
        source = "HK_FutuOpenD"
    else:
        symbols = [
            {"symbol": "300001", "name": "趋势科技", "market": "创业板"},
            {"symbol": "300002", "name": "反转科技", "market": "创业板"},
            {"symbol": "300003", "name": "震荡科技", "market": "创业板"},
        ]
        codes = ["300001", "300002", "300003"]
        source = "test"
    repository.upsert_symbols(symbols, market=market)
    price_paths = [
        [10, 10.1, 10.3, 10.6, 11.0, 11.4, 11.9, 12.5, 13.2, 14.0, 14.7, 15.5],
        [20, 19.8, 19.5, 19.3, 19.1, 18.9, 18.8, 18.7, 18.9, 19.2, 19.6, 20.1],
        [30, 30.2, 30.1, 30.4, 30.3, 30.8, 30.7, 31.0, 31.4, 31.2, 31.8, 32.1],
    ]
    for code, closes in zip(codes, price_paths):
        repository.upsert_daily_bars(
            code,
            _daily_rows(closes),
            source,
            market=market,
            ts_code=code,
        )


def _run_cli(service: AlphaBacktestService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = alpha_backtest_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_alpha_backtest_outputs_summary_only_portfolio_metrics(tmp_path):
    repository = _repository(tmp_path)
    _seed_market(repository)
    service = AlphaBacktestService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--symbols",
        "300001,300002,300003",
        "--factor",
        "momentum_5d",
        "--start",
        "2026-05-04",
        "--end",
        "2026-05-10",
        "--top-n",
        "1",
        "--holding-period",
        "1",
    )

    assert exit_code == 0
    assert payload["status"] in {"ok", "partial"}
    assert payload["source"] == "alpha_backtest"
    assert payload["request"]["market"] == "cn"
    assert payload["request"]["top_n"] == 1
    assert payload["cost_model"]["type"] == "market_spec_bps"
    assert payload["summary"]["periods"] > 0
    assert payload["summary"]["orders_total"] > 0
    assert payload["summary"]["total_return"] is not None
    assert payload["summary"]["max_drawdown"] is not None
    assert payload["summary"]["turnover"] is not None
    assert payload["constraints"] == [
        "backtest_not_applied_to_runtime",
        "read_only_market_data",
        "no_broker_or_order_side_effects",
    ]
    assert "periods" not in payload
    json.dumps(payload, allow_nan=False)


def test_alpha_backtest_auto_excludes_immature_holding_period_tail(tmp_path):
    repository = _repository(tmp_path)
    _seed_market(repository)
    service = AlphaBacktestService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--symbols",
        "300001,300002,300003",
        "--factor",
        "momentum_5d",
        "--start",
        "2026-05-04",
        "--end",
        "2026-05-12",
        "--top-n",
        "1",
        "--holding-period",
        "3",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["summary"]["effective_end"] == "2026-05-09"
    assert payload["summary"]["data_gaps"] == []
    assert "periods" not in payload
    json.dumps(payload, allow_nan=False)


def test_alpha_backtest_include_details_is_explicit_opt_in(tmp_path):
    repository = _repository(tmp_path)
    _seed_market(repository, market="hk")
    service = AlphaBacktestService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "hk",
        "--symbols",
        "HK.00700,HK.09988,HK.03690",
        "--factor",
        "momentum_5d",
        "--start",
        "2026-05-04",
        "--end",
        "2026-05-10",
        "--top-n",
        "2",
        "--holding-period",
        "1",
        "--include-details",
    )

    assert exit_code == 0
    assert payload["request"]["market"] == "hk"
    assert payload["cost_model"]["market"] == "hk"
    assert payload["summary"]["periods"] > 0
    assert "periods" in payload
    assert payload["periods"][0]["selected_symbols"]
    json.dumps(payload, allow_nan=False)


def test_alpha_backtest_empty_universe_returns_empty_status(tmp_path):
    service = AlphaBacktestService(repository=_repository(tmp_path))

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--universe",
        "etf",
        "--factor",
        "momentum_5d",
    )

    assert exit_code == 0
    assert payload["status"] == "empty"
    assert payload["summary"]["periods"] == 0
    assert payload["summary"]["data_gaps"] == ["empty_universe"]
    assert payload["constraints"][0] == "backtest_not_applied_to_runtime"
    json.dumps(payload, allow_nan=False)
