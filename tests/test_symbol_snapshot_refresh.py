from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import src.main as main_module
from src.main import app
from src.repositories.market_data_repository import MarketDataRepository
from src.services.symbol_snapshot_refresh_service import SymbolSnapshotRefreshService


class FakeSymbolCatalog:
    def __init__(self):
        self.calls = []

    def refresh_market_snapshot_result(self, market: str):
        self.calls.append(market)
        return {
            "success": True,
            "rows": [{"symbol": "300827"}, {"symbol": "510300"}] if market == "cn" else [{"symbol": "NVDA"}],
            "source": "fake",
            "partial": False,
        }


class TestSymbolSnapshotRefreshService:
    def test_notify_request_schedules_health_but_skips_docs(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        service = SymbolSnapshotRefreshService(repository=storage, symbol_catalog=FakeSymbolCatalog())
        scheduled = []

        monkeypatch.setattr(service, "_market_today", lambda market: "2026-03-24")
        monkeypatch.setattr(
            service,
            "_spawn_refresh_thread",
            lambda *, market, trigger_path, market_date: scheduled.append((market, trigger_path, market_date)),
        )

        service.notify_request("/docs")
        service.notify_request("/redoc")
        service.notify_request("/openapi.json")
        service.notify_request("/health")

        assert scheduled == [
            ("cn", "/health", "2026-03-24"),
            ("us", "/health", "2026-03-24"),
        ]

    def test_market_refresh_skips_when_store_already_current(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                }
            ],
            market="cn",
        )
        catalog = FakeSymbolCatalog()
        service = SymbolSnapshotRefreshService(repository=storage, symbol_catalog=catalog)
        market_date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")

        service._run_market_refresh(
            market="cn",
            trigger_path="/health",
            market_date=market_date,
        )

        assert catalog.calls == []
        assert service._state["cn"]["last_checked_date"] == market_date
        assert service._state["cn"]["last_error"] is None

    def test_market_refresh_marks_closed_day_as_checked_without_refresh(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        catalog = FakeSymbolCatalog()
        service = SymbolSnapshotRefreshService(repository=storage, symbol_catalog=catalog)
        monkeypatch.setattr(
            service,
            "_is_market_open_today",
            lambda *, market, market_date: {"is_open": False, "used_fallback": False},
        )

        service._run_market_refresh(
            market="cn",
            trigger_path="/stock/list",
            market_date="2026-10-01",
        )

        assert catalog.calls == []
        assert service._state["cn"]["last_checked_date"] == "2026-10-01"
        assert service._state["cn"]["last_error"] is None

    def test_market_refresh_open_check_failure_does_not_seal_day(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        service = SymbolSnapshotRefreshService(repository=storage, symbol_catalog=FakeSymbolCatalog())
        scheduled = []

        monkeypatch.setattr(
            service,
            "_is_market_open_today",
            lambda *, market, market_date: {"is_open": None, "used_fallback": False},
        )

        service._run_market_refresh(
            market="cn",
            trigger_path="/stock/list",
            market_date="2026-03-24",
        )

        assert service._state["cn"]["last_checked_date"] is None
        assert service._state["cn"]["last_error"] == "market_open_check_failed"

        monkeypatch.setattr(service, "_market_today", lambda market: "2026-03-24")
        monkeypatch.setattr(
            service,
            "_spawn_refresh_thread",
            lambda *, market, trigger_path, market_date: scheduled.append((market, trigger_path, market_date)),
        )

        service._maybe_schedule_market_refresh(market="cn", trigger_path="/stock/list")

        assert scheduled == [("cn", "/stock/list", "2026-03-24")]

    def test_market_refresh_does_not_repeat_after_success_on_same_day(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        service = SymbolSnapshotRefreshService(repository=storage, symbol_catalog=FakeSymbolCatalog())
        service._state["cn"]["last_checked_date"] = "2026-03-24"
        scheduled = []

        monkeypatch.setattr(service, "_market_today", lambda market: "2026-03-24")
        monkeypatch.setattr(
            service,
            "_spawn_refresh_thread",
            lambda *, market, trigger_path, market_date: scheduled.append((market, trigger_path, market_date)),
        )

        service._maybe_schedule_market_refresh(market="cn", trigger_path="/stock/list")

        assert scheduled == []

    def test_market_refresh_does_not_schedule_when_in_flight(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        service = SymbolSnapshotRefreshService(repository=storage, symbol_catalog=FakeSymbolCatalog())
        service._state["cn"]["in_flight"] = True
        scheduled = []

        monkeypatch.setattr(service, "_market_today", lambda market: "2026-03-24")
        monkeypatch.setattr(
            service,
            "_spawn_refresh_thread",
            lambda *, market, trigger_path, market_date: scheduled.append((market, trigger_path, market_date)),
        )

        service._maybe_schedule_market_refresh(market="cn", trigger_path="/stock/list")

        assert scheduled == []

    def test_us_market_refresh_marks_fallback_check_as_success(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        catalog = FakeSymbolCatalog()
        service = SymbolSnapshotRefreshService(repository=storage, symbol_catalog=catalog)

        monkeypatch.setattr(
            service,
            "_is_market_open_today",
            lambda *, market, market_date: {"is_open": True, "used_fallback": market == "us"},
        )

        service._run_market_refresh(
            market="us",
            trigger_path="/health",
            market_date="2026-03-24",
        )

        assert catalog.calls == ["us"]
        assert service._state["us"]["last_checked_date"] == "2026-03-24"
        assert service._state["us"]["last_error"] is None


class TestSymbolSnapshotRefreshMiddleware:
    def test_health_request_invokes_preflight(self, monkeypatch):
        notified = []
        monkeypatch.setattr(
            main_module.symbol_snapshot_refresh_service,
            "notify_request",
            lambda path: notified.append(path),
        )

        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert notified == ["/health"]
