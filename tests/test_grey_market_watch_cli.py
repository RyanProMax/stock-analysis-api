from __future__ import annotations

from io import StringIO
import json

from src.model.trading import MarketSnapshot
from src.services.grey_market_watch_cli import main as grey_market_watch_main
from src.services.grey_market_watch_service import GreyMarketWatchService


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


class FakeFutuMarketData:
    def get_market_snapshots(self, codes: list[str]):
        assert codes == ["HK.02618"]
        return [
            MarketSnapshot(
                code="HK.02618",
                name="剂泰医药",
                price=11.2,
                prev_close=10.0,
                volume=120_000,
                turnover=1_344_000.0,
                as_of="2026-05-12 16:22:03",
                source="futu_opend",
                raw={
                    "dark_status": "TRADING",
                    "bid_price": 11.18,
                    "ask_price": 11.22,
                    "bid_vol": 10_000,
                    "ask_vol": 8_000,
                },
            )
        ]


class FakeFutuGateway:
    def get_order_book(self, code: str, *, num: int):
        assert code == "HK.02618"
        assert num == 3
        return {
            "bid": [{"price": 11.18, "volume": 10_000, "order_count": 4}],
            "ask": [{"price": 11.22, "volume": 8_000, "order_count": 3}],
        }


class FakeGreyMarketWatchService:
    def __init__(self):
        self.calls = 0

    def query(
        self,
        *,
        code: str,
        name: str | None,
        issue_price: float | None,
        providers: list[str],
        order_book_depth: int,
    ):
        self.calls += 1
        assert code == "HK.02618"
        assert name == "剂泰医药"
        assert issue_price == 10.0
        assert providers == ["futu", "tiger", "fosun"]
        assert order_book_depth == 5
        return {
            "status": "ok",
            "source": "grey_market_watch",
            "request": {
                "code": code,
                "name": name,
                "issue_price": issue_price,
                "providers": providers,
            },
            "summary": {"ok_count": 1, "unsupported_count": 2, "failed_count": 0},
            "providers": [{"provider": "futu", "status": "ok"}],
        }


def _run_cli(*args: str, service=None) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = grey_market_watch_main(list(args), writer=writer, service=service)
    return exit_code, _strict_json_loads(writer.getvalue())


def test_grey_market_service_builds_futu_dark_quote_and_provider_capabilities():
    service = GreyMarketWatchService(
        futu_market_data=FakeFutuMarketData(),
        futu_gateway=FakeFutuGateway(),
    )

    payload = service.query(
        code="HK.02618",
        name="剂泰医药",
        issue_price=10.0,
        providers=["futu", "tiger", "fosun"],
        order_book_depth=3,
    )

    assert payload["status"] == "ok"
    assert payload["summary"]["ok_count"] == 1
    assert payload["summary"]["unsupported_count"] == 2
    futu = payload["providers"][0]
    assert futu["provider"] == "futu"
    assert futu["official_api"] is True
    assert futu["quote"]["dark_status"] == "TRADING"
    assert round(futu["quote"]["change_vs_issue_pct"], 4) == 0.12
    assert futu["order_book"]["best_bid"]["price"] == 11.18
    assert payload["providers"][1]["provider"] == "tiger"
    assert payload["providers"][1]["status"] == "unsupported"


def test_grey_market_watch_tick_runs_once_then_skips_until_interval(tmp_path):
    service = FakeGreyMarketWatchService()
    state_db = tmp_path / "state.sqlite"

    first_exit_code, first_payload = _run_cli(
        "--code",
        "HK.02618",
        "--name",
        "剂泰医药",
        "--issue-price",
        "10",
        "--state-db",
        str(state_db),
        "--now",
        "2026-05-12T16:20:00+08:00",
        service=service,
    )
    second_exit_code, second_payload = _run_cli(
        "--code",
        "HK.02618",
        "--name",
        "剂泰医药",
        "--issue-price",
        "10",
        "--state-db",
        str(state_db),
        "--now",
        "2026-05-12T16:20:05+08:00",
        service=service,
    )

    assert first_exit_code == 0
    assert first_payload["status"] == "ok"
    assert first_payload["source"] == "grey_market_watch_tick"
    assert first_payload["watch"]["summary"]["ok_count"] == 1
    assert second_exit_code == 0
    assert second_payload["status"] == "skipped"
    assert second_payload["reason"] == "not_due"
    assert service.calls == 1


