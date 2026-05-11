from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.services.alpha_universe_seed_service import AlphaUniverseSeedService
from src.services.alpha_universe_seed_status_cli import main as seed_status_cli_main
from src.services.alpha_universe_seed_status_service import AlphaUniverseSeedStatusService


def _repository(tmp_path) -> MarketDataRepository:
    return MarketDataRepository(str(tmp_path / "market.sqlite"))


def _daily_rows(start: str, periods: int) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=periods, freq="D")
    return pd.DataFrame(
        {
            "date": [date.strftime("%Y-%m-%d") for date in dates],
            "open": [10 + idx for idx in range(periods)],
            "high": [11 + idx for idx in range(periods)],
            "low": [9 + idx for idx in range(periods)],
            "close": [10.5 + idx for idx in range(periods)],
            "volume": [1000 + idx for idx in range(periods)],
        }
    )


def _seed_file(tmp_path) -> str:
    path = tmp_path / "seeds.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "seeds": [
                    {
                        "id": "hk_core",
                        "market": "hk",
                        "symbols": ["HK.00700", "HK.09988", "HK.03690"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def _run_cli(service: AlphaUniverseSeedStatusService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = seed_status_cli_main(list(args), writer=writer, service=service)
    return exit_code, json.loads(writer.getvalue())


def test_seed_status_reports_missing_incomplete_and_stale_symbols(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [
            {"symbol": "HK.00700", "name": "Tencent", "market": "港股", "exchange": "HKEX"},
            {"symbol": "HK.09988", "name": "Alibaba", "market": "港股", "exchange": "HKEX"},
            {"symbol": "HK.03690", "name": "Meituan", "market": "港股", "exchange": "HKEX"},
        ],
        market="hk",
    )
    repository.upsert_daily_bars(
        "HK.00700",
        _daily_rows("2026-01-01", 10),
        "HK_FutuOpenD",
        market="hk",
    )
    repository.upsert_daily_bars(
        "HK.09988",
        _daily_rows("2026-01-05", 10),
        "HK_FutuOpenD",
        market="hk",
    )
    service = AlphaUniverseSeedStatusService(
        repository=repository,
        seed_service=AlphaUniverseSeedService(_seed_file(tmp_path)),
    )

    exit_code, payload = _run_cli(
        service,
        "--universe-seed",
        "hk_core",
        "--market",
        "hk",
        "--start-date",
        "2026-01-01",
        "--stale-before",
        "2026-01-20",
    )

    assert exit_code == 0
    assert payload["status"] == "needs_sync"
    assert payload["summary"] == {
        "total": 3,
        "ok": 0,
        "missing": 1,
        "incomplete": 1,
        "stale": 1,
        "needs_sync": 3,
    }
    statuses = {item["symbol"]: item["status"] for item in payload["items"]}
    assert statuses == {
        "HK.00700": "stale",
        "HK.09988": "incomplete_history",
        "HK.03690": "missing_daily_history",
    }
    assert payload["sync_plan"]["required"] is True
    assert payload["sync_plan"]["symbols"] == ["HK.00700", "HK.09988", "HK.03690"]
    assert payload["sync_plan"]["command_args"] == [
        "uv",
        "run",
        "sync-market-data",
        "--market",
        "hk",
        "--scope",
        "symbol",
        "--symbols",
        "HK.00700,HK.09988,HK.03690",
        "--start-date",
        "2026-01-01",
    ]
    json.dumps(payload, allow_nan=False)


def test_seed_status_reports_ok_when_seed_is_covered(tmp_path):
    repository = _repository(tmp_path)
    repository.upsert_symbols(
        [{"symbol": "HK.00700", "name": "Tencent", "market": "港股", "exchange": "HKEX"}],
        market="hk",
    )
    repository.upsert_daily_bars(
        "HK.00700",
        _daily_rows("2026-01-01", 30),
        "HK_FutuOpenD",
        market="hk",
    )
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(
        '{"version":1,"seeds":[{"id":"hk_one","market":"hk","symbols":["HK.00700"]}]}',
        encoding="utf-8",
    )
    service = AlphaUniverseSeedStatusService(
        repository=repository,
        seed_service=AlphaUniverseSeedService(seed_file),
    )

    exit_code, payload = _run_cli(
        service,
        "--universe-seed",
        "hk_one",
        "--market",
        "hk",
        "--start-date",
        "2026-01-01",
        "--stale-before",
        "2026-01-15",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["summary"]["ok"] == 1
    assert payload["items"][0]["needs_sync"] is False
    assert payload["sync_plan"] == {
        "required": False,
        "status": "not_required",
        "symbols": [],
        "command_args": [],
    }


def test_seed_status_adjusts_start_date_to_first_observed_trade_date(tmp_path):
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
        _daily_rows("2026-01-02", 30),
        "HK_FutuOpenD",
        market="hk",
    )
    repository.upsert_daily_bars(
        "HK.09988",
        _daily_rows("2026-01-02", 30),
        "HK_FutuOpenD",
        market="hk",
    )
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(
        '{"version":1,"seeds":[{"id":"hk_pair","market":"hk","symbols":["HK.00700","HK.09988"]}]}',
        encoding="utf-8",
    )
    service = AlphaUniverseSeedStatusService(
        repository=repository,
        seed_service=AlphaUniverseSeedService(seed_file),
    )

    exit_code, payload = _run_cli(
        service,
        "--universe-seed",
        "hk_pair",
        "--market",
        "hk",
        "--start-date",
        "2026-01-01",
        "--stale-before",
        "2026-01-15",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["request"]["start_date"] == "2026-01-01"
    assert payload["request"]["effective_start_date"] == "2026-01-02"
    assert payload["summary"]["ok"] == 2
