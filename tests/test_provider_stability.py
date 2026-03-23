import logging
from types import SimpleNamespace

import pytest
import requests

from src.data_provider.manager import DataManager
from src.data_provider.sources.akshare import AkShareDataSource
from src.data_provider.sources.pytdx import PytdxDataSource
from src.data_provider.sources.tushare import TushareDataSource


class TestDataManagerFinancialCapabilityFiltering:
    def test_get_financial_data_skips_unsupported_fetchers_without_polluting_breakers(self):
        class UnsupportedFetcher:
            SOURCE_NAME = "Unsupported"
            priority = 0

        class SupportedFetcher:
            SOURCE_NAME = "Supported"
            priority = 1

            @staticmethod
            def get_cn_financial_data(symbol: str):
                return {"pe_ratio": 10.0}, {}

        manager = DataManager(fetchers=[UnsupportedFetcher(), SupportedFetcher()])

        payload, source = manager.get_financial_data("600519")

        assert payload == {"pe_ratio": 10.0}
        assert source == "Supported"
        assert manager.get_circuit_breaker_status()["CN_Unsupported"] == "closed"
        assert manager.get_circuit_breaker_status()["CN_Supported"] == "closed"


class TestPytdxStability:
    def test_pytdx_session_closes_failed_connect_sockets(self, monkeypatch):
        class FakeAPI:
            instances = []

            def __init__(self):
                self.disconnected = False
                FakeAPI.instances.append(self)

            def connect(self, host, port, time_out=1):
                return False

            def disconnect(self):
                self.disconnected = True

        source = PytdxDataSource()
        source._hosts = [("127.0.0.1", 7709), ("127.0.0.2", 7709)]
        monkeypatch.setattr(source, "_get_pytdx", lambda: FakeAPI)

        with pytest.raises(ConnectionError, match="Pytdx 无法连接任何服务器"):
            with source._pytdx_session():
                pass

        assert len(FakeAPI.instances) == 2
        assert all(instance.disconnected for instance in FakeAPI.instances)


class TestFinancialLoggingNoise:
    def test_akshare_cn_financial_proxy_error_logs_warning_without_traceback(
        self, monkeypatch, caplog, capsys
    ):
        monkeypatch.setattr(
            "src.data_provider.sources.akshare.ak.stock_individual_info_em",
            lambda **kwargs: (_ for _ in ()).throw(requests.exceptions.ProxyError("proxy down")),
        )
        caplog.set_level(logging.WARNING)

        payload, raw_data = AkShareDataSource.get_cn_financial_data("600519")

        captured = capsys.readouterr()
        assert payload is None
        assert raw_data == {}
        assert "AkShare A股财务数据不可用" in caplog.text
        assert "Traceback" not in captured.err
        assert captured.err == ""

    def test_tushare_cn_financial_failure_logs_warning_without_traceback(
        self, monkeypatch, caplog, capsys
    ):
        class ProStub:
            def daily_basic(self, **kwargs):
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

            def fina_indicator(self, **kwargs):
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

            def income(self, **kwargs):
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

        monkeypatch.setattr(TushareDataSource, "get_pro", classmethod(lambda cls: ProStub()))
        caplog.set_level(logging.WARNING)

        payload, raw_data = TushareDataSource.get_cn_financial_data("600519")

        captured = capsys.readouterr()
        assert payload is None
        assert raw_data == {}
        assert "Tushare A股财务数据不可用" in caplog.text
        assert "Traceback" not in captured.err
        assert captured.err == ""


class TestWatchPollingCnLightMode:
    def test_cn_snapshot_skips_heavy_financial_fetch_and_uses_quote_light_fields(
        self, monkeypatch
    ):
        from src.core.watch_polling import WatchPollingService

        service = WatchPollingService()
        quote = SimpleNamespace(
            price=1500.0,
            change_pct=1.23,
            change_amount=18.2,
            open_price=1490.0,
            high=1510.0,
            low=1480.0,
            pre_close=1481.8,
            volume=1000,
            amount=100000.0,
            turnover_rate=2.1,
            amplitude=2.0,
            pe_ratio=24.5,
            pb_ratio=8.1,
            total_mv=1800000000000.0,
        )

        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_stock_info",
            lambda symbol: {"name": "贵州茅台"},
        )
        monkeypatch.setattr(
            "src.core.watch_polling.daily_market_data_service.get_stock_daily",
            lambda symbol: (None, "贵州茅台", "CN_SQLiteDailyWarehouse"),
        )
        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_realtime_quote",
            lambda symbol: (quote, "CN_Tushare"),
        )
        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_financial_data",
            lambda symbol: (_ for _ in ()).throw(AssertionError("不应调用重型财务 fallback")),
        )
        monkeypatch.setattr(
            service,
            "_build_technical_payload",
            lambda **kwargs: {
                "trend": "盘整",
                "ma_alignment": "数据不足",
                "breakout_state": "none",
                "volume_ratio": 1.0,
                "volume_ratio_state": "normal",
            },
        )

        result = service._build_current_snapshot("600519")

        assert result["status"] == "ok"
        assert result["partial"] is False
        assert result["degradation"]["quote_mode"] == "realtime"
        assert result["degradation"]["quote_is_realtime"] is True
        assert result["fundamentals"]["pe_ratio"] == 24.5
        assert result["fundamentals"]["pb_ratio"] == 8.1
        assert result["fundamentals"]["market_cap"] == 1800000000000.0
        assert result["fundamentals"]["source"] == "CN_Tushare"
        assert result["earnings_watch"]["partial"] is False