def test_grey_market_watch_once_ignores_scheduler_interval(tmp_path):
    service = FakeGreyMarketWatchService()
    state_db = tmp_path / "state.sqlite"

    first_exit_code, first_payload = _run_cli(
        "--code",
        "HK.02618",
        "--name",
        "剂泰医药",
        "--issue-price",
        "10",
        "--state-db",
        str(state_db),
        "--now",
        "2026-05-12T16:20:00+08:00",
        service=service,
    )
    second_exit_code, second_payload = _run_cli(
        "--once",
        "--code",
        "HK.02618",
        "--name",
        "剂泰医药",
        "--issue-price",
        "10",
        "--state-db",
        str(state_db),
        "--now",
        "2026-05-12T16:20:05+08:00",
        service=service,
    )

    assert first_exit_code == 0
    assert first_payload["status"] == "ok"
    assert first_payload["source"] == "grey_market_watch_tick"
    assert second_exit_code == 0
    assert second_payload["status"] == "ok"
    assert second_payload["source"] == "grey_market_watch_once"
    assert second_payload["schedule"]["mode"] == "once"
    assert service.calls == 2


def test_grey_market_watch_once_does_not_create_scheduler_state_db(tmp_path):
    service = FakeGreyMarketWatchService()
    state_db = tmp_path / "state.sqlite"

    exit_code, payload = _run_cli(
        "--once",
        "--code",
        "HK.02618",
        "--name",
        "剂泰医药",
        "--issue-price",
        "10",
        "--state-db",
        str(state_db),
        "--now",
        "2026-05-12T16:20:00+08:00",
        service=service,
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "grey_market_watch_once"
    assert not state_db.exists()
    assert service.calls == 1


def test_grey_market_watch_tick_skips_outside_dark_window(tmp_path):
    service = FakeGreyMarketWatchService()

    exit_code, payload = _run_cli(
        "--code",
        "HK.02618",
        "--state-db",
        str(tmp_path / "state.sqlite"),
        "--now",
        "2026-05-12T15:59:00+08:00",
        service=service,
    )

    assert exit_code == 0
    assert payload["status"] == "skipped"
    assert payload["reason"] == "outside_active_window"
    assert payload["schedule"]["next_run_at"] == "2026-05-12T16:15:00+08:00"
    assert service.calls == 0


def test_grey_market_watch_once_still_skips_outside_dark_window(tmp_path):
    service = FakeGreyMarketWatchService()

    exit_code, payload = _run_cli(
        "--once",
        "--code",
        "HK.02618",
        "--state-db",
        str(tmp_path / "state.sqlite"),
        "--now",
        "2026-05-12T15:59:00+08:00",
        service=service,
    )

    assert exit_code == 0
    assert payload["status"] == "skipped"
    assert payload["source"] == "grey_market_watch_once"
    assert payload["reason"] == "outside_active_window"
    assert payload["schedule"]["next_run_at"] == "2026-05-12T16:15:00+08:00"
    assert service.calls == 0


def test_grey_market_watch_rejects_unknown_provider(tmp_path):
    exit_code, payload = _run_cli(
        "--code",
        "HK.02618",
        "--providers",
        "futu,unknown",
        "--state-db",
        str(tmp_path / "state.sqlite"),
        "--now",
        "2026-05-12T16:20:00+08:00",
        service=FakeGreyMarketWatchService(),
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "unsupported grey-market provider" in payload["error"]
