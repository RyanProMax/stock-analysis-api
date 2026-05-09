from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.services.alpha_daily_report_service import AlphaDailyReportService
from src.services.alpha_research_loop_cli import main as alpha_research_loop_cli_main
from src.services.alpha_research_loop_service import AlphaResearchLoopService


def _daily_rows(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range(end="2026-05-12", periods=len(closes), freq="D")
    volumes = volumes or [1000 + idx * 20 for idx in range(len(closes))]
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


def _service(tmp_path) -> AlphaResearchLoopService:
    repository = _repository(tmp_path)
    _seed_market(repository)
    return AlphaResearchLoopService(
        report_service=AlphaDailyReportService(repository=repository),
    )


def _run_cli(service: AlphaResearchLoopService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = alpha_research_loop_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_alpha_research_loop_returns_human_review_ready_without_applying_strategy(tmp_path):
    exit_code, payload = _run_cli(
        _service(tmp_path),
        "--market",
        "cn",
        "--symbols",
        "300001,300002,300003",
        "--factors",
        "momentum_5d,momentum_20d",
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
        "--researcher-id",
        "researcher-agent",
        "--backtester-id",
        "backtester-agent",
        "--evaluator-id",
        "judge-agent",
        "--min-rank-ic-mean",
        "-1",
        "--min-quantile-spread",
        "-1",
        "--min-observations",
        "1",
        "--allow-data-gaps",
    )

    assert exit_code == 0
    assert payload["status"] == "human_review_ready"
    assert payload["source"] == "alpha_research_loop"
    assert payload["team"]["researcher"]["id"] == "researcher-agent"
    assert payload["team"]["backtester"]["id"] == "backtester-agent"
    assert payload["team"]["evaluator"]["id"] == "judge-agent"
    assert payload["summary"]["human_review_ready"] is True
    assert payload["summary"]["proposal_not_applied"] is True
    assert payload["summary"]["approval_required"] is True
    assert payload["selected"]["verdict"]["gate_status"] == "passed"
    assert payload["selected"]["strategy_proposal"]["approval_required"] is True
    assert payload["selected"]["strategy_proposal"]["effective_status"] == "candidate_only"
    assert payload["attempts"][0]["roles"]["researcher_id"] == "researcher-agent"
    assert payload["attempts"][0]["roles"]["backtester_id"] == "backtester-agent"
    assert payload["attempts"][0]["roles"]["evaluator_id"] == "judge-agent"
    assert "report" not in payload["attempts"][0]
    assert "strategy_proposal" not in payload["attempts"][0]
    json.dumps(payload, allow_nan=False)


def test_alpha_research_loop_needs_iteration_when_all_attempts_blocked(tmp_path):
    exit_code, payload = _run_cli(
        _service(tmp_path),
        "--market",
        "cn",
        "--symbols",
        "300001,300002,300003",
        "--factors",
        "momentum_5d,volatility_5d",
        "--date",
        "2026-05-12",
        "--start",
        "2026-05-04",
        "--end",
        "2026-05-10",
        "--forward-windows",
        "1,3",
        "--researcher-id",
        "researcher-agent",
        "--backtester-id",
        "backtester-agent",
        "--evaluator-id",
        "judge-agent",
        "--min-rank-ic-mean",
        "999",
        "--min-quantile-spread",
        "999",
    )

    assert exit_code == 0
    assert payload["status"] == "needs_iteration"
    assert payload["selected"] is None
    assert payload["summary"]["human_review_ready"] is False
    assert payload["summary"]["blocked_attempts"] == 2
    assert payload["next_research_actions"]
    assert all(attempt["status"] == "blocked" for attempt in payload["attempts"])
    assert any(
        "rank_ic_mean_below_threshold" in attempt["judge_reasons"]
        for attempt in payload["attempts"]
    )


def test_alpha_research_loop_rejects_non_independent_roles(tmp_path):
    exit_code, payload = _run_cli(
        _service(tmp_path),
        "--market",
        "cn",
        "--symbols",
        "300001,300002,300003",
        "--factors",
        "momentum_5d",
        "--researcher-id",
        "same-agent",
        "--backtester-id",
        "backtester-agent",
        "--evaluator-id",
        "same-agent",
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["source"] == "alpha_research_loop"
    assert "agent team roles must be distinct" in payload["error"]
