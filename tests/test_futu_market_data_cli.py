from __future__ import annotations

from io import StringIO
import json
import os
import subprocess
import sys
import time
import warnings

import pytest

from src.services.futu_market_data_cli import (
    _build_parser,
    main as futu_market_data_cli_main,
)
from src.data_provider.sources.futu import FutuDailyDataSource


def _strict_json_loads(raw: str) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw, parse_constant=reject_constant)


class FakeFutuGateway:
    def __init__(self, *, expected_rehab: str = "none"):
        self.expected_rehab = expected_rehab

    def get_global_state(self):
        return {"qot_logined": True, "server_ver": "10.4.6408"}

    def get_ipo_list(self, market: str):
        assert market == "HK"
        return [
            {
                "code": "HK.02723",
                "name": "DEEPZERO",
                "is_subscribe_status": True,
                "list_time": "2026-05-12",
            },
            {
                "code": "HK.01779",
                "name": "LONGBIO-B",
                "is_subscribe_status": True,
                "list_time": "2026-06-05",
            },
            {
                "code": "HK.02290",
                "name": "LUNG FUNG GROUP",
                "is_subscribe_status": True,
                "list_time": "2026-06-05",
            },
            {
                "code": "HK.01081",
                "name": "DAJIN",
                "is_subscribe_status": True,
                "list_time": "2026-06-05",
            },
            {
                "code": "HK.02553",
                "name": "SHOUGANG LANZA",
                "is_subscribe_status": False,
                "list_time": "2026-06-03",
            },
        ]

    def request_history_kline(
        self,
        code: str,
        *,
        ktype: str,
        start: str | None,
        end: str | None,
        max_count: int,
        rehab: str,
        session: str,
        max_page: int | None,
    ):
        assert code == "HK.01234"
        assert ktype == "1d"
        assert start == "2026-05-12"
        assert end == "2026-05-12"
        assert rehab == self.expected_rehab
        return [
            {
                "time_key": "2026-05-12",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11.5,
                "volume": 1000,
                "turnover": 11500,
            }
        ]

    def get_market_snapshots(self, codes: list[str]):
        assert codes == ["HK.00700"]
        return [
            {
                "code": "HK.00700",
                "name": "Tencent",
                "last_price": 390.2,
                "lot_size": 100,
                "price_spread": 0.2,
                "stock_type": "STOCK",
                "stock_owner": float("nan"),
            }
        ]

    def get_order_book(self, code: str, *, num: int):
        assert code == "HK.00700"
        assert num == 3
        return {
            "bid": [{"price": 390.0, "volume": 1000, "order_count": 2}],
            "ask": [{"price": 390.2, "volume": 1200, "order_count": 3}],
        }

    def get_rt_ticker(self, code: str, *, num: int):
        assert code == "HK.00700"
        assert num == 5
        return [{"time": "09:31:01", "price": 390.2, "volume": 100}]

    def get_rt_data(self, code: str):
        assert code == "HK.00700"
        return [{"time": "09:31", "price": 390.2, "volume": 1000}]

    def get_option_expiration_date(self, code: str, *, index_option_type: str):
        assert code == "US.AAPL"
        assert index_option_type == "NORMAL"
        return [{"strike_time": "2026-05-15"}]

    def get_option_chain(
        self,
        code: str,
        *,
        index_option_type: str,
        start: str | None,
        end: str | None,
        option_type: str,
        option_cond_type: str,
    ):
        assert code == "US.AAPL"
        assert index_option_type == "NORMAL"
        assert start == "2026-05-15"
        assert end == "2026-06-19"
        assert option_type == "CALL"
        assert option_cond_type == "ALL"
        return [
            {
                "code": "US.AAPL260515C00200000",
                "option_type": "CALL",
                "strike_price": 200.0,
                "last_price": 6.2,
            }
        ]


