from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.repositories.strategy_registry_repository import SqliteStrategyRegistry
from src.repositories.trading_ledger_repository import SqliteTradingLedger
from src.services.alpha_daily_report_service import AlphaDailyReportService
from src.services.strategy_registry_service import StrategyRegistryService
from src.services.watch_worker_cli import main as watch_worker_cli_main
from src.services.watch_worker_service import WatchWorkerService


def _daily_rows(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range(end="2026-05-12", periods=len(closes), freq="D")
    rows = []
    previous = None
    for idx, (date, close) in enumerate(zip(dates, closes)):
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "pre_close": previous,
                "volume": 1000 + idx * 10,
                "amount": close * (1000 + idx * 10),
                "turnover_rate": 1.0,
                "pe_ttm": 20.0,
                "pb": 2.0,
            }
        )
        previous = close
    return pd.DataFrame(rows)


def _seed_market(repository: MarketDataRepository) -> None:
    repository.upsert_symbols(
        [
            {"symbol": "300001", "name": "趋势科技", "market": "创业板"},
            {"symbol": "300002", "name": "反转科技", "market": "创业板"},
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


def _activate_strategy(registry: StrategyRegistryService) -> None:
    proposal = {
        "proposal_id": "proposal-alpha-worker",
        "strategy_version": "alpha_topn_momentum_5d.20260512",
        "generated_at": "2026-05-12T08:00:00+00:00",
        "source": "alpha_daily_report",
        "proposed_changes": [
            {
                "type": "register_alpha_topn_candidate",
                "parameters": {
                    "market": "cn",
                    "symbols": "300001,300002",
                    "factor": "momentum_5d",
                    "top_n": 2,
                    "forward_windows": [1, 3],
                },
            }
        ],
        "evidence": {"rank_ic_mean": 0.1},
        "approval_required": True,
        "effective_status": "candidate_only",
    }
    registry.propose(proposal)
    registry.record_judge_verdict(
        {
            "verdict_id": "judge-proposal-alpha-worker-eval-worker",
            "proposal_id": "proposal-alpha-worker",
            "strategy_version": "alpha_topn_momentum_5d.20260512",
            "evaluator_id": "judge-agent",
            "generated_at": "2026-05-12T08:05:00+00:00",
            "gate_status": "passed",
            "researcher_id": "researcher-agent",
            "evaluation_id": "eval-worker",
            "thresholds": {"min_rank_ic_mean": 0.03},
            "metrics": {"rank_ic_mean": 0.1, "observations": 30},
            "reasons": [],
            "human_review_ready": True,
            "proposal_not_applied": True,
        }
    )
    registry.approve(strategy_version="alpha_topn_momentum_5d.20260512", approved_by="ryan")
    registry.activate(strategy_version="alpha_topn_momentum_5d.20260512")


def _service(tmp_path, report_service=None) -> tuple[WatchWorkerService, SqliteTradingLedger]:
    market_repository = MarketDataRepository(str(tmp_path / "market.sqlite"))
    _seed_market(market_repository)
    registry_repository = SqliteStrategyRegistry(tmp_path / "strategy_registry.sqlite")
    registry = StrategyRegistryService(registry=registry_repository)
    _activate_strategy(registry)
    state = SqliteTradingLedger(tmp_path / "watch_worker_state.sqlite")
    service = WatchWorkerService(
        strategy_registry=registry_repository,
        state_repository=state,
        report_service=report_service or AlphaDailyReportService(repository=market_repository),
    )
    return service, state


def _run_cli(service: WatchWorkerService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = watch_worker_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def _base_args() -> list[str]:
    return [
        "--state-key",
        "test-alpha-watch",
        "--interval-seconds",
        "300",
        "--active-window",
        "09:30-11:30,13:00-15:00",
        "--timezone",
        "Asia/Shanghai",
    ]


def test_watch_worker_tick_skips_outside_active_window(tmp_path):
    service, _state = _service(tmp_path)

    exit_code, payload = _run_cli(
        service,
        *_base_args(),
        "--now",
        "2026-05-12T08:00:00+08:00",
    )

    assert exit_code == 0
    assert payload["status"] == "skipped"
    assert payload["reason"] == "outside_active_window"
    assert payload["schedule"]["next_run_at"] == "2026-05-12T09:30:00+08:00"


def test_watch_worker_tick_runs_once_then_skips_until_interval_elapsed(tmp_path):
    service, state = _service(tmp_path)

    first_exit, first = _run_cli(
        service,
        *_base_args(),
        "--now",
        "2026-05-12T10:00:00+08:00",
    )
    second_exit, second = _run_cli(
        service,
        *_base_args(),
        "--now",
        "2026-05-12T10:02:00+08:00",
    )

    assert first_exit == 0
    assert first["status"] in {"ok", "partial"}
    assert first["active_strategy"]["strategy_version"] == "alpha_topn_momentum_5d.20260512"
    assert first["summary"]["proposal_not_applied"] is True
    assert first["simulated_execution"]["status"] == "disabled"
    assert state.list_runs() == []
    assert second_exit == 0
    assert second["status"] == "skipped"
    assert second["reason"] == "not_due"
    assert second["schedule"]["next_run_at"] == "2026-05-12T10:05:00+08:00"


def test_watch_worker_tick_degrades_when_report_generation_fails(tmp_path):
    class FailingReportService:
        def report(self, **_kwargs):
            raise RuntimeError("provider unavailable")

    service, _state = _service(tmp_path, report_service=FailingReportService())

    exit_code, payload = _run_cli(
        service,
        *_base_args(),
        "--now",
        "2026-05-12T10:00:00+08:00",
    )

    assert exit_code == 0
    assert payload["status"] == "degraded"
    assert payload["reason"] == "report_failed"
    assert "provider unavailable" in payload["error"]
    assert payload["simulated_execution"]["status"] == "disabled"
