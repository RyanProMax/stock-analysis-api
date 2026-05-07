from __future__ import annotations

from io import StringIO
import json

import pandas as pd

from src.services.realtime_quote_polling_cli import main as realtime_quote_cli_main
from src.services.realtime_quote_polling_service import RealtimeQuotePollingService


class FakePro:
    def __init__(
        self,
        *,
        stock_basic_df: pd.DataFrame | None = None,
        etf_basic_df: pd.DataFrame | None = None,
        quotation_df: pd.DataFrame | None = None,
        quotation_error: Exception | None = None,
    ) -> None:
        self.stock_basic_df = stock_basic_df if stock_basic_df is not None else pd.DataFrame()
        self.etf_basic_df = etf_basic_df if etf_basic_df is not None else pd.DataFrame()
        self.quotation_df = quotation_df if quotation_df is not None else pd.DataFrame()
        self.quotation_error = quotation_error

    def stock_basic(self, **kwargs):
        return self.stock_basic_df

    def etf_basic(self, **kwargs):
        return self.etf_basic_df

    def quotation(self, **kwargs):
        if self.quotation_error is not None:
            raise self.quotation_error
        return self.quotation_df


def _stock_basic_frame(symbol: str = "600000") -> pd.DataFrame:
    exchange = "SSE" if symbol.startswith("6") else "SZSE"
    return pd.DataFrame(
        [
            {
                "ts_code": f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ",
                "symbol": symbol,
                "name": "浦发银行",
                "area": "上海",
                "industry": "银行",
                "market": "主板",
                "exchange": exchange,
                "list_status": "L",
                "list_date": "19991110",
                "delist_date": None,
            }
        ]
    )


def _etf_basic_frame(symbol: str = "510300") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": f"{symbol}.SH",
                "exchange": "SSE",
                "csname": "沪深300ETF",
                "cname": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
                "extname": "沪深300ETF",
                "list_status": "L",
                "list_date": "20120528",
                "setup_date": "20120504",
                "index_code": "000300.SH",
                "index_name": "沪深300",
                "mgr_name": "华泰柏瑞",
                "custod_name": "中国银行",
                "mgt_fee": 0.5,
                "etf_type": "股票型",
            }
        ]
    )


def _quotation_frame(name: str = "浦发银行") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": name,
                "price": 10.23,
                "pct_chg": 1.23,
                "change": 0.12,
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "pre_close": 10.11,
                "vol": 123456,
                "amount": 987654321,
                "volume_ratio": 1.8,
                "turnover_ratio": 2.5,
                "amplitude": 3.4,
            }
        ]
    )


def _legacy_frame(name: str = "浦发银行") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": name,
                "price": 10.22,
                "pre_close": 10.1,
                "open": 10.0,
                "high": 10.25,
                "low": 9.98,
                "volume": 100000,
                "amount": 50000000,
            }
        ]
    )


def _run_cli(service: RealtimeQuotePollingService, *args: str) -> tuple[int, dict]:
    writer = StringIO()
    exit_code = realtime_quote_cli_main(list(args), writer=writer, service=service)
    payload = json.loads(writer.getvalue())
    return exit_code, payload


class TestRealtimeQuotePollingCli:
    def test_stock_cli_contract_and_json_only(self):
        def noisy_get_pro():
            print("noise that should be suppressed")
            return FakePro(
                stock_basic_df=_stock_basic_frame(),
                quotation_df=_quotation_frame(),
            )

        service = RealtimeQuotePollingService(get_pro=noisy_get_pro)
        exit_code, payload = _run_cli(service, "--symbols", "600000", "--pretty")

        assert exit_code == 0
        assert payload["status"] == "ok"
        assert payload["request"]["symbols"] == ["600000"]
        item = payload["items"][0]
        assert item["status"] == "ok"
        assert item["info"]["security_type"] == "stock"
        assert item["quote_data"]["mode"] == "realtime"
        assert item["quote_data"]["change_pct"] == 0.0123
        assert item["quote_data"]["turnover_rate"] == 0.025

    def test_etf_cli_contract(self):
        service = RealtimeQuotePollingService(
            get_pro=lambda: FakePro(
                etf_basic_df=_etf_basic_frame(),
                quotation_df=_quotation_frame(name="沪深300ETF"),
            )
        )

        exit_code, payload = _run_cli(service, "--symbols", "510300")

        assert exit_code == 0
        assert payload["status"] == "ok"
        item = payload["items"][0]
        assert item["info"]["security_type"] == "etf"
        assert item["info"]["index_code"] == "000300.SH"
        assert item["quote_data"]["mode"] == "realtime"

    def test_invalid_symbol_returns_failed_item(self):
        service = RealtimeQuotePollingService(
            get_pro=lambda: FakePro(stock_basic_df=pd.DataFrame(), quotation_df=pd.DataFrame())
        )

        exit_code, payload = _run_cli(service, "--symbols", "BAD")

        assert exit_code == 0
        assert payload["status"] == "partial"
        assert payload["summary"]["failed"] == 1
        item = payload["items"][0]
        assert item["status"] == "failed"
        assert "非法证券代码" in item["error"]

    def test_quotation_falls_back_to_legacy_realtime(self):
        service = RealtimeQuotePollingService(
            get_pro=lambda: FakePro(
                stock_basic_df=_stock_basic_frame(),
                quotation_error=RuntimeError("permission denied"),
            ),
            legacy_quote_fetcher=lambda symbol: _legacy_frame(),
        )

        exit_code, payload = _run_cli(service, "--symbols", "600000")

        assert exit_code == 0
        item = payload["items"][0]
        assert item["status"] == "ok"
        assert item["quote_data"]["mode"] == "legacy_realtime"
        assert item["quote_data"]["change_pct"] is not None

    def test_missing_tushare_token_returns_failed_payload(self):
        service = RealtimeQuotePollingService(
            get_pro=lambda: (_ for _ in ()).throw(
                RuntimeError("缺少 TUSHARE_TOKEN，请先在环境变量中配置。")
            )
        )

        exit_code, payload = _run_cli(service, "--symbols", "600000")

        assert exit_code == 3
        assert payload["status"] == "failed"
        assert "TUSHARE_TOKEN" in payload["error"]
