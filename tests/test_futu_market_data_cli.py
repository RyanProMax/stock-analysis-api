from __future__ import annotations

from io import StringIO
import json
import os
import subprocess
import sys

from src.services.futu_market_data_cli import main as futu_market_data_cli_main


class FakeFutuGateway:
    def get_global_state(self):
        return {"qot_logined": True, "server_ver": "10.4.6408"}

    def get_ipo_list(self, market: str):
        assert market == "HK"
        return [
            {
                "code": "HK.01234",
                "name": "Demo Robotics",
                "is_subscribe_status": True,
                "list_time": "2026-05-12",
            }
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
        assert rehab == "none"
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
        return [{"code": "HK.00700", "name": "Tencent", "last_price": 390.2}]


def _run_cli(*args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = futu_market_data_cli_main(
        list(args),
        writer=writer,
        gateway=FakeFutuGateway(),
    )
    return exit_code, json.loads(writer.getvalue())


def test_global_state_cli_contract():
    exit_code, payload = _run_cli("global-state", "--json")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "futu_opend"
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
    assert payload["data"][0]["code"] == "HK.01234"


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


def test_snapshot_cli_contract():
    exit_code, payload = _run_cli("snapshot", "--codes", "HK.00700", "--json")

    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["source"] == "futu_opend"
    assert payload["request"] == {"codes": ["HK.00700"], "count": 1}
    assert payload["data"][0]["code"] == "HK.00700"
