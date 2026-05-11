from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.services.alpha_daily_report_cli import main as alpha_daily_report_cli_main
from src.services.alpha_daily_report_service import AlphaDailyReportService


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


def _seed_market(repository: MarketDataRepository) -> None:
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


def _run_cli(service: AlphaDailyReportService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = alpha_daily_report_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_alpha_daily_report_is_summary_only_and_emits_candidate_proposal(tmp_path):
    repository = _repository(tmp_path)
    _seed_market(repository)
    service = AlphaDailyReportService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--symbols",
        "300001,300002,300003",
        "--factor",
        "momentum_5d",
        "--date",
        "2026-05-12",
        "--start",
        "2026-05-04",
        "--end",
        "2026-05-10",
        "--forward-windows",
        "1,3",
        "--top",
        "2",
    )

    assert exit_code == 0
    assert payload["status"] in {"ok", "partial"}
    assert payload["source"] == "alpha_daily_report"
    assert payload["summary"]["proposal_not_applied"] is True
    assert payload["summary"]["human_action_required"] is True
    assert payload["summary"]["top_candidate_symbols"]
    assert "items" not in payload["alpha_scan"]
    assert "evaluation" not in payload["alpha_evaluation"]
    assert payload["alpha_backtest"]["status"] in {"ok", "partial"}
    assert payload["alpha_backtest"]["summary"]["periods"] > 0
    assert "periods" not in payload["alpha_backtest"]
    proposal = payload["strategy_proposal"]
    assert proposal["approval_required"] is True
    assert proposal["effective_status"] == "candidate_only"
    assert proposal["source"] == "alpha_daily_report"
    assert proposal["proposed_changes"][0]["type"] == "register_alpha_topn_candidate"
    assert proposal["evidence"]["alpha_backtest_summary"]["periods"] > 0
    assert "total_return" in proposal["evidence"]["alpha_backtest_summary"]
    assert "proposal_not_applied_to_runtime" in proposal["constraints"]
    json.dumps(payload, allow_nan=False)


def test_alpha_daily_report_include_details_is_explicit_opt_in(tmp_path):
    repository = _repository(tmp_path)
    _seed_market(repository)
    service = AlphaDailyReportService(repository=repository)

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--symbols",
        "300001,300002,300003",
        "--factor",
        "momentum_5d",
        "--date",
        "2026-05-12",
        "--start",
        "2026-05-04",
        "--end",
        "2026-05-10",
        "--forward-windows",
        "1,3",
        "--include-details",
    )

    assert exit_code == 0
    assert "items" in payload["alpha_scan"]
    assert "evaluation" in payload["alpha_evaluation"]
    assert "periods" in payload["alpha_backtest"]
    assert payload["alpha_evaluation"]["evaluation"]["candidate_id"] == "factor:momentum_5d"


def test_alpha_daily_report_empty_universe_has_no_strategy_proposal(tmp_path):
    service = AlphaDailyReportService(repository=_repository(tmp_path))

    exit_code, payload = _run_cli(
        service,
        "--market",
        "cn",
        "--universe",
        "etf",
        "--factor",
        "momentum_20d",
        "--date",
        "2026-05-12",
    )

    assert exit_code == 0
    assert payload["status"] == "empty"
    assert payload["summary"]["proposal_not_applied"] is True
    assert payload["summary"]["human_action_required"] is False
    assert payload["strategy_proposal"] is None
    assert payload["alpha_backtest"]["status"] == "empty"
    json.dumps(payload, allow_nan=False)