class FakeReadonlyTradeGateway:
    def __init__(self):
        self.calls: list[str] = []

    def get_account(self, *, currency: str):
        assert currency == "HKD"
        self.calls.append("get_account")
        return {"cash": 50000.0, "total_assets": 51000.0, "currency": "HKD"}

    def get_positions(self, *, code: str = ""):
        assert code == "HK.00700"
        self.calls.append("get_positions")
        return [{"code": "HK.00700", "qty": 100, "market_val": 41000.0}]

    def get_orders(self, *, code: str = "", start: str = "", end: str = "", history: bool = False):
        assert code == "HK.00700"
        assert start == "2026-05-01"
        assert end == "2026-05-07"
        assert history is True
        self.calls.append("get_orders")
        return [{"order_id": "O-1", "code": "HK.00700", "order_status": "FILLED_ALL"}]

    def get_deals(self, *, code: str = "", start: str = "", end: str = "", history: bool = False):
        assert code == "HK.00700"
        assert start == "2026-05-01"
        assert end == "2026-05-07"
        assert history is True
        self.calls.append("get_deals")
        return [{"deal_id": "D-1", "code": "HK.00700", "qty": 100}]

    def get_cash_flow(self, *, clearing_date: str = "", direction: str = "N/A"):
        assert clearing_date == "2026-05-07"
        assert direction == "N/A"
        self.calls.append("get_cash_flow")
        return [{"clearing_date": "2026-05-07", "cash_flow": -39020.0}]

    def place_order(self, *args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("readonly CLI must not place orders")

    def unlock_trade(self, *args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("readonly CLI must not unlock trading")

    def subscribe(self, *args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("readonly CLI must not subscribe")


class NoisyFutuGateway(FakeFutuGateway):
    def get_global_state(self):
        print("futu sdk stdout log")
        warnings.warn("futu sdk warning", DeprecationWarning, stacklevel=1)
        return super().get_global_state()


class HangingFutuGateway(FakeFutuGateway):
    def get_ipo_list(self, market: str):
        time.sleep(1)
        return super().get_ipo_list(market)


class CleanupHangingFutuGateway(FakeFutuGateway):
    def get_ipo_list(self, market: str):
        try:
            time.sleep(1)
        finally:
            time.sleep(1)


def _run_cli(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = futu_market_data_cli_main(
        list(args),
        writer=writer,
        gateway=FakeFutuGateway(),
    )
    return exit_code, _strict_json_loads(writer.getvalue())


def _run_trade_cli(*args: str) -> tuple[int, dict, FakeReadonlyTradeGateway]:
    writer = StringIO()
    trade_gateway = FakeReadonlyTradeGateway()
    exit_code = futu_market_data_cli_main(
        list(args),
        writer=writer,
        gateway=FakeFutuGateway(),
        trade_gateway=trade_gateway,
    )
    return exit_code, _strict_json_loads(writer.getvalue()), trade_gateway


def test_global_state_cli_contract():
    exit_code, payload = _run_cli("global-state", "--json")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "futu_opend"
    assert payload["data"]["qot_logined"] is True


def test_futu_cli_suppresses_gateway_stdout_noise(capsys):
    writer = StringIO()

    exit_code = futu_market_data_cli_main(
        ["global-state", "--json"],
        writer=writer,
        gateway=NoisyFutuGateway(),
    )

    captured = capsys.readouterr()
    payload = _strict_json_loads(writer.getvalue())
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert payload["status"] == "ok"
    assert payload["data"]["qot_logined"] is True


def test_futu_cli_import_does_not_initialize_market_data_repository(tmp_path):
    env = {
        **os.environ,
        "MARKET_DATA_DB_PATH": str(tmp_path / "missing-parent" / "market_data.sqlite"),
    }

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.services.futu_market_data_cli import main; print('ok')",
        ],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    assert proc.stdout.strip() == "ok"


def test_ipo_list_cli_contract():
    exit_code, payload = _run_cli("ipo-list", "--market", "HK", "--json")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["market"] == "HK"
    assert payload["data"][0]["code"] == "HK.02723"
    assert payload["data"][0]["name"] == "DEEPZERO"
    assert payload["data"][0]["name_zh"] == "深演智能"
    assert payload["data"][0]["display_name"] == "深演智能"
    assert payload["data"][0]["name_en"] == "DEEPZERO"
    assert payload["data"][0]["name_source"] == "hkipo_alias_map"

    by_code = {row["code"]: row for row in payload["data"]}
    assert by_code["HK.01779"]["name_zh"] == "天辰生物-B"
    assert by_code["HK.01779"]["display_name"] == "天辰生物-B"
    assert by_code["HK.01779"]["name_en"] == "LONGBIO-B"
    assert by_code["HK.02290"]["name_zh"] == "龙丰集团"
    assert by_code["HK.02290"]["display_name"] == "龙丰集团"
    assert by_code["HK.02290"]["name_en"] == "LUNG FUNG GROUP"
    assert by_code["HK.01081"]["name_zh"] == "大金重工"
    assert by_code["HK.01081"]["display_name"] == "大金重工"
    assert by_code["HK.01081"]["name_en"] == "DAJIN"
    assert by_code["HK.02553"]["name_zh"] == "首钢朗泽"
    assert by_code["HK.02553"]["display_name"] == "首钢朗泽"
    assert by_code["HK.02553"]["name_en"] == "SHOUGANG LANZA"


def test_ipo_list_cli_times_out_hanging_opend_call(monkeypatch):
    monkeypatch.setenv("FUTU_OPEND_CALL_TIMEOUT_SECONDS", "0.05")
    writer = StringIO()

    exit_code = futu_market_data_cli_main(
        ["ipo-list", "--market", "HK", "--json"],
        writer=writer,
        gateway=HangingFutuGateway(),
    )

    payload = _strict_json_loads(writer.getvalue())

    assert exit_code == 1
    assert payload["status"] == "failed"
    assert "timed out after 0.05s" in payload["error"]


def test_stdout_cli_force_exits_after_hanging_opend_call(monkeypatch, capsys):
    monkeypatch.setenv("FUTU_OPEND_CALL_TIMEOUT_SECONDS", "0.05")
    exit_codes: list[int] = []

    def fake_exit(code: int) -> None:
        exit_codes.append(code)
        raise SystemExit(code)

    monkeypatch.setattr("src.services.futu_market_data_cli.os._exit", fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        futu_market_data_cli_main(
            ["ipo-list", "--market", "HK", "--json"],
            gateway=HangingFutuGateway(),
        )

    payload = _strict_json_loads(capsys.readouterr().out)

    assert exc_info.value.code == 1
    assert exit_codes == [1]
    assert payload["status"] == "failed"
    assert "timed out after 0.05s" in payload["error"]


def test_ipo_list_cli_bounds_cleanup_after_hanging_opend_call(monkeypatch):
    monkeypatch.setenv("FUTU_OPEND_CALL_TIMEOUT_SECONDS", "0.05")
    writer = StringIO()

    started = time.monotonic()
    exit_code = futu_market_data_cli_main(
        ["ipo-list", "--market", "HK", "--json"],
        writer=writer,
        gateway=CleanupHangingFutuGateway(),
    )
    elapsed = time.monotonic() - started

    payload = _strict_json_loads(writer.getvalue())

    assert exit_code == 1
    assert elapsed < 0.3
    assert payload["status"] == "failed"
    assert "timed out after 0.05s" in payload["error"]


def test_history_kline_cli_contract():
    exit_code, payload = _run_cli(
        "kline",
        "--code",
        "HK.01234",
        "--start",
        "2026-05-12",
        "--end",
        "2026-05-12",
        "--rehab",
        "none",
        "--json",
    )

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["code"] == "HK.01234"
    assert payload["data"][0]["close"] == 11.5


def test_futu_daily_data_source_maps_kline_to_warehouse_daily_columns():
    source = FutuDailyDataSource(gateway=FakeFutuGateway(expected_rehab="forward"))

    df = source.get_daily_data(
        "HK.01234",
        market="hk",
        start_date="2026-05-12",
        end_date="2026-05-12",
    )

    assert list(df["date"]) == ["2026-05-12"]
    assert list(df["open"]) == [10]
    assert list(df["close"]) == [11.5]
    assert list(df["volume"]) == [1000]
    assert list(df["amount"]) == [11500]
    assert list(df["ts_code"]) == ["HK.01234"]


def test_snapshot_cli_contract():
    exit_code, payload = _run_cli("snapshot", "--codes", "HK.00700", "--json")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "futu_opend"
    assert payload["request"] == {"codes": ["HK.00700"], "count": 1}
    assert payload["data"][0]["code"] == "HK.00700"
    assert payload["data"][0]["raw"]["stock_owner"] is None


def test_symbol_rules_cli_extracts_lot_size_and_tick_from_futu_snapshot():
    exit_code, payload = _run_cli("symbol-rules", "--codes", "HK.00700", "--json")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "futu_opend"
    assert payload["request"] == {"codes": ["HK.00700"], "count": 1}
    rule = payload["data"][0]
    assert rule["code"] == "HK.00700"
    assert rule["market"] == "hk"
    assert rule["lot_size"] == 100
    assert rule["lot_size_source"] == "futu_snapshot"
    assert rule["price_tick"] == 0.2
    assert rule["price_tick_source"] == "futu_snapshot"
    assert rule["market_spec"]["default_lot_size"] == 100
    assert rule["market_spec"]["default_price_tick"] == 0.01
    assert rule["raw_fields"]["price_spread"] == 0.2


def test_order_book_ticker_rt_data_cli_contracts():
    exit_code, order_book = _run_cli("order-book", "--code", "HK.00700", "--num", "3", "--json")
    assert exit_code == 0
    assert order_book["status"] == "ok"
    assert order_book["request"] == {"code": "HK.00700", "num": 3}
    assert order_book["data"]["bid"][0]["price"] == 390.0

    exit_code, ticker = _run_cli("ticker", "--code", "HK.00700", "--num", "5", "--json")
    assert exit_code == 0
    assert ticker["status"] == "ok"
    assert ticker["request"] == {"code": "HK.00700", "num": 5}
    assert ticker["data"][0]["price"] == 390.2

    exit_code, rt_data = _run_cli("rt-data", "--code", "HK.00700", "--json")
    assert exit_code == 0
    assert rt_data["status"] == "ok"
    assert rt_data["request"] == {"code": "HK.00700"}
    assert rt_data["data"][0]["volume"] == 1000


def test_option_expirations_and_chain_cli_contracts():
    exit_code, expirations = _run_cli("option-expirations", "--code", "US.AAPL", "--json")
    assert exit_code == 0
    assert expirations["status"] == "ok"
    assert expirations["request"] == {"code": "US.AAPL", "index_option_type": "NORMAL"}
    assert expirations["data"][0]["strike_time"] == "2026-05-15"

    exit_code, chain = _run_cli(
        "option-chain",
        "--code",
        "US.AAPL",
        "--start",
        "2026-05-15",
        "--end",
        "2026-06-19",
        "--option-type",
        "CALL",
        "--json",
    )
    assert exit_code == 0
    assert chain["status"] == "ok"
    assert chain["request"] == {
        "code": "US.AAPL",
        "index_option_type": "NORMAL",
        "start": "2026-05-15",
        "end": "2026-06-19",
        "option_type": "CALL",
        "option_cond_type": "ALL",
    }
    assert chain["data"][0]["code"] == "US.AAPL260515C00200000"


def test_account_positions_orders_deals_and_cash_flow_are_readonly():
    exit_code, account, trade_gateway = _run_trade_cli(
        "account",
        "--market",
        "HK",
        "--currency",
        "HKD",
        "--json",
    )
    assert exit_code == 0
    assert account["status"] == "ok"
    assert account["environment"] == "SIMULATE"
    assert account["data"]["cash"] == 50000.0

    exit_code, positions, _ = _run_trade_cli(
        "positions",
        "--market",
        "HK",
        "--code",
        "HK.00700",
        "--json",
    )
    assert exit_code == 0
    assert positions["status"] == "ok"
    assert positions["data"][0]["code"] == "HK.00700"

    exit_code, orders, _ = _run_trade_cli(
        "orders",
        "--market",
        "HK",
        "--code",
        "HK.00700",
        "--start",
        "2026-05-01",
        "--end",
        "2026-05-07",
        "--history",
        "--json",
    )
    assert exit_code == 0
    assert orders["status"] == "ok"
    assert orders["data"][0]["order_id"] == "O-1"

    exit_code, deals, _ = _run_trade_cli(
        "deals",
        "--market",
        "HK",
        "--code",
        "HK.00700",
        "--start",
        "2026-05-01",
        "--end",
        "2026-05-07",
        "--history",
        "--json",
    )
    assert exit_code == 0
    assert deals["status"] == "ok"
    assert deals["data"][0]["deal_id"] == "D-1"

    exit_code, cash_flow, _ = _run_trade_cli(
        "cash-flow",
        "--market",
        "HK",
        "--clearing-date",
        "2026-05-07",
        "--json",
    )
    assert exit_code == 0
    assert cash_flow["status"] == "ok"
    assert cash_flow["data"][0]["cash_flow"] == -39020.0
    assert trade_gateway.calls == ["get_account"]


def test_futu_market_data_cli_does_not_expose_write_subcommands():
    parser = _build_parser()
    subcommands = next(action for action in parser._actions if action.dest == "command")
    exposed = set(subcommands.choices)

    assert "symbol-rules" in exposed
    assert not exposed.intersection(
        {
            "place-order",
            "modify-order",
            "cancel-order",
            "unlock-trade",
            "subscribe",
        }
    )
