from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.services.alpha_evaluate_cli import main as alpha_evaluate_cli_main
from src.services.alpha_evaluation_service import AlphaEvaluationService


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


def _run_cli(service: AlphaEvaluationService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = alpha_evaluate_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_alpha_evaluate_outputs_core_factor_metrics_and_sample_split(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [
            {"symbol": "300001", "name": "趋势科技", "market": "创业板"},
            {"symbol": "300002", "name": "反转科技", "market": "创业板"},
            {"symbol": "300003", "name": "震荡科技", "market": "创业板"},
        ],
        market="cn",
    )
    repository.upsert_daily_bars(
        "300001",
        _daily_rows([10, 10.1, 10.3, 10.6, 11.0, 11.4, 11.9, 12.5, 13.2, 14.0, 14.7, 15.5]),
        "test",
        market="cn",
    )
    repository.upsert_daily_bars(
        "300002",
        _daily_rows([20, 19.8, 19.5, 19.3, 19.1, 18.9, 18.8, 18.7, 18.9, 19.2, 19.6, 20.1]),
        "test",
        market="cn",
    )
    repository.upsert_daily_bars(
        "300003",
        _daily_rows([30, 30.2, 30.1, 30.4, 30.3, 30.8, 30.7, 31.0, 31.4, 31.2, 31.8, 32.1]),
        "test",
        market="cn",
    )
    service = AlphaEvaluationService(repository=repository)

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
        "--forward-windows",
        "1,3",
        "--quantiles",
        "2",
        "--cost-bps",
        "10",
    )

    assert exit_code == 0
    assert payload["status"] in {"ok", "partial"}
    assert payload["source"] == "alpha_evaluate"
    assert payload["summary"]["symbols"] == 3
    assert payload["summary"]["observations"] > 0
    evaluation = payload["evaluation"]
    assert evaluation["status"] in {"ok", "partial"}
    assert evaluation["candidate_id"] == "factor:momentum_5d"
    assert evaluation["forward_windows"] == [1, 3]
    assert set(evaluation["sample_split"]) == {"train", "validation", "out_of_sample"}
    assert evaluation["cost_model"] == {"type": "fixed_bps", "bps": 10.0}
    for metric in ("rank_ic_mean", "rank_ic_tstat", "quantile_spread", "turnover"):
        assert metric in evaluation["metrics"]
    assert "rank_ic_by_window" in evaluation["metrics"]
    assert "quantile_returns_by_window" in evaluation["metrics"]
    assert "cost_adjusted_quantile_spread" in evaluation["metrics"]
    json.dumps(payload, allow_nan=False)


def test_alpha_evaluate_reports_data_gaps_for_missing_forward_returns(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [{"symbol": "300004", "name": "短样本", "market": "创业板"}],
        market="cn",
    )
    repository.upsert_daily_bars(
        "300004",
        _daily_rows([10.0, 10.2, 10.4, 10.6, 10.8, 11.0]),
        "test",
        market="cn",
    )
    service = AlphaEvaluationService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--symbols",
        "300004",
        "--factor",
        "momentum_5d",
        "--start",
        "2026-05-08",
        "--end",
        "2026-05-12",
        "--forward-windows",
        "5",
    )

    assert exit_code == 0
    assert payload["status"] == "partial"
    assert payload["evaluation"]["status"] == "partial"
    assert payload["summary"]["data_gaps"]
    assert any("missing_forward_return" in gap for gap in payload["summary"]["data_gaps"])
    json.dumps(payload, allow_nan=False)


def test_alpha_evaluate_empty_universe_returns_empty_status(tmp_path):
    service = AlphaEvaluationService(repository=_repository(tmp_path))

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--universe",
        "etf",
        "--factor",
        "momentum_20d",
    )

    assert exit_code == 0
    assert payload["status"] == "empty"
    assert payload["summary"]["symbols"] == 0
    assert payload["summary"]["observations"] == 0
    assert payload["summary"]["data_gaps"] == ["empty_universe"]
    assert payload["evaluation"]["status"] == "empty"
    json.dumps(payload, allow_nan=False)
